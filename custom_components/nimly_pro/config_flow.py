"""Config flow for Nimly PRO."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_IEEE, DOMAIN, MANUFACTURER, SUPPORTED_MODELS, ZHA_DOMAIN

_LOGGER = logging.getLogger(__name__)


class NimlyProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Nimly PRO."""

    VERSION = 2

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle user step — select a Nimly lock from ZHA."""
        if ZHA_DOMAIN not in self.hass.data:
            return self.async_abort(reason="zha_not_found")

        zha_data = self.hass.data[ZHA_DOMAIN]
        if not hasattr(zha_data, "gateway_proxy"):
            return self.async_abort(reason="zha_not_found")

        # Find Nimly devices
        devices = {}
        for ieee, proxy in zha_data.gateway_proxy.device_proxies.items():
            device = proxy.device if hasattr(proxy, "device") else proxy
            manufacturer = getattr(device, "manufacturer", "")
            model = getattr(device, "model", "")
            if manufacturer == MANUFACTURER and model in SUPPORTED_MODELS:
                ieee_str = str(ieee)
                # Skip already configured
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
                title=f"Nimly PRO ({ieee[-8:]})",
                data={CONF_IEEE: ieee},
                options={"slots": {}},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(devices),
                }
            ),
        )
