"""Sensor platform for Nimly Touch Pro integration."""
import logging
from datetime import timedelta
from typing import Any, Dict

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DOORLOCK_CLUSTER_ID,
    OTA_CLUSTER_ID,
    ATTR_CURRENT_FILE_VERSION,
    NAME_FIRMWARE,
    NAME_LAST_USER,
)
from .helpers import get_zha_device

_LOGGER = logging.getLogger(__name__)

# Polling interval for sensors
SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nimly Touch Pro sensors from a config entry."""
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

    entities = []

    # Add firmware version sensor (from OTA cluster)
    for endpoint_id, endpoint in zigpy_device.endpoints.items():
        if endpoint_id != 0:
            if hasattr(endpoint, "out_clusters"):
                clusters = endpoint.out_clusters
                for cluster in clusters.values():
                    if cluster.cluster_id == OTA_CLUSTER_ID:
                        entities.append(
                            NimlyProFirmwareSensor(zha_device_wrapper, zigpy_device, endpoint, cluster)
                        )
                        break

    # Add last user sensor (attached to the door lock cluster)
    for endpoint_id, endpoint in zigpy_device.endpoints.items():
        if endpoint_id != 0:
            if hasattr(endpoint, "in_clusters"):
                clusters = endpoint.in_clusters
                for cluster in clusters.values():
                    if cluster.cluster_id == DOORLOCK_CLUSTER_ID:
                        entities.append(
                            NimlyProLastUserSensor(zha_device_wrapper, zigpy_device, endpoint, cluster)
                        )
                        break

    if entities:
        async_add_entities(entities)


class NimlyProFirmwareSensor(SensorEntity):
    """Representation of Nimly Touch Pro firmware version sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

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
        
        self._attr_name = f"{device_name} {NAME_FIRMWARE}"
        self._attr_unique_id = f"{zigpy_device.ieee}_{endpoint.endpoint_id}_firmware"
        self._attr_native_value = "Unknown"
        self._available = True

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return getattr(self._zha_device, "available", True) and self._available

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await self._update_firmware_version()

        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_update, SCAN_INTERVAL)
        )

    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_firmware_version()

    async def _update_firmware_version(self):
        """Update firmware version information."""
        try:
            result = await self._cluster.read_attributes([ATTR_CURRENT_FILE_VERSION])
            if result and result[0] and ATTR_CURRENT_FILE_VERSION in result[0]:
                version = result[0][ATTR_CURRENT_FILE_VERSION]
                if isinstance(version, int):
                    major = (version >> 24) & 0xFF
                    minor = (version >> 16) & 0xFF
                    patch = (version >> 8) & 0xFF
                    build = version & 0xFF
                    self._attr_native_value = f"{major}.{minor}.{patch}.{build}"
                else:
                    self._attr_native_value = str(version)
                self._available = True

        except Exception as ex:
            _LOGGER.debug("Error reading firmware version: %s", ex)
            self._available = False

        self.async_write_ha_state()


class NimlyProLastUserSensor(SensorEntity):
    """Representation of Nimly Touch Pro last user sensor."""

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
        
        self._attr_name = f"{device_name} {NAME_LAST_USER}"
        self._attr_unique_id = f"{zigpy_device.ieee}_{endpoint.endpoint_id}_last_user"
        self._attr_native_value = "Unknown"
        self._available = True
        self._last_event_time = None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return getattr(self._zha_device, "available", True) and self._available

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        attributes = {}

        if self._last_event_time:
            attributes["last_event_time"] = self._last_event_time

        return attributes

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_update, SCAN_INTERVAL)
        )

    async def _async_update(self, now=None):
        """Periodic update."""
        pass

    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        _LOGGER.debug("Attribute updated in last user sensor: %s = %s", attrid, value)
