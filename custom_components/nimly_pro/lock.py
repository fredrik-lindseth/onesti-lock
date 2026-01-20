"""Lock platform for Nimly Touch Pro integration."""
import logging
from datetime import timedelta
from typing import Any, Dict

from homeassistant.components.lock import LockEntity, LockState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    DOORLOCK_CLUSTER_ID,
    ATTR_LOCK_STATE,
    EVENT_TYPE_RF_UNLOCK,
    EVENT_TYPE_AUTO_LOCK,
)
from .helpers import get_zha_device

_LOGGER = logging.getLogger(__name__)

# Polling interval for the lock state
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nimly Touch Pro lock from a config entry."""
    ieee = config_entry.data["ieee"]
    _LOGGER.debug("Setting up Nimly Pro lock for IEEE: %s", ieee)

    # Find the ZHA device
    zha_device = get_zha_device(hass, ieee)
    if not zha_device:
        _LOGGER.error("ZHA device not found for %s", ieee)
        return

    # Store the ZHA device wrapper for name/availability info
    zha_device_wrapper = zha_device
    
    # Get the underlying zigpy device for cluster access
    zigpy_device = zha_device
    if hasattr(zha_device, "device"):
        zigpy_device = zha_device.device

    if not hasattr(zigpy_device, 'endpoints'):
        _LOGGER.error("Device has no endpoints: %s", type(zigpy_device))
        return

    # Find the endpoint with the door lock cluster
    doorlock_endpoint = None
    for endpoint_id, endpoint in zigpy_device.endpoints.items():
        if endpoint_id != 0:  # Skip ZDO endpoint
            if hasattr(endpoint, "in_clusters"):
                clusters = endpoint.in_clusters
                for cluster in clusters.values():
                    if cluster.cluster_id == DOORLOCK_CLUSTER_ID:
                        doorlock_endpoint = endpoint
                        _LOGGER.debug("Found door lock cluster in endpoint %s", endpoint_id)
                        break
                if doorlock_endpoint:
                    break

    if not doorlock_endpoint:
        _LOGGER.error("Door lock cluster not found on device %s", ieee)
        return

    # Create and add our enhanced lock entity
    async_add_entities([NimlyProLock(zha_device_wrapper, zigpy_device, doorlock_endpoint)])


class NimlyProLock(LockEntity):
    """Representation of a Nimly Touch Pro lock."""

    def __init__(self, zha_device, zigpy_device, endpoint):
        """Initialize the lock."""
        self._zha_device = zha_device  # ZHA device wrapper for name/availability
        self._zigpy_device = zigpy_device  # Zigpy device for clusters
        self._endpoint = endpoint
        self._doorlock_cluster = None

        # Find the door lock cluster
        for cluster in endpoint.in_clusters.values():
            if cluster.cluster_id == DOORLOCK_CLUSTER_ID:
                self._doorlock_cluster = cluster
                break

        # Use ZHA device name if available, otherwise use model/manufacturer
        device_name = getattr(zha_device, 'name', None)
        if not device_name or device_name.startswith('0x'):
            # Try model name
            device_name = getattr(zha_device, 'model', None) or getattr(zigpy_device, 'model', 'Nimly Lock')
        
        self._attr_name = device_name
        self._attr_unique_id = f"{zigpy_device.ieee}_{endpoint.endpoint_id}_lock"
        self._state = None
        self._available = True
        self._last_event_type = None
        self._last_event_user = None
        self._last_event_time = None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return getattr(self._zha_device, "available", True) and self._available

    @property
    def is_locked(self) -> bool:
        """Return true if the lock is locked."""
        return self._state == LockState.LOCKED

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
            self._state = LockState.LOCKED
            self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.error("Error locking door: %s", ex)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock."""
        try:
            result = await self._doorlock_cluster.unlock_door()
            _LOGGER.debug("Unlock command result: %s", result)
            self._state = LockState.UNLOCKED
            # Record this as an RF event
            self._last_event_type = EVENT_TYPE_RF_UNLOCK
            self._last_event_user = "Home Assistant"
            self._last_event_time = dt_util.now().isoformat()
            self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.error("Error unlocking door: %s", ex)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Initial data fetch
        await self._update_lock_state()

        # Set up regular polling
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_update, SCAN_INTERVAL)
        )

    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_lock_state()

    async def _update_lock_state(self):
        """Update lock state."""
        try:
            result = await self._doorlock_cluster.read_attributes([ATTR_LOCK_STATE])
            if result and result[0] and ATTR_LOCK_STATE in result[0]:
                lock_state = result[0][ATTR_LOCK_STATE]
                self._state = LockState.LOCKED if lock_state == 1 else LockState.UNLOCKED
                self._available = True

        except Exception as ex:
            _LOGGER.debug("Error reading lock state: %s", ex)
            self._available = False

        self.async_write_ha_state()

    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        _LOGGER.debug("Attribute updated: %s = %s", attrid, value)

        lock_state_attrid = int(ATTR_LOCK_STATE, 16) if isinstance(ATTR_LOCK_STATE, str) else ATTR_LOCK_STATE
        if attrid == lock_state_attrid:
            self._state = LockState.LOCKED if value == 1 else LockState.UNLOCKED
            if value == 1 and self._last_event_type != EVENT_TYPE_AUTO_LOCK:
                self._last_event_type = EVENT_TYPE_AUTO_LOCK
                self._last_event_time = dt_util.now().isoformat()
            self.async_write_ha_state()
