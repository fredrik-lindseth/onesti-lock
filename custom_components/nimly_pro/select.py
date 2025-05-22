"""Select platform for Nimly Touch Pro integration."""
import logging
from typing import Any, Callable, Dict, List, Optional

from zigpy.exceptions import ZigbeeException

from homeassistant.components.select import SelectEntity
from homeassistant.components.zha.core.helpers import get_zha_gateway
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    DOORLOCK_CLUSTER_ID,
    ATTR_LED_SETTINGS,
    ATTR_SOUND_VOLUME,
    NAME_LED_SETTINGS,
    NAME_SOUND_VOLUME,
    LED_SETTINGS_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

# Polling interval
SCAN_INTERVAL = dt_util.timedelta(seconds=60)

# Sound volume options
SOUND_VOLUME_OPTIONS = {
    0: "Off",
    1: "Low",
    2: "Medium",
    3: "High"
}

async def async_setup_entry(
    hass: HomeAssistant, 
    config_entry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Nimly Touch Pro select entities from a config entry."""
    ieee = config_entry.data["ieee"]
    
    # Get the ZHA gateway
    zha_gateway = get_zha_gateway(hass)
    if not zha_gateway:
        _LOGGER.error("ZHA gateway not found")
        return
        
    # Find the ZHA device
    zha_device = zha_gateway.get_device(ieee)
    if not zha_device:
        _LOGGER.error("ZHA device not found for %s", ieee)
        return
    
    # Find the endpoint with the door lock cluster
    doorlock_endpoint = None
    doorlock_cluster = None
    for endpoint_id, endpoint in zha_device.endpoints.items():
        if endpoint_id != 0:  # Skip ZDO endpoint
            clusters = endpoint.in_clusters
            if any(cluster.cluster_id == DOORLOCK_CLUSTER_ID for cluster in clusters.values()):
                doorlock_endpoint = endpoint
                doorlock_cluster = next(
                    cluster for cluster in clusters.values() 
                    if cluster.cluster_id == DOORLOCK_CLUSTER_ID
                )
                break
                
    if doorlock_endpoint and doorlock_cluster:
        async_add_entities([
            NimlyProLEDSettingsSelect(zha_device, doorlock_endpoint, doorlock_cluster),
            NimlyProSoundVolumeSelect(zha_device, doorlock_endpoint, doorlock_cluster)
        ])

class NimlyProLEDSettingsSelect(SelectEntity):
    """Representation of Nimly Touch Pro LED Settings selector."""
    
    def __init__(self, zha_device, endpoint, cluster):
        """Initialize the select entity."""
        self._zha_device = zha_device
        self._endpoint = endpoint
        self._cluster = cluster
        
        self._attr_name = f"{zha_device.name} {NAME_LED_SETTINGS}"
        self._attr_unique_id = f"{zha_device.ieee}_{endpoint.endpoint_id}_led_settings"
        self._attr_options = list(LED_SETTINGS_OPTIONS.values())
        self._current_option_index = 0  # Default to the first option
        self._available = True
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._zha_device.available and self._available
        
    @property
    def current_option(self) -> str:
        """Return the selected option."""
        return self._attr_options[self._current_option_index]
        
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        # Find the index of the option
        option_index = self._attr_options.index(option)
        
        try:
            # Write the attribute to the lock
            await self._cluster.write_attributes({
                int(ATTR_LED_SETTINGS, 16): option_index
            })
            self._current_option_index = option_index
            self.async_write_ha_state()
        except ZigbeeException as ex:
            _LOGGER.error("Error setting LED brightness: %s", ex)
        
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Register to listen for attribute changes
        self.async_on_remove(
            self._endpoint.add_listener(self)
        )
        
        # Initial data fetch
        await self._update_led_settings()
        
        # Set up regular polling
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_update, SCAN_INTERVAL
            )
        )
        
    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_led_settings()
        
    async def _update_led_settings(self):
        """Update LED settings value."""
        try:
            # Read the LED settings attribute
            result = await self._cluster.read_attributes([ATTR_LED_SETTINGS])
            if ATTR_LED_SETTINGS in result[0]:
                value = result[0][ATTR_LED_SETTINGS]
                if value is not None and 0 <= value < len(self._attr_options):
                    self._current_option_index = value
                self._available = True
                
        except ZigbeeException as ex:
            _LOGGER.debug("Error reading LED settings: %s", ex)
            self._available = False
            
        self.async_write_ha_state()
        
    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        if attrid == int(ATTR_LED_SETTINGS, 16):
            if value is not None and 0 <= value < len(self._attr_options):
                self._current_option_index = value
                self.async_write_ha_state()

class NimlyProSoundVolumeSelect(SelectEntity):
    """Representation of Nimly Touch Pro Sound Volume selector."""
    
    def __init__(self, zha_device, endpoint, cluster):
        """Initialize the select entity."""
        self._zha_device = zha_device
        self._endpoint = endpoint
        self._cluster = cluster
        
        self._attr_name = f"{zha_device.name} {NAME_SOUND_VOLUME}"
        self._attr_unique_id = f"{zha_device.ieee}_{endpoint.endpoint_id}_sound_volume"
        self._attr_options = list(SOUND_VOLUME_OPTIONS.values())
        self._current_option_index = 0  # Default to the first option
        self._available = True
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._zha_device.available and self._available
        
    @property
    def current_option(self) -> str:
        """Return the selected option."""
        return self._attr_options[self._current_option_index]
        
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        # Find the index of the option
        option_index = self._attr_options.index(option)
        
        try:
            # Write the attribute to the lock
            await self._cluster.write_attributes({
                int(ATTR_SOUND_VOLUME, 16): option_index
            })
            self._current_option_index = option_index
            self.async_write_ha_state()
        except ZigbeeException as ex:
            _LOGGER.error("Error setting sound volume: %s", ex)
        
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Register to listen for attribute changes
        self.async_on_remove(
            self._endpoint.add_listener(self)
        )
        
        # Initial data fetch
        await self._update_sound_volume()
        
        # Set up regular polling
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_update, SCAN_INTERVAL
            )
        )
        
    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_sound_volume()
        
    async def _update_sound_volume(self):
        """Update sound volume value."""
        try:
            # Read the sound volume attribute
            result = await self._cluster.read_attributes([ATTR_SOUND_VOLUME])
            if ATTR_SOUND_VOLUME in result[0]:
                value = result[0][ATTR_SOUND_VOLUME]
                if value is not None and 0 <= value < len(self._attr_options):
                    self._current_option_index = value
                self._available = True
                
        except ZigbeeException as ex:
            _LOGGER.debug("Error reading sound volume: %s", ex)
            self._available = False
            
        self.async_write_ha_state()
        
    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        if attrid == int(ATTR_SOUND_VOLUME, 16):
            if value is not None and 0 <= value < len(self._attr_options):
                self._current_option_index = value
                self.async_write_ha_state()
