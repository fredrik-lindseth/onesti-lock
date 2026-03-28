"""Onesti Lock — PIN management and activity tracking for Nimly locks."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    ACTION_LOCK,
    ACTION_UNLOCK,
    ACTION_UNKNOWN,
    CONF_IEEE,
    DOMAIN,
    SOURCE_AUTO,
    SOURCE_KEYPAD,
    SOURCE_MANUAL,
    SOURCE_RF,
    SOURCE_UNKNOWN,
)
from .coordinator import NimlyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

# Nimly operation event: attrid 0x0100 on DoorLock cluster
# Encoded as bitmap32 (little-endian):
#   byte 0: user_slot (0 = system/no user, 3+ = user slot)
#   byte 1: reserved (always 0)
#   byte 2: action (1 = lock, 2 = unlock)
#   byte 3: source (2 = keypad, 10 = auto/system)
ATTR_OPERATION_EVENT = 0x0100

# Source byte values
_SOURCE_MAP = {
    0x01: SOURCE_RF,
    0x02: SOURCE_KEYPAD,
    0x03: SOURCE_MANUAL,
    0x0A: SOURCE_AUTO,
}

# Action byte values
_ACTION_MAP = {
    0x01: ACTION_LOCK,
    0x02: ACTION_UNLOCK,
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Onesti Lock from a config entry."""
    coordinator = NimlyCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    # Register services
    from .services import async_setup_services
    await async_setup_services(hass)

    # Set up sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for attribute reports from the lock's DoorLock cluster
    _setup_attribute_listener(hass, entry, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unsub = hass.data[DOMAIN][entry.entry_id].get("unsub_attribute")
    if unsub:
        unsub()

    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hass.data[DOMAIN].pop(entry.entry_id, None)

    if not hass.data[DOMAIN]:
        from .services import async_unload_services
        await async_unload_services(hass)

    return True


def _setup_attribute_listener(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: NimlyCoordinator
) -> None:
    """Listen for attribute reports on the DoorLock cluster.

    Nimly sends attrid 0x0100 as a bitmap32 containing:
    user_slot, reserved, action, source — decoded from little-endian bytes.
    """
    cluster = coordinator._get_cluster()
    if not cluster:
        _LOGGER.warning("Could not set up attribute listener — cluster not found")
        return

    @callback
    def _on_attribute_report(event) -> None:
        """Handle attribute report from zigpy."""
        if event.attribute_id != ATTR_OPERATION_EVENT:
            return

        raw = event.raw_value
        if not hasattr(raw, 'value'):
            val = int(raw)
        else:
            val = int(raw.value) if hasattr(raw.value, '__int__') else int(raw)

        # Decode little-endian bytes
        try:
            b = val.to_bytes(4, "little")
        except (OverflowError, ValueError):
            _LOGGER.warning("Could not decode operation event: %s", val)
            return

        user_slot = b[0]
        action_byte = b[2]
        source_byte = b[3]

        action = _ACTION_MAP.get(action_byte, ACTION_UNKNOWN)
        source = _SOURCE_MAP.get(source_byte, SOURCE_UNKNOWN)

        # user_slot 0 = system/auto (no specific user)
        user_slot_or_none = user_slot if user_slot > 0 else None

        _LOGGER.info(
            "Nimly event: %s by %s via %s (raw: %s)",
            action,
            coordinator.get_slot_name(user_slot) if user_slot > 0 else "system",
            source,
            f"0x{val:08x}",
        )

        coordinator.update_activity(user_slot_or_none, action, source)

        hass.bus.async_fire(
            "nimly_pro_lock_activity",
            {
                "ieee": coordinator.ieee,
                "user_slot": user_slot_or_none,
                "user_name": coordinator.get_slot_name(user_slot)
                if user_slot > 0
                else None,
                "action": action,
                "source": source,
            },
        )

    # Subscribe to attribute reports on the cluster
    cluster.add_listener(_AttributeListener(cluster, _on_attribute_report))
    _LOGGER.info("Nimly attribute listener active on cluster %s", cluster)


class _AttributeListener:
    """Zigpy cluster listener that forwards attribute reports."""

    def __init__(self, cluster, callback_fn) -> None:
        self._cluster = cluster
        self._callback = callback_fn

    def attribute_updated(self, attrid, value, timestamp=None) -> None:
        """Called by zigpy when an attribute report is received."""
        if attrid == ATTR_OPERATION_EVENT:
            # Create a minimal event-like object
            class _Event:
                pass
            event = _Event()
            event.attribute_id = attrid
            event.raw_value = value
            self._callback(event)

    def cluster_command(self, tsn, command_id, args) -> None:
        """Called by zigpy for cluster commands — not used."""
        pass
