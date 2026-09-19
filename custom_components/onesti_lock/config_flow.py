"""Config flow and options flow for Onesti Lock."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

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
from .localize import async_get_strings, format_reserved_slot_row
from .zha import device_metadata, has_door_lock_cluster, is_zha_loaded, iter_device_proxies

if TYPE_CHECKING:
    from .coordinator import NimlyCoordinator

_LOGGER = logging.getLogger(__name__)


class NimlyProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Onesti Lock."""

    VERSION = 2

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
    """Options flow for Onesti Lock: PIN code management UI."""

    _set_pin_task: asyncio.Task | None = None
    _set_pin_input: dict[str, Any] | None = None
    _set_pin_error: str | None = None
    _clear_pin_task: asyncio.Task | None = None
    _clear_pin_error: str | None = None

    # -- Helpers --

    def _coordinator(self) -> NimlyCoordinator:
        return self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]

    def _build_set_pin_schema(
        self,
        strings: Mapping[str, str],
        suggested: dict[str, Any] | None = None,
    ) -> vol.Schema:
        """Build set_pin form schema, optionally pre-filling values."""
        slots = self.config_entry.options.get("slots", {})
        label_template = strings.get("slot_label", "Slot {slot}: {name}")
        vacant = strings.get("slot_vacant", "Vacant")
        first = self._coordinator().first_user_slot()
        slot_options = {}
        for i in range(first, first + NUM_USER_SLOTS):
            name = slots.get(str(i), {}).get("name", "")
            slot_options[str(i)] = label_template.format(slot=i, name=name or vacant)

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

    async def _do_set_pin(self) -> bool:
        """Background task: send set_pin command to coordinator."""
        inp = self._set_pin_input
        assert inp is not None
        return await self._coordinator().set_pin(
            int(inp["slot"]), inp["name"], inp["code"],
        )

    async def _do_clear_pin(self) -> bool:
        """Background task: send clear_slot command to coordinator."""
        inp = self._set_pin_input  # reused for clear_pin slot
        assert inp is not None
        return await self._coordinator().clear_slot(int(inp["slot"]))

    # -- Main menu --

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Main menu: choose action."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["set_pin", "clear_pin", "name_slot", "view_slots", "settings"],
        )

    # -- Set PIN: form → progress → result --

    async def async_step_set_pin(self, user_input=None) -> ConfigFlowResult:
        """Set a PIN code: show form, validate, start background task."""
        errors: dict[str, str] = {}
        suggested: dict[str, Any] | None = None

        # Returning from failed progress step: show error with preserved input
        if self._set_pin_error:
            errors["base"] = self._set_pin_error
            suggested = self._set_pin_input
            self._set_pin_error = None
        elif user_input is not None:
            code = user_input["code"]

            if not code.isdigit() or len(code) < 4 or len(code) > 8:
                errors["code"] = "invalid_pin"
                suggested = user_input
            else:
                # Input valid: store and kick off background task
                self._set_pin_input = user_input
                return await self.async_step_set_pin_progress()

        # The schema builder is synchronous, so the strings are resolved here
        # and passed in.
        strings = await async_get_strings(self.hass, self.hass.config.language)
        return self.async_show_form(
            step_id="set_pin",
            data_schema=self._build_set_pin_schema(strings, suggested),
            errors=errors,
        )

    async def async_step_set_pin_progress(
        self, user_input=None,
    ) -> ConfigFlowResult:
        """Show spinner while set_pin runs in background."""
        if not self._set_pin_task:
            self._set_pin_task = self.hass.async_create_task(
                self._do_set_pin()
            )

        return self.async_show_progress(
            step_id="set_pin_progress",
            progress_action="set_pin_progress",
            progress_task=self._set_pin_task,
        )

    async def async_step_set_pin_progress_done(
        self, user_input=None,
    ) -> ConfigFlowResult:
        """Called automatically when set_pin_task completes."""
        # NOTE: HA calls this step when the progress_task finishes.
        # The naming convention is {progress_action}_done.
        task = self._set_pin_task
        self._set_pin_task = None

        try:
            success = task.result()
        except TimeoutError:
            _LOGGER.warning("Timeout setting PIN for %s", self.config_entry.entry_id)
            self._set_pin_error = "lock_unreachable"
        except Exception:
            _LOGGER.exception("Unexpected error setting PIN for %s", self.config_entry.entry_id)
            self._set_pin_error = "unknown"
        else:
            if success:
                self._set_pin_input = None
                return self.async_create_entry(data=self.config_entry.options)
            self._set_pin_error = "lock_unreachable"

        # Error: route back to form with preserved input
        return self.async_show_progress_done(next_step_id="set_pin")

    # -- Clear PIN: form → progress → result --

    async def async_step_clear_pin(self, user_input=None) -> ConfigFlowResult:
        """Clear a PIN code: show form, start background task."""
        errors: dict[str, str] = {}

        # Build schema first to check for active slots
        strings = await async_get_strings(self.hass, self.hass.config.language)
        label_template = strings.get("slot_label", "Slot {slot}: {name}")
        fallback_template = strings.get("slot_fallback_name", "Slot {slot}")
        slots = self.config_entry.options.get("slots", {})
        # Reserved master slots are never offered: clear_slot refuses them,
        # and a named slot 0 would otherwise show up as removable.
        first = self._coordinator().first_user_slot()
        active_slots = {}
        for i in range(first, MAX_SLOTS):
            slot_data = slots.get(str(i), {})
            if slot_data.get("has_pin") or slot_data.get("name"):
                name = slot_data.get("name", "")
                if name:
                    active_slots[str(i)] = label_template.format(slot=i, name=name)
                else:
                    active_slots[str(i)] = fallback_template.format(slot=i)

        if not active_slots:
            return self.async_abort(reason="no_active_slots")

        if user_input is not None:
            # Store input and kick off background task
            self._set_pin_input = user_input  # reuse for slot reference
            self._clear_pin_error = None
            return await self.async_step_clear_pin_progress()

        # Show form (possibly with error from previous attempt)
        if self._clear_pin_error:
            errors["base"] = self._clear_pin_error
            self._clear_pin_error = None

        suggested = self._set_pin_input if errors else None
        schema = vol.Schema(
            {vol.Required("slot"): vol.In(active_slots)}
        )
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)

        return self.async_show_form(
            step_id="clear_pin",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_clear_pin_progress(
        self, user_input=None,
    ) -> ConfigFlowResult:
        """Show spinner while clear_pin runs in background."""
        if not self._clear_pin_task:
            self._clear_pin_task = self.hass.async_create_task(
                self._do_clear_pin()
            )

        return self.async_show_progress(
            step_id="clear_pin_progress",
            progress_action="clear_pin_progress",
            progress_task=self._clear_pin_task,
        )

    async def async_step_clear_pin_progress_done(
        self, user_input=None,
    ) -> ConfigFlowResult:
        """Called automatically when clear_pin_task completes."""
        task = self._clear_pin_task
        self._clear_pin_task = None

        try:
            success = task.result()
        except TimeoutError:
            _LOGGER.warning("Timeout clearing PIN for %s", self.config_entry.entry_id)
            self._clear_pin_error = "lock_unreachable"
        except Exception:
            _LOGGER.exception("Unexpected error clearing PIN for %s", self.config_entry.entry_id)
            self._clear_pin_error = "unknown"
        else:
            if success:
                self._set_pin_input = None
                return self.async_create_entry(data=self.config_entry.options)
            self._clear_pin_error = "lock_unreachable"

        # Error: route back to form with preserved input
        return self.async_show_progress_done(next_step_id="clear_pin")

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
        label_template = strings.get("slot_label", "Slot {slot}: {name}")
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
                line = label_template.format(slot=i, name=f"**{name}**")
                lines.append(f"{line} {pin_active}")
            elif name:
                line = label_template.format(slot=i, name=name)
                lines.append(f"{line} {no_pin}")
            else:
                lines.append(label_template.format(slot=i, name=vacant))

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
