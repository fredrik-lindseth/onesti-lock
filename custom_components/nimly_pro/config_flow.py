"""Config flow for Nimly Touch Pro integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ZHA_DOMAIN = "zha"


def get_zha_gateway(hass):
    """Get the ZHA gateway from hass.data."""
    if ZHA_DOMAIN not in hass.data:
        return None
    zha_data = hass.data[ZHA_DOMAIN]

    # For HA 2024.x+ with HAZHAData object
    if hasattr(zha_data, "gateway"):
        return zha_data.gateway

    # For HAZHAData object, try to access gateway_proxy
    if hasattr(zha_data, "gateway_proxy"):
        gateway_proxy = zha_data.gateway_proxy
        if hasattr(gateway_proxy, "gateway"):
            return gateway_proxy.gateway
        return gateway_proxy

    # Legacy: dict-based storage
    if isinstance(zha_data, dict):
        if "gateway" in zha_data:
            return zha_data["gateway"]
        for entry_data in zha_data.values():
            if hasattr(entry_data, "gateway"):
                return entry_data.gateway
            if isinstance(entry_data, dict) and "gateway" in entry_data:
                return entry_data["gateway"]

    _LOGGER.warning("Could not find ZHA gateway in data: %s", type(zha_data))
    return None


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nimly Touch Pro."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices = {}

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        zha_gateway = get_zha_gateway(self.hass)
        if not zha_gateway:
            return self.async_abort(reason="zha_not_found")

        if not hasattr(zha_gateway, "devices"):
            return self.async_abort(reason="zha_not_found")

        devices = zha_gateway.devices
        if hasattr(devices, "values"):
            device_list = list(devices.values())
        else:
            device_list = list(devices)

        # Filter for Nimly Touch Pro devices
        nimly_devices = {}
        for device in device_list:
            manufacturer = getattr(device, "manufacturer", "")
            model = getattr(device, "model", "")
            if (
                manufacturer == "Onesti Products AS"
                and model in ["NimlyPRO", "NimlyPRO24"]
            ):
                ieee_str = str(device.ieee)
                device_name = getattr(device, "name", None) or f"Nimly Lock {ieee_str}"
                nimly_devices[ieee_str] = device_name

        if not nimly_devices:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            selected_ieee = user_input["device"]
            await self.async_set_unique_id(selected_ieee)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Nimly Touch Pro {selected_ieee}",
                data={"ieee": selected_ieee},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("device"): vol.In(nimly_devices)}),
        )

    async def async_step_import(self, user_input=None):
        """Handle import from configuration.yaml."""
        return await self.async_step_user(user_input)
