"""Binary sensor platform for Nimly Touch Pro integration."""
import logging
from typing import Any, Callable, Dict, List, Optional

from zigpy.exceptions import ZigbeeException

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.zha.core.helpers import get_zha_gateway
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    DOORLOCK_CLUSTER_ID,
    ATTR_DOOR_STATE,
    NAME_DOOR_STATE,
)

_LOGGER = logging.getLogger(__name__)

# Polling interval
SCAN_INTERVAL = dt_util.timedelta(seconds=30)

# Door state values based on ZCL spec
DOOR_STATE_OPEN = 0
DOOR_STATE_CLOSED = 1

async def async_setup_entry(
    hass: HomeAssistant, 
    config_entry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Nimly Touch Pro binary sensors from a config entry."""
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
            NimlyProDoorStateSensor(zha_device, doorlock_endpoint, doorlock_cluster)
        ])

class NimlyProDoorStateSensor(BinarySensorEntity):
    """Representation of Nimly Touch Pro door state sensor."""

    _attr_device_class = BinarySensorDeviceClass.DOOR
    
    def __init__(self, zha_device, endpoint, cluster):
        """Initialize the sensor."""
        self._zha_device = zha_device
        self._endpoint = endpoint
        self._cluster = cluster
        
        self._attr_name = f"{zha_device.name} {NAME_DOOR_STATE}"
        self._attr_unique_id = f"{zha_device.ieee}_{endpoint.endpoint_id}_door_state"
        self._is_on = None  # True for open, False for closed
        self._available = True
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._zha_device.available and self._available
        
    @property
    def is_on(self) -> bool:
        """Return true if the door is open."""
        return self._is_on
        
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Register to listen for attribute changes
        self.async_on_remove(
            self._endpoint.add_listener(self)
        )
        
        # Initial data fetch
        await self._update_door_state()
        
        # Set up regular polling
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_update, SCAN_INTERVAL
            )
        )
        
    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_door_state()
        
    async def _update_door_state(self):
        """Update door state information."""
        try:
            # Read the door state attribute
            result = await self._cluster.read_attributes([ATTR_DOOR_STATE])
            if ATTR_DOOR_STATE in result[0]:
                door_state = result[0][ATTR_DOOR_STATE]
                # Door is "on" (in binary sensor terms) when open
                self._is_on = door_state == DOOR_STATE_OPEN
                self._available = True
                
        except ZigbeeException as ex:
            _LOGGER.debug("Error reading door state: %s", ex)
            self._available = False
            
        self.async_write_ha_state()
        
    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        if attrid == int(ATTR_DOOR_STATE, 16):
            self._is_on = value == DOOR_STATE_OPEN
            self.async_write_ha_state()
