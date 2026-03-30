"""Onesti Lock — PIN management and activity tracking for Onesti/Nimly locks."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    ACTION_LOCK,
    ACTION_UNLOCK,
    ACTION_UNKNOWN,
    CONF_IEEE,
    DOMAIN,
    DOORLOCK_CLUSTER_ID,
    SOURCE_AUTO,
    SOURCE_FINGERPRINT,
    SOURCE_KEYPAD,
    SOURCE_RFID,
    SOURCE_ZIGBEE,
    SOURCE_UNKNOWN,
)
from .coordinator import NimlyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

# Onesti operation event: attrid 0x0100 on DoorLock cluster (0x0101)
# bitmap32 little-endian: [user_slot, reserved, action, source]
ATTR_OPERATION_EVENT = 0x0100

_SOURCE_MAP = {
    0x00: SOURCE_ZIGBEE,
    0x02: SOURCE_KEYPAD,
    0x03: SOURCE_FINGERPRINT,
    0x04: SOURCE_RFID,
    0x0A: SOURCE_AUTO,
}

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

    from .services import async_setup_services
    await async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register event listener on the DoorLock cluster
    _register_event_listener(hass, entry, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unsub = hass.data[DOMAIN][entry.entry_id].get("unsub_listener")
    if unsub:
        unsub()

    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id, None)

    if not hass.data[DOMAIN]:
        from .services import async_unload_services
        await async_unload_services(hass)

    return True


def _decode_operation_event(coordinator, val: int) -> dict | None:
    """Decode attrid 0x0100 bitmap32 into action/source/user."""
    try:
        b = val.to_bytes(4, "little")
    except (OverflowError, ValueError):
        return None

    user_slot = b[0]
    action = _ACTION_MAP.get(b[2], ACTION_UNKNOWN)
    source = _SOURCE_MAP.get(b[3], SOURCE_UNKNOWN)
    user_slot_or_none = user_slot if user_slot > 0 else None

    return {
        "user_slot": user_slot_or_none,
        "user_name": coordinator.get_slot_name(user_slot) if user_slot > 0 else None,
        "action": action,
        "source": source,
    }


def _register_event_listener(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: NimlyCoordinator
) -> None:
    """Listen for attribute_report events on the DoorLock cluster.

    zigpy emits "attribute_report" via cluster.emit() for every Report_Attributes
    ZCL frame, even for unknown attributes and even when value is unchanged.
    This is the only reliable way to catch Onesti's custom attrid 0x0100.

    The alternatives don't work:
    - add_listener + attribute_updated: suppressed for unknown attributes
    - add_listener + general_command: not dispatched to listeners
    - add_listener + handle_cluster_request: only for cluster commands, not general
    """
    cluster = coordinator._get_cluster()
    if not cluster:
        _LOGGER.error("Could not find DoorLock cluster for event listener")
        return

    def _on_attribute_report(event) -> None:
        if event.attribute_id != ATTR_OPERATION_EVENT:
            return

        raw = event.raw_value
        try:
            val = int(raw)
        except (TypeError, ValueError):
            try:
                val = int(raw.value)
            except (TypeError, ValueError, AttributeError):
                _LOGGER.warning("Could not parse operation event: %s", raw)
                return

        decoded = _decode_operation_event(coordinator, val)
        if not decoded:
            return

        _LOGGER.info(
            "Lock event: %s by %s via %s (raw: 0x%08x)",
            decoded["action"],
            decoded["user_name"] or "system",
            decoded["source"],
            val,
        )

        # Only update the activity sensor for user-initiated events,
        # not auto-lock — otherwise auto-lock immediately overwrites
        # "Vibecke låste opp med kode" with "Auto-lås"
        if decoded["source"] != "auto":
            coordinator.update_activity(
                decoded["user_slot"], decoded["action"], decoded["source"]
            )

        hass.bus.async_fire(
            "onesti_lock_activity",
            {"ieee": coordinator.ieee, **decoded},
        )

    unsub = cluster.on_event("attribute_report", _on_attribute_report)
    hass.data[DOMAIN][entry.entry_id]["unsub_listener"] = unsub

    _LOGGER.debug(
        "Event listener registered on %s (events: %s)",
        type(cluster).__name__,
        list(cluster._event_listeners.keys()),
    )
