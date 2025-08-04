"""Config flow for Nimly Touch Pro integration."""
import logging
import voluptuous as vol
import zigpy.zha.api

from homeassistant import config_entries
from homeassistant.components.zha.core.const import DOMAIN as ZHA_DOMAIN
from homeassistant.components.zha.core.helpers import get_zha_gateway
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DOORLOCK_CLUSTER_ID

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nimly Touch Pro."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices = {}

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        # Get the ZHA gateway
        zha_gateway = get_zha_gateway(self.hass)
        if not zha_gateway:
            return self.async_abort(reason="zha_gateway_missing")

        # Get all devices from ZHA
        devices = zha_gateway.devices.values()
        
        # Filter for Nimly Touch Pro devices
        nimly_devices = {}
        for device in devices:
            # Check if this is a Nimly lock
            if (
                device.manufacturer == "Onesti Products AS" and
                device.model in ["NimlyPRO", "NimlyPRO24"]
            ):
                # Check if it has the door lock cluster
                for endpoint in device.endpoints.values():
                    if DOORLOCK_CLUSTER_ID in [cluster.cluster_id for cluster in endpoint.in_clusters.values()]:
                        nimly_devices[device.ieee] = device.name or f"Nimly Lock {device.ieee}"
                        
        if not nimly_devices:
            return self.async_abort(reason="no_devices_found")
            
        if user_input is not None:
            selected_ieee = user_input["device"]
            await self.async_set_unique_id(selected_ieee)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=f"Nimly Touch Pro {selected_ieee}",
                data={"ieee": selected_ieee}
            )
            
        # Show device selection form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(nimly_devices)
                }
            ),
        )
        
    async def async_step_import(self, user_input=None):
        """Handle import from configuration.yaml."""
        return await self.async_step_user(user_input)
