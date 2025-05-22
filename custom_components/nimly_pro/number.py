"""Number platform for Nimly Touch Pro integration."""
import logging
from typing import Any, Callable, Dict, List, Optional

from zigpy.exceptions import ZigbeeException

from homeassistant.components.number import NumberEntity
from homeassistant.components.zha.core.helpers import get_zha_gateway
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    DOORLOCK_CLUSTER_ID,
    ATTR_AUTO_RELOCK_TIME,
    NAME_AUTO_RELOCK,
    DEFAULT_AUTO_RELOCK_TIME,
)

_LOGGER = logging.getLogger(__name__)

# Polling interval
SCAN_INTERVAL = dt_util.timedelta(seconds=60)

async def async_setup_entry(
    hass: HomeAssistant, 
    config_entry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Nimly Touch Pro number entities from a config entry."""
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
            NimlyProAutoRelockTime(zha_device, doorlock_endpoint, doorlock_cluster)
        ])

class NimlyProAutoRelockTime(NumberEntity):
    """Representation of Nimly Touch Pro Auto Relock Time setting."""
    
    def __init__(self, zha_device, endpoint, cluster):
        """Initialize the number entity."""
        self._zha_device = zha_device
        self._endpoint = endpoint
        self._cluster = cluster
        
        self._attr_name = f"{zha_device.name} {NAME_AUTO_RELOCK}"
        self._attr_unique_id = f"{zha_device.ieee}_{endpoint.endpoint_id}_auto_relock"
        self._attr_native_min_value = 0  # 0 seconds (disabled)
        self._attr_native_max_value = 3600  # 1 hour
        self._attr_native_step = 1  # 1 second steps
        self._attr_native_value = DEFAULT_AUTO_RELOCK_TIME
        self._attr_mode = "slider"
        self._attr_native_unit_of_measurement = "seconds"
        self._available = True
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._zha_device.available and self._available
        
    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        try:
            # Write the attribute to the lock
            await self._cluster.write_attributes({
                int(ATTR_AUTO_RELOCK_TIME, 16): int(value)
            })
            self._attr_native_value = value
            self.async_write_ha_state()
        except ZigbeeException as ex:
            _LOGGER.error("Error setting auto relock time: %s", ex)
        
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Register to listen for attribute changes
        self.async_on_remove(
            self._endpoint.add_listener(self)
        )
        
        # Initial data fetch
        await self._update_auto_relock_time()
        
        # Set up regular polling
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_update, SCAN_INTERVAL
            )
        )
        
    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_auto_relock_time()
        
    async def _update_auto_relock_time(self):
        """Update auto-relock time value."""
        try:
            # Read the auto-relock time attribute
            result = await self._cluster.read_attributes([ATTR_AUTO_RELOCK_TIME])
            if ATTR_AUTO_RELOCK_TIME in result[0]:
                value = result[0][ATTR_AUTO_RELOCK_TIME]
                if value is not None:
                    self._attr_native_value = value
                self._available = True
                
        except ZigbeeException as ex:
            _LOGGER.debug("Error reading auto-relock time: %s", ex)
            self._available = False
            
        self.async_write_ha_state()
        
    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        if attrid == int(ATTR_AUTO_RELOCK_TIME, 16):
            if value is not None:
                self._attr_native_value = value
                self.async_write_ha_state()
