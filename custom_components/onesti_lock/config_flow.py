"""Config flow and options flow for Onesti Lock."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine, Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from . import pin_rules
from .const import (
    CONF_IEEE,
    CONF_RESERVED_SLOTS,
    DOMAIN,
    MANUFACTURER,
    MAX_SLOTS,
    NUM_USER_SLOTS,
    RESERVED_SLOTS_MAX,
    RESERVED_SLOTS_MIN,
    SUPPORTED_MODELS,
)
from .localize import async_get_strings, format_reserved_slot_row, format_slot_label
from .redact import redact_digits
from .zha import (
    Delivery,
    SendOutcome,
    device_metadata,
    has_door_lock_cluster,
    is_zha_loaded,
    iter_device_proxies,
)

if TYPE_CHECKING:
    from .coordinator import NimlyConfigEntry, NimlyCoordinator

_LOGGER = logging.getLogger(__name__)


class _FormError(NamedTuple):
    """A failed write as its form shows it: the error key and its placeholders."""

    key: str
    # {status} for the lock_rejected texts. Given to every form that can
    # show a write error, since the frontend fills an error's placeholders
    # from the form's description_placeholders.
    placeholders: dict[str, str]


class NimlyProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Onesti Lock."""

    VERSION = 2
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NimlyProOptionsFlow()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle user step: select a Nimly lock from ZHA."""
        if not is_zha_loaded(self.hass):
            return self.async_abort(reason="zha_not_found")

        devices = {}
        existing = {
            entry.data.get(CONF_IEEE)
            for entry in self._async_current_entries()
        }
        for ieee, proxy in iter_device_proxies(self.hass):
            manufacturer, model = device_metadata(proxy)
            # The model string is informational, not a gate. All Onesti
            # locks share hardware and the ZMNC010 Zigbee module, and a
            # module can report a sibling model name (issue #5: a CodePRO
            # presenting as Twist), so any Onesti device with a Door Lock
            # cluster is offered.
            if manufacturer != MANUFACTURER or not has_door_lock_cluster(proxy):
                continue
            if model not in SUPPORTED_MODELS:
                _LOGGER.warning(
                    "Unrecognized Onesti model %r, offering it anyway. "
                    "Please report the model string on GitHub",
                    model,
                )
            ieee_str = str(ieee)
            if ieee_str not in existing:
                devices[ieee_str] = f"{model} ({ieee_str})"

        if not devices:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            ieee = user_input["device"]
            await self.async_set_unique_id(ieee)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Onesti Lock ({ieee[-8:]})",
                data={CONF_IEEE: ieee},
                options={"slots": {}},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("device"): vol.In(devices)}
            ),
        )


class NimlyProOptionsFlow(OptionsFlow):
    """Options flow for Onesti Lock: PIN code management UI.

    set_pin and clear_pin each keep their own input, task and pending error,
    so a failure on one path never feeds the other. All of it is instance
    state: HA builds one flow object per open dialog, and two dialogs must
    not see each other's input.
    """

    def __init__(self) -> None:
        super().__init__()
        self._set_pin_input: dict[str, Any] | None = None
        self._set_pin_task: asyncio.Task[_FormError | None] | None = None
        self._set_pin_error: _FormError | None = None
        self._clear_pin_input: dict[str, Any] | None = None
        self._clear_pin_task: asyncio.Task[_FormError | None] | None = None
        self._clear_pin_error: _FormError | None = None

    # -- Helpers --

    def _coordinator(self) -> NimlyCoordinator:
        entry: NimlyConfigEntry = self.config_entry
        return entry.runtime_data

    def _pin_length_placeholders(self) -> dict[str, str]:
        """{min} and {max} for the set_pin texts, from the lock's reported range."""
        low, high = pin_rules.pin_length_range(self._coordinator().lock_capabilities)
        return {"min": str(low), "max": str(high)}

    def _build_set_pin_schema(
        self,
        strings: Mapping[str, str],
        suggested: dict[str, Any] | None = None,
    ) -> vol.Schema:
        """Build set_pin form schema, optionally pre-filling values."""
        slots = self.config_entry.options.get("slots", {})
        vacant = strings.get("slot_vacant", "Vacant")
        first = self._coordinator().first_user_slot()
        slot_options = {}
        for i in range(first, first + NUM_USER_SLOTS):
            name = slots.get(str(i), {}).get("name", "")
            slot_options[str(i)] = format_slot_label(strings, i, name or vacant)

        schema = vol.Schema(
            {
                vol.Required("slot", default=str(first)): vol.In(slot_options),
                vol.Required("name"): str,
                vol.Required("code"): str,
            }
        )
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)
        return schema

    def _start_write(
        self, write: Coroutine[Any, Any, _FormError | None]
    ) -> asyncio.Task[_FormError | None]:
        """Run a PIN write so that closing the dialog cannot interrupt it.

        HA cancels the progress task when the dialog closes. By then the
        command may have reached the lock, and cancelling before the save
        would leave storage describing the old code. The write therefore runs
        as its own task, logs its own outcome, and the progress task only
        waits for it through asyncio.shield.
        """
        write_task = self.hass.async_create_task(write)

        async def wait_for_write() -> _FormError | None:
            return await asyncio.shield(write_task)

        return self.hass.async_create_task(wait_for_write())

    async def _write(
        self, action: str, slot: int, write: Coroutine[Any, Any, SendOutcome]
    ) -> _FormError | None:
        """Await a coordinator write and log how it went.

        Returns the form error, or None on success. The log line is the
        only trace of the outcome once the dialog is gone. It carries the
        slot, never the PIN code.
        """
        entry_id = self.config_entry.entry_id
        try:
            outcome = await write
        except TimeoutError:
            _LOGGER.warning("Timeout %s on slot %s for %s", action, slot, entry_id)
            return _FormError("lock_unreachable", {})
        except Exception as err:
            # No traceback and a redacted message: the transport promises
            # never to raise, and if it breaks that promise the error may
            # quote the command params, PIN included.
            _LOGGER.error(
                "Unexpected error %s on slot %s for %s: %s: %s",
                action,
                slot,
                entry_id,
                type(err).__name__,
                redact_digits(err),
            )
            return _FormError("unknown", {})
        key = outcome.error_key
        if key is None:
            _LOGGER.debug("Finished %s on slot %s for %s", action, slot, entry_id)
            return None
        if outcome.delivery is Delivery.UNREACHED:
            _LOGGER.warning("Lock did not confirm %s on slot %s for %s", action, slot, entry_id)
            return _FormError(key, {})
        _LOGGER.warning(
            "Lock refused %s on slot %s for %s with status %s",
            action,
            slot,
            entry_id,
            outcome.status_text,
        )
        return _FormError(key, {"status": outcome.status_text})

    @staticmethod
    def _task_error(task: asyncio.Task[_FormError | None]) -> _FormError | None:
        """The form error a finished write task left, or None on success."""
        if task.cancelled():
            # Only the write itself being cancelled gets here, which happens
            # when HA shuts down under it.
            return _FormError("unknown", {})
        return task.result()

    @callback
    def async_remove(self) -> None:
        """Say so when the dialog closes while a write is still running."""
        for action, task in (
            ("setting PIN", self._set_pin_task),
            ("clearing PIN", self._clear_pin_task),
        ):
            if task is not None and not task.done():
                _LOGGER.info(
                    "Options dialog for %s closed while %s; the command keeps "
                    "running and its result is logged",
                    self.config_entry.entry_id,
                    action,
                )

    # -- Main menu --

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Main menu: choose action, or say that the lock is not running.

        Every step below reads the coordinator from entry.runtime_data, which
        Home Assistant sets while the entry is loaded and drops on unload. A
        lock that is missing from ZHA leaves the entry in SETUP_RETRY, and
        reading it there is an AttributeError the dialog shows as "Unknown
        error". The menu is the only way into this flow, so the check belongs
        here.
        """
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="lock_not_loaded")

        return self.async_show_menu(
            step_id="init",
            menu_options=["set_pin", "clear_pin", "name_slot", "view_slots", "settings"],
        )

    # -- Set PIN: form → progress → result --

    async def async_step_set_pin(self, user_input=None) -> ConfigFlowResult:
        """Set a PIN code: show form, validate, start background task."""
        errors: dict[str, str] = {}
        suggested: dict[str, Any] | None = None
        error_placeholders: dict[str, str] = {}

        # Returning from a failed progress step: show the error with the input
        # preserved. Checked before user_input, since HA can route back here
        # with the submitted input still attached (see async_step_clear_pin).
        if self._set_pin_error:
            errors["base"] = self._set_pin_error.key
            error_placeholders = self._set_pin_error.placeholders
            suggested = self._set_pin_input
            self._set_pin_error = None
        elif user_input is not None:
            if not pin_rules.is_valid_pin(
                user_input["code"], self._coordinator().lock_capabilities
            ):
                errors["code"] = "invalid_pin"
                suggested = user_input
            else:
                self._set_pin_input = user_input
                return await self.async_step_set_pin_progress()

        # The schema builder is synchronous, so the strings are resolved here
        # and passed in.
        strings = await async_get_strings(self.hass, self.hass.config.language)
        return self.async_show_form(
            step_id="set_pin",
            data_schema=self._build_set_pin_schema(strings, suggested),
            errors=errors,
            # Always sent, not only with the error: the frontend fills
            # {min}-{max} in invalid_pin from the form's placeholders.
            description_placeholders={
                **self._pin_length_placeholders(),
                **error_placeholders,
            },
        )

    async def async_step_set_pin_progress(
        self, user_input=None,
    ) -> ConfigFlowResult:
        """Show a spinner while set_pin runs, then route on its outcome.

        HA runs this step again once the progress task finishes, so the step
        itself has to notice that the task is done and move the flow on.
        """
        if not self._set_pin_task:
            inp = self._set_pin_input
            assert inp is not None
            slot = int(inp["slot"])
            self._set_pin_task = self._start_write(
                self._write(
                    "setting PIN",
                    slot,
                    self._coordinator().set_pin(slot, inp["name"], inp["code"]),
                )
            )

        if not self._set_pin_task.done():
            return self.async_show_progress(
                step_id="set_pin_progress",
                progress_action="set_pin_progress",
                progress_task=self._set_pin_task,
            )

        task = self._set_pin_task
        self._set_pin_task = None
        self._set_pin_error = self._task_error(task)
        if self._set_pin_error:
            # The form step shows the error with the input preserved.
            return self.async_show_progress_done(next_step_id="set_pin")
        return self.async_show_progress_done(next_step_id="set_pin_done")

    async def async_step_set_pin_done(
        self, user_input=None,
    ) -> ConfigFlowResult:
        """Finish the flow after the lock accepted the PIN."""
        self._set_pin_input = None
        # Read now, not when the dialog opened: the coordinator has saved this
        # write, and any other flow's or service's that finished meanwhile.
        return self.async_create_entry(data=self.config_entry.options)

    # -- Clear PIN: form → progress → result --

    async def async_step_clear_pin(self, user_input=None) -> ConfigFlowResult:
        """Clear a PIN code: show form, start background task."""
        errors: dict[str, str] = {}

        strings = await async_get_strings(self.hass, self.hass.config.language)
        fallback_template = strings.get("slot_fallback_name", "Slot {slot}")
        slots = self.config_entry.options.get("slots", {})
        # Only slots with a PIN: a slot that is merely named may hold an RFID
        # tag or a fingerprint, and has no code to clear. Reserved master
        # slots are never offered, since the coordinator refuses them.
        first = self._coordinator().first_user_slot()
        active_slots = {}
        for i in range(first, MAX_SLOTS):
            slot_data = slots.get(str(i), {})
            if not slot_data.get("has_pin"):
                continue
            name = slot_data.get("name", "")
            if name:
                active_slots[str(i)] = format_slot_label(strings, i, name)
            else:
                active_slots[str(i)] = fallback_template.format(slot=i)

        if not active_slots:
            return self.async_abort(reason="no_active_slots")

        # A failed attempt is checked before user_input: when the task finishes
        # within the submit itself, HA routes progress_done back here with the
        # submitted input still attached, and it must not start another send.
        suggested: dict[str, Any] | None = None
        error_placeholders: dict[str, str] = {}
        if self._clear_pin_error:
            errors["base"] = self._clear_pin_error.key
            error_placeholders = self._clear_pin_error.placeholders
            suggested = self._clear_pin_input
            self._clear_pin_error = None
        elif user_input is not None:
            self._clear_pin_input = user_input
            return await self.async_step_clear_pin_progress()

        schema = vol.Schema(
            {vol.Required("slot"): vol.In(active_slots)}
        )
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)

        return self.async_show_form(
            step_id="clear_pin",
            data_schema=schema,
            errors=errors,
            description_placeholders=error_placeholders,
        )

    async def async_step_clear_pin_progress(
        self, user_input=None,
    ) -> ConfigFlowResult:
        """Show a spinner while clear_pin runs, then route on its outcome.

        Same shape as async_step_set_pin_progress.
        """
        if not self._clear_pin_task:
            inp = self._clear_pin_input
            assert inp is not None
            slot = int(inp["slot"])
            # clear_pin, not clear_slot: the name stays, as the step text says.
            self._clear_pin_task = self._start_write(
                self._write("clearing PIN", slot, self._coordinator().clear_pin(slot))
            )

        if not self._clear_pin_task.done():
            return self.async_show_progress(
                step_id="clear_pin_progress",
                progress_action="clear_pin_progress",
                progress_task=self._clear_pin_task,
            )

        task = self._clear_pin_task
        self._clear_pin_task = None
        self._clear_pin_error = self._task_error(task)
        if self._clear_pin_error:
            return self.async_show_progress_done(next_step_id="clear_pin")
        return self.async_show_progress_done(next_step_id="clear_pin_done")

    async def async_step_clear_pin_done(
        self, user_input=None,
    ) -> ConfigFlowResult:
        """Finish the flow after the lock cleared the PIN."""
        self._clear_pin_input = None
        # Read now, for the same reason as in async_step_set_pin_done.
        return self.async_create_entry(data=self.config_entry.options)

    # -- Name slot (for RFID, fingerprint, etc.) --

    async def async_step_name_slot(self, user_input=None) -> ConfigFlowResult:
        """Assign a name to any slot (for RFID tags, fingerprints, etc.)."""
        errors: dict[str, str] = {}
        suggested: dict[str, Any] | None = None
        if user_input is not None:
            slot = int(user_input["slot"])
            # Same range set_name enforces. Names never reach the lock, so
            # master slots can be named too (issue #6).
            if not 0 <= slot < MAX_SLOTS:
                errors["slot"] = "invalid_slot"
                suggested = user_input
            else:
                # An empty name removes it, and a slot left with neither name
                # nor PIN is dropped from storage. That is the only way to
                # unname a reserved slot, since clear_slot refuses those.
                await self._coordinator().set_slot_name(slot, user_input.get("name", "").strip())
                return self.async_create_entry(data=self.config_entry.options)

        schema = vol.Schema(
            {
                vol.Required("slot"): vol.Coerce(int),
                vol.Optional("name", default=""): str,
            }
        )
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)

        return self.async_show_form(
            step_id="name_slot",
            data_schema=schema,
            errors=errors,
        )

    # -- View slots --

    async def async_step_view_slots(self, user_input=None) -> ConfigFlowResult:
        """View current slot status, shown as description text."""
        strings = await async_get_strings(self.hass, self.hass.config.language)
        pin_active = strings.get("slot_status_pin_active", "(PIN active)")
        no_pin = strings.get("slot_status_no_pin", "(no PIN)")
        vacant = strings.get("slot_vacant", "Vacant")
        slots = self.config_entry.options.get("slots", {})
        first = self._coordinator().first_user_slot()
        lines = []
        # Reserved master slots first: they cannot be written from here, but
        # a name on them is what events show for the master user. They hold
        # a master code, so they are never "Vacant".
        for i in range(first):
            name = slots.get(str(i), {}).get("name", "")
            lines.append(format_reserved_slot_row(strings, i, name))
        for i in range(first, first + NUM_USER_SLOTS):
            slot_data = slots.get(str(i), {})
            name = slot_data.get("name", "")
            has_pin = slot_data.get("has_pin", False)
            if name and has_pin:
                line = format_slot_label(strings, i, f"**{name}**")
                lines.append(f"{line} {pin_active}")
            elif name:
                line = format_slot_label(strings, i, name)
                lines.append(f"{line} {no_pin}")
            else:
                lines.append(format_slot_label(strings, i, vacant))

        # Return to menu
        if user_input is not None:
            return await self.async_step_init()

        return self.async_show_form(
            step_id="view_slots",
            description_placeholders={"slot_status": "\n".join(lines)},
            data_schema=vol.Schema({}),
        )

    # -- Settings --

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        """Per-lock settings: how many slots from 0 up are master codes."""
        if user_input is not None:
            # Merged into the existing options, which also hold slot data.
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_RESERVED_SLOTS: int(user_input[CONF_RESERVED_SLOTS]),
                }
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RESERVED_SLOTS,
                        default=self._coordinator().first_user_slot(),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=RESERVED_SLOTS_MIN, max=RESERVED_SLOTS_MAX),
                    ),
                }
            ),
        )
