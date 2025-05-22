"""Lock platform for Nimly Touch Pro integration."""
import logging
from typing import Any, Callable, Dict, List, Optional

from zigpy.exceptions import ZigbeeException
import zigpy.zcl.clusters.closures as closures

from homeassistant.components.lock import LockEntity
from homeassistant.components.zha.core.const import DOMAIN as ZHA_DOMAIN
from homeassistant.components.zha.core.helpers import get_zha_gateway
from homeassistant.components.zha.core.device import ZHADevice
from homeassistant.const import STATE_LOCKED, STATE_UNLOCKED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    DOORLOCK_CLUSTER_ID,
    ATTR_LOCK_STATE,
    ATTR_KEYPAD_OPERATION_EVENT_MASK,
    ATTR_MANUAL_OPERATION_EVENT_MASK,
    ATTR_RF_OPERATION_EVENT_MASK,
    EVENT_TYPE_KEYPAD_UNLOCK,
    EVENT_TYPE_MANUAL_UNLOCK,
    EVENT_TYPE_RF_UNLOCK,
    EVENT_TYPE_AUTO_LOCK,
)

_LOGGER = logging.getLogger(__name__)

# Polling interval for the lock state
SCAN_INTERVAL = dt_util.timedelta(seconds=30)

async def async_setup_entry(
    hass: HomeAssistant, 
    config_entry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Nimly Touch Pro lock from a config entry."""
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
    for endpoint_id, endpoint in zha_device.endpoints.items():
        if endpoint_id != 0:  # Skip ZDO endpoint
            clusters = endpoint.in_clusters
            if any(cluster.cluster_id == DOORLOCK_CLUSTER_ID for cluster in clusters.values()):
                doorlock_endpoint = endpoint
                break
                
    if not doorlock_endpoint:
        _LOGGER.error("Door lock cluster not found on device %s", ieee)
        return
        
    # Create and add our enhanced lock entity
    async_add_entities([NimlyProLock(zha_device, doorlock_endpoint)])

class NimlyProLock(LockEntity):
    """Representation of a Nimly Touch Pro lock."""

    def __init__(self, zha_device, endpoint):
        """Initialize the lock."""
        self._zha_device = zha_device
        self._endpoint = endpoint
        self._doorlock_cluster = None
        
        # Find the door lock cluster
        for cluster in endpoint.in_clusters.values():
            if cluster.cluster_id == DOORLOCK_CLUSTER_ID:
                self._doorlock_cluster = cluster
                break
                
        self._attr_name = f"{zha_device.name}"
        self._attr_unique_id = f"{zha_device.ieee}_{endpoint.endpoint_id}_lock"
        self._state = None
        self._available = True
        self._last_event = None
        self._last_event_type = None
        self._last_event_user = None
        self._last_event_time = None
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._zha_device.available and self._available
        
    @property
    def is_locked(self) -> bool:
        """Return true if the lock is locked."""
        return self._state == STATE_LOCKED
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        attributes = {}
        
        if self._last_event_type:
            attributes["last_event_type"] = self._last_event_type
            
        if self._last_event_user:
            attributes["last_event_user"] = self._last_event_user
            
        if self._last_event_time:
            attributes["last_event_time"] = self._last_event_time
            
        return attributes
        
    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock."""
        try:
            result = await self._doorlock_cluster.lock_door()
            _LOGGER.debug("Lock command result: %s", result)
            self._state = STATE_LOCKED
            self.async_write_ha_state()
        except ZigbeeException as ex:
            _LOGGER.error("Error locking door: %s", ex)
        
    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock."""
        try:
            result = await self._doorlock_cluster.unlock_door()
            _LOGGER.debug("Unlock command result: %s", result)
            self._state = STATE_UNLOCKED
            # Record this as an RF event
            self._last_event_type = EVENT_TYPE_RF_UNLOCK
            self._last_event_user = "Home Assistant"
            self._last_event_time = dt_util.now().isoformat()
            self.async_write_ha_state()
        except ZigbeeException as ex:
            _LOGGER.error("Error unlocking door: %s", ex)
        
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Register to listen for attribute changes
        self.async_on_remove(
            self._endpoint.add_listener(self)
        )
        
        # Initial data fetch
        await self._update_lock_state()
        
        # Set up regular polling
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_update, SCAN_INTERVAL
            )
        )
        
    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_lock_state()
        
    async def _update_lock_state(self):
        """Update lock state and event information."""
        try:
            result = await self._doorlock_cluster.read_attributes([ATTR_LOCK_STATE])
            if ATTR_LOCK_STATE in result[0]:
                lock_state = result[0][ATTR_LOCK_STATE]
                self._state = STATE_LOCKED if lock_state == 1 else STATE_UNLOCKED
                self._available = True
                
            # Try to read event attributes if they're available
            await self._update_event_data()
                
        except ZigbeeException as ex:
            _LOGGER.debug("Error reading lock state: %s", ex)
            self._available = False
            
        self.async_write_ha_state()
        
    async def _update_event_data(self):
        """Update event data from the lock."""
        try:
            # This is a placeholder - in a real implementation we would
            # read the event log from the lock if available
            # For now, we're just checking the event masks to see if they exist
            await self._doorlock_cluster.read_attributes([
                ATTR_KEYPAD_OPERATION_EVENT_MASK,
                ATTR_MANUAL_OPERATION_EVENT_MASK,
                ATTR_RF_OPERATION_EVENT_MASK
            ])
            
        except ZigbeeException as ex:
            _LOGGER.debug("Error reading event data: %s", ex)
        
    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        _LOGGER.debug("Attribute updated: %s = %s", attrid, value)
        
        if attrid == int(ATTR_LOCK_STATE, 16):
            self._state = STATE_LOCKED if value == 1 else STATE_UNLOCKED
            # If it locked automatically, record that
            if value == 1 and self._last_event_type != EVENT_TYPE_AUTO_LOCK:
                self._last_event_type = EVENT_TYPE_AUTO_LOCK
                self._last_event_time = dt_util.now().isoformat()
            self.async_write_ha_state()
