"""Binary sensor platform for Nimly Touch Pro integration."""
import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DOORLOCK_CLUSTER_ID,
    ATTR_DOOR_STATE,
    NAME_DOOR_STATE,
)
from .helpers import get_zha_device

_LOGGER = logging.getLogger(__name__)

# Polling interval
SCAN_INTERVAL = timedelta(seconds=30)

# Door state values based on ZCL spec
DOOR_STATE_OPEN = 0
DOOR_STATE_CLOSED = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nimly Touch Pro binary sensors from a config entry."""
    ieee = config_entry.data["ieee"]

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
    doorlock_cluster = None
    for endpoint_id, endpoint in zigpy_device.endpoints.items():
        if endpoint_id != 0:
            if hasattr(endpoint, "in_clusters"):
                clusters = endpoint.in_clusters
                for cluster in clusters.values():
                    if cluster.cluster_id == DOORLOCK_CLUSTER_ID:
                        doorlock_endpoint = endpoint
                        doorlock_cluster = cluster
                        break
                if doorlock_cluster:
                    break

    if doorlock_endpoint and doorlock_cluster:
        async_add_entities(
            [NimlyProDoorStateSensor(zha_device_wrapper, zigpy_device, doorlock_endpoint, doorlock_cluster)]
        )


class NimlyProDoorStateSensor(BinarySensorEntity):
    """Representation of Nimly Touch Pro door state sensor."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, zha_device, zigpy_device, endpoint, cluster):
        """Initialize the sensor."""
        self._zha_device = zha_device
        self._zigpy_device = zigpy_device
        self._endpoint = endpoint
        self._cluster = cluster

        # Use ZHA device name if available
        device_name = getattr(zha_device, 'name', None)
        if not device_name or device_name.startswith('0x'):
            device_name = getattr(zha_device, 'model', None) or getattr(zigpy_device, 'model', 'Nimly Lock')
        
        self._attr_name = f"{device_name} {NAME_DOOR_STATE}"
        self._attr_unique_id = f"{zigpy_device.ieee}_{endpoint.endpoint_id}_door_state"
        self._is_on = None
        self._available = True

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return getattr(self._zha_device, "available", True) and self._available

    @property
    def is_on(self) -> bool | None:
        """Return true if the door is open."""
        return self._is_on

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await self._update_door_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_update, SCAN_INTERVAL)
        )

    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_door_state()

    async def _update_door_state(self):
        """Update door state information."""
        try:
            result = await self._cluster.read_attributes([ATTR_DOOR_STATE])
            if result and result[0] and ATTR_DOOR_STATE in result[0]:
                door_state = result[0][ATTR_DOOR_STATE]
                self._is_on = door_state == DOOR_STATE_OPEN
                self._available = True

        except Exception as ex:
            _LOGGER.debug("Error reading door state: %s", ex)
            self._available = False

        self.async_write_ha_state()

    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        door_state_attrid = (
            int(ATTR_DOOR_STATE, 16)
            if isinstance(ATTR_DOOR_STATE, str)
            else ATTR_DOOR_STATE
        )
        if attrid == door_state_attrid:
            self._is_on = value == DOOR_STATE_OPEN
            self.async_write_ha_state()
