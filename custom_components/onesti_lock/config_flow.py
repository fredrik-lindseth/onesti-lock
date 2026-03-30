"""Config flow and options flow for Onesti Lock."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.data_entry_flow import FlowResult

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
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NimlyProOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle user step — select a Nimly lock from ZHA."""
        if ZHA_DOMAIN not in self.hass.data:
            return self.async_abort(reason="zha_not_found")

        zha_data = self.hass.data[ZHA_DOMAIN]
        if not hasattr(zha_data, "gateway_proxy"):
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

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Main menu: choose action."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["set_pin", "clear_pin", "view_slots"],
        )

    async def async_step_set_pin(self, user_input=None) -> FlowResult:
        """Set a PIN code for a slot."""
        errors = {}

        if user_input is not None:
            slot = int(user_input["slot"])
            name = user_input["name"]
            code = user_input["code"]

            if not code.isdigit() or len(code) < 4 or len(code) > 8:
                errors["code"] = "invalid_pin"
            else:
                # Get coordinator and set PIN
                coordinator = self.hass.data[DOMAIN][self._entry.entry_id]["coordinator"]
                success = await coordinator.set_pin(slot, name, code)
                if success:
                    return self.async_create_entry(data=self._entry.options)
                errors["base"] = "lock_unreachable"

        # Build slot descriptions for the dropdown
        slots = self._entry.options.get("slots", {})
        slot_options = {}
        for i in range(SLOT_FIRST_USER, SLOT_FIRST_USER + 10):
            name = slots.get(str(i), {}).get("name", "")
            label = f"Slot {i} — {name}" if name else f"Slot {i} — Ledig"
            slot_options[str(i)] = label

        return self.async_show_form(
            step_id="set_pin",
            data_schema=vol.Schema(
                {
                    vol.Required("slot", default=str(SLOT_FIRST_USER)): vol.In(slot_options),
                    vol.Required("name"): str,
                    vol.Required("code"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_clear_pin(self, user_input=None) -> FlowResult:
        """Clear a PIN code from a slot."""
        errors = {}

        if user_input is not None:
            slot = int(user_input["slot"])
            coordinator = self.hass.data[DOMAIN][self._entry.entry_id]["coordinator"]
            success = await coordinator.clear_slot(slot)
            if success:
                return self.async_create_entry(data=self._entry.options)
            errors["base"] = "lock_unreachable"

        # Only show slots that have a PIN
        slots = self._entry.options.get("slots", {})
        active_slots = {}
        for i in range(MAX_SLOTS):
            slot_data = slots.get(str(i), {})
            if slot_data.get("has_pin") or slot_data.get("name"):
                name = slot_data.get("name", "")
                label = f"Slot {i} — {name}" if name else f"Slot {i}"
                active_slots[str(i)] = label

        if not active_slots:
            return self.async_abort(reason="no_active_slots")

        return self.async_show_form(
            step_id="clear_pin",
            data_schema=vol.Schema(
                {vol.Required("slot"): vol.In(active_slots)}
            ),
            errors=errors,
        )

    async def async_step_view_slots(self, user_input=None) -> FlowResult:
        """View current slot status — shown as description text."""
        slots = self._entry.options.get("slots", {})
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
