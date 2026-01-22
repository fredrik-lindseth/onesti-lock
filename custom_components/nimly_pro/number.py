"""Number platform for Nimly Touch Pro integration."""
import logging
from datetime import timedelta

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOORLOCK_CLUSTER_ID,
    ATTR_AUTO_RELOCK_TIME,
    NAME_AUTO_RELOCK,
    DEFAULT_AUTO_RELOCK_TIME,
)
from .helpers import get_zha_device

_LOGGER = logging.getLogger(__name__)

# Polling interval
SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nimly Touch Pro number entities from a config entry."""
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
            [NimlyProAutoRelockTime(zha_device_wrapper, zigpy_device, doorlock_endpoint, doorlock_cluster)]
        )


class NimlyProAutoRelockTime(NumberEntity):
    """Representation of Nimly Touch Pro Auto Relock Time setting."""

    def __init__(self, zha_device, zigpy_device, endpoint, cluster):
        """Initialize the number entity."""
        self._zha_device = zha_device
        self._zigpy_device = zigpy_device
        self._endpoint = endpoint
        self._cluster = cluster

        # Use ZHA device name if available
        device_name = getattr(zha_device, 'name', None)
        if not device_name or device_name.startswith('0x'):
            device_name = getattr(zha_device, 'model', None) or getattr(zigpy_device, 'model', 'Nimly Lock')
        
        self._attr_name = f"{device_name} {NAME_AUTO_RELOCK}"
        self._attr_unique_id = f"{zigpy_device.ieee}_{endpoint.endpoint_id}_auto_relock"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 3600
        self._attr_native_step = 1
        self._attr_native_value = DEFAULT_AUTO_RELOCK_TIME
        self._attr_mode = "slider"
        self._attr_native_unit_of_measurement = "s"
        self._available = True

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return getattr(self._zha_device, "available", True) and self._available

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        try:
            attr_id = (
                int(ATTR_AUTO_RELOCK_TIME, 16)
                if isinstance(ATTR_AUTO_RELOCK_TIME, str)
                else ATTR_AUTO_RELOCK_TIME
            )
            await self._cluster.write_attributes({attr_id: int(value)})
            self._attr_native_value = value
            self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.error("Error setting auto relock time: %s", ex)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await self._update_auto_relock_time()

        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_update, SCAN_INTERVAL)
        )

    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_auto_relock_time()

    async def _update_auto_relock_time(self):
        """Update auto-relock time value."""
        try:
            result = await self._cluster.read_attributes([ATTR_AUTO_RELOCK_TIME])
            if result and result[0] and ATTR_AUTO_RELOCK_TIME in result[0]:
                value = result[0][ATTR_AUTO_RELOCK_TIME]
                if value is not None:
                    self._attr_native_value = value
                self._available = True

        except Exception as ex:
            _LOGGER.debug("Error reading auto-relock time: %s", ex)
            self._available = False

        self.async_write_ha_state()

    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        attr_id = (
            int(ATTR_AUTO_RELOCK_TIME, 16)
            if isinstance(ATTR_AUTO_RELOCK_TIME, str)
            else ATTR_AUTO_RELOCK_TIME
        )
        if attrid == attr_id:
            if value is not None:
                self._attr_native_value = value
                self.async_write_ha_state()
