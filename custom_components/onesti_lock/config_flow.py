"""Config flow and options flow for Onesti Lock."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

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
    DOMAIN,
    MANUFACTURER,
    MAX_SLOTS,
    SLOT_FIRST_USER,
    SUPPORTED_MODELS,
    ZHA_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class NimlyProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Onesti Lock."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NimlyProOptionsFlow()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle user step — select a Nimly lock from ZHA."""
        if ZHA_DOMAIN not in self.hass.data:
            return self.async_abort(reason="zha_not_found")

        zha_data = self.hass.data[ZHA_DOMAIN]
        if not hasattr(zha_data, "gateway_proxy") or zha_data.gateway_proxy is None:
            return self.async_abort(reason="zha_not_found")

        devices = {}
        for ieee, proxy in zha_data.gateway_proxy.device_proxies.items():
            device = proxy.device if hasattr(proxy, "device") else proxy
            manufacturer = getattr(device, "manufacturer", "")
            model = getattr(device, "model", "")
            if manufacturer == MANUFACTURER and model in SUPPORTED_MODELS:
                ieee_str = str(ieee)
                existing = {
                    entry.data.get(CONF_IEEE)
                    for entry in self._async_current_entries()
                }
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
    """Options flow for Onesti Lock — PIN code management UI."""

    _set_pin_task: asyncio.Task | None = None
    _set_pin_input: dict[str, Any] | None = None
    _set_pin_error: str | None = None
    _clear_pin_task: asyncio.Task | None = None
    _clear_pin_error: str | None = None

    # -- Helpers --

    def _build_set_pin_schema(
        self, suggested: dict[str, Any] | None = None,
    ) -> vol.Schema:
        """Build set_pin form schema, optionally pre-filling values."""
        slots = self.config_entry.options.get("slots", {})
        slot_options = {}
        for i in range(SLOT_FIRST_USER, SLOT_FIRST_USER + 10):
            name = slots.get(str(i), {}).get("name", "")
            label = f"Slot {i} — {name}" if name else f"Slot {i} — Ledig"
            slot_options[str(i)] = label

        schema = vol.Schema(
            {
                vol.Required("slot", default=str(SLOT_FIRST_USER)): vol.In(slot_options),
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
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        return await coordinator.set_pin(
            int(inp["slot"]), inp["name"], inp["code"],
        )

    async def _do_clear_pin(self) -> bool:
        """Background task: send clear_slot command to coordinator."""
        inp = self._set_pin_input  # reused for clear_pin slot
        assert inp is not None
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        return await coordinator.clear_slot(int(inp["slot"]))

    # -- Main menu --

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Main menu: choose action."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["set_pin", "clear_pin", "name_slot", "view_slots"],
        )

    # -- Set PIN: form → progress → result --

    async def async_step_set_pin(self, user_input=None) -> ConfigFlowResult:
        """Set a PIN code — show form, validate, start background task."""
        errors: dict[str, str] = {}
        suggested: dict[str, Any] | None = None

        # Returning from failed progress step — show error with preserved input
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
                # Input valid — store and kick off background task
                self._set_pin_input = user_input
                return await self.async_step_set_pin_progress()

        return self.async_show_form(
            step_id="set_pin",
            data_schema=self._build_set_pin_schema(suggested),
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

        # Error — route back to form with preserved input
        return self.async_show_progress_done(next_step_id="set_pin")

    # -- Clear PIN: form → progress → result --

    async def async_step_clear_pin(self, user_input=None) -> ConfigFlowResult:
        """Clear a PIN code — show form, start background task."""
        errors: dict[str, str] = {}

        # Build schema first to check for active slots
        slots = self.config_entry.options.get("slots", {})
        active_slots = {}
        for i in range(MAX_SLOTS):
            slot_data = slots.get(str(i), {})
            if slot_data.get("has_pin") or slot_data.get("name"):
                name = slot_data.get("name", "")
                label = f"Slot {i} — {name}" if name else f"Slot {i}"
                active_slots[str(i)] = label

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

        # Error — route back to form with preserved input
        return self.async_show_progress_done(next_step_id="clear_pin")

    # -- Name slot (for RFID, fingerprint, etc.) --

    async def async_step_name_slot(self, user_input=None) -> ConfigFlowResult:
        """Assign a name to any slot (for RFID tags, fingerprints, etc.)."""
        if user_input is not None:
            slot = int(user_input["slot"])
            name = user_input["name"]
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
            await coordinator.set_slot_name(slot, name)
            return self.async_create_entry(data=self.config_entry.options)

        return self.async_show_form(
            step_id="name_slot",
            data_schema=vol.Schema(
                {
                    vol.Required("slot"): vol.Coerce(int),
                    vol.Required("name"): str,
                }
            ),
        )

    # -- View slots --

    async def async_step_view_slots(self, user_input=None) -> ConfigFlowResult:
        """View current slot status — shown as description text."""
        slots = self.config_entry.options.get("slots", {})
        lines = []
        for i in range(SLOT_FIRST_USER, SLOT_FIRST_USER + 10):
            slot_data = slots.get(str(i), {})
            name = slot_data.get("name", "")
            has_pin = slot_data.get("has_pin", False)
            if name and has_pin:
                lines.append(f"Slot {i}: **{name}** (PIN aktiv)")
            elif name:
                lines.append(f"Slot {i}: {name} (ingen PIN)")
            else:
                lines.append(f"Slot {i}: Ledig")

        # Return to menu
        if user_input is not None:
            return await self.async_step_init()

        return self.async_show_form(
            step_id="view_slots",
            description_placeholders={"slot_status": "\n".join(lines)},
            data_schema=vol.Schema({}),
        )
