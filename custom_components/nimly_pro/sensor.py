"""Sensor platform for Nimly Touch Pro integration."""
import logging
from typing import Any, Callable, Dict, List, Optional

from zigpy.exceptions import ZigbeeException

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.zha.core.helpers import get_zha_gateway
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    DOORLOCK_CLUSTER_ID,
    POWER_CLUSTER_ID,
    OTA_CLUSTER_ID,
    ATTR_BATTERY_PERCENTAGE,
    ATTR_CURRENT_FILE_VERSION,
    NAME_FIRMWARE,
    NAME_LAST_USER,
)

_LOGGER = logging.getLogger(__name__)

# Polling interval for sensors
SCAN_INTERVAL = dt_util.timedelta(seconds=60)

async def async_setup_entry(
    hass: HomeAssistant, 
    config_entry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Nimly Touch Pro sensors from a config entry."""
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
    
    # Set up entities list
    entities = []
    
    # Add firmware version sensor (from OTA cluster)
    ota_endpoint = None
    for endpoint_id, endpoint in zha_device.endpoints.items():
        if endpoint_id != 0:  # Skip ZDO endpoint
            clusters = endpoint.out_clusters
            if any(cluster.cluster_id == OTA_CLUSTER_ID for cluster in clusters.values()):
                ota_endpoint = endpoint
                ota_cluster = next(
                    cluster for cluster in clusters.values() 
                    if cluster.cluster_id == OTA_CLUSTER_ID
                )
                entities.append(
                    NimlyProFirmwareSensor(zha_device, endpoint, ota_cluster)
                )
                break
    
    # Add last user sensor (attached to the door lock cluster)
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
                entities.append(
                    NimlyProLastUserSensor(zha_device, endpoint, doorlock_cluster)
                )
                break
    
    # Add battery percentage sensor
    power_endpoint = None
    for endpoint_id, endpoint in zha_device.endpoints.items():
        if endpoint_id != 0:  # Skip ZDO endpoint
            clusters = endpoint.in_clusters
            if any(cluster.cluster_id == POWER_CLUSTER_ID for cluster in clusters.values()):
                power_endpoint = endpoint
                power_cluster = next(
                    cluster for cluster in clusters.values() 
                    if cluster.cluster_id == POWER_CLUSTER_ID
                )
                # We use a standard battery entity - not custom
                # This will complement and provide more context for the built-in battery entity
                break
    
    if entities:
        async_add_entities(entities)

class NimlyProFirmwareSensor(SensorEntity):
    """Representation of Nimly Touch Pro firmware version sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    
    def __init__(self, zha_device, endpoint, cluster):
        """Initialize the sensor."""
        self._zha_device = zha_device
        self._endpoint = endpoint
        self._cluster = cluster
        
        self._attr_name = f"{zha_device.name} {NAME_FIRMWARE}"
        self._attr_unique_id = f"{zha_device.ieee}_{endpoint.endpoint_id}_firmware"
        self._attr_native_value = "Unknown"
        self._available = True
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._zha_device.available and self._available
        
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Initial data fetch
        await self._update_firmware_version()
        
        # Set up regular polling
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_update, SCAN_INTERVAL
            )
        )
        
    async def _async_update(self, now=None):
        """Periodic update."""
        await self._update_firmware_version()
        
    async def _update_firmware_version(self):
        """Update firmware version information."""
        try:
            # Read the current firmware version
            result = await self._cluster.read_attributes([ATTR_CURRENT_FILE_VERSION])
            if ATTR_CURRENT_FILE_VERSION in result[0]:
                version = result[0][ATTR_CURRENT_FILE_VERSION]
                # Format version number for display (e.g., convert 0x01020304 to 1.2.3.4)
                if isinstance(version, int):
                    major = (version >> 24) & 0xFF
                    minor = (version >> 16) & 0xFF
                    patch = (version >> 8) & 0xFF
                    build = version & 0xFF
                    self._attr_native_value = f"{major}.{minor}.{patch}.{build}"
                else:
                    self._attr_native_value = str(version)
                self._available = True
                
        except ZigbeeException as ex:
            _LOGGER.debug("Error reading firmware version: %s", ex)
            self._available = False
            
        self.async_write_ha_state()

class NimlyProLastUserSensor(SensorEntity):
    """Representation of Nimly Touch Pro last user sensor."""

    def __init__(self, zha_device, endpoint, cluster):
        """Initialize the sensor."""
        self._zha_device = zha_device
        self._endpoint = endpoint
        self._cluster = cluster
        
        self._attr_name = f"{zha_device.name} {NAME_LAST_USER}"
        self._attr_unique_id = f"{zha_device.ieee}_{endpoint.endpoint_id}_last_user"
        self._attr_native_value = "Unknown"
        self._available = True
        self._last_event_time = None
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._zha_device.available and self._available
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        attributes = {}
        
        if self._last_event_time:
            attributes["last_event_time"] = self._last_event_time
            
        return attributes
        
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Register to listen for lock state changes in lock entity
        # This will allow us to update the last user when lock state changes
        
        # Also listen for ZHA events
        self.async_on_remove(
            self._endpoint.add_listener(self)
        )
        
        # Set up regular polling - though most updates will come from events
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_update, SCAN_INTERVAL
            )
        )
        
    async def _async_update(self, now=None):
        """Periodic update - attempt to read event log if possible."""
        # In a full implementation, we would try to read the event log
        # from the lock to get the most recent events
        pass
    
    def attribute_updated(self, attrid, value):
        """Handle attribute updates."""
        # This is called when attributes are updated from ZHA
        # We can use this to detect when the lock state changes
        # and potentially who triggered it
        _LOGGER.debug("Attribute updated in last user sensor: %s = %s", attrid, value)
        
        # In a complete implementation, we would parse event logs
        # or operation events to determine the user
