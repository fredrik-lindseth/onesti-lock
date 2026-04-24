"""Onesti Lock — PIN management and activity tracking for Onesti/Nimly locks."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    ACTION_LOCK,
    ACTION_UNKNOWN,
    ACTION_UNLOCK,
    CONF_IEEE,
    DOMAIN,
    DOORLOCK_CLUSTER_ID,
    SOURCE_AUTO,
    SOURCE_FINGERPRINT,
    SOURCE_KEYPAD,
    SOURCE_RFID,
    SOURCE_UNKNOWN,
    SOURCE_ZIGBEE,
)
from .coordinator import NimlyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

# Onesti operation event: attrid 0x0100 on DoorLock cluster (0x0101)
# bitmap32 little-endian: [user_slot, reserved, action, source]
ATTR_OPERATION_EVENT = 0x0100
# Onesti custom: last used PIN code as ASCII digits (attribute 0x0101)
ATTR_LAST_PIN_CODE = 0x0101

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

    # Read lock capabilities in the background — lock may be sleeping and
    # we don't want to block setup on a slow/missing response
    hass.async_create_task(coordinator.read_lock_capabilities())

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


def _decode_pin_code(raw) -> str | None:
    """Decode attrid 0x0101 as PIN digits.

    Onesti sends the last-used PIN as bytes in one of two formats depending
    on firmware:
      - BCD (packed nibbles): b"\\x54\\x78" → "5478"  (NimlyPRO captures)
      - ASCII: b"\\x35\\x34\\x37\\x38" → "5478"  (seen in Z2M PR #11332)

    We detect format heuristically: if every byte is a printable digit
    (0x30-0x39) the data is ASCII, otherwise treat as BCD. Empty/None
    returns None.
    """
    if raw is None:
        return None

    if isinstance(raw, str):
        text = raw.strip().strip("\x00").strip()
        return text or None

    try:
        if isinstance(raw, bytes | bytearray):
            data = bytes(raw)
        elif isinstance(raw, list):
            data = bytes(raw)
        else:
            text = str(raw).strip().strip("\x00").strip()
            return text or None
    except (TypeError, ValueError):
        return None

    # Strip trailing null-padding
    data = data.rstrip(b"\x00")
    if not data:
        return None

    # ASCII digits: every byte in 0x30-0x39
    if all(0x30 <= b <= 0x39 for b in data):
        return data.decode("ascii")

    # BCD packed: every nibble must be 0-9
    nibbles: list[str] = []
    for byte in data:
        high = (byte >> 4) & 0x0F
        low = byte & 0x0F
        if high > 9 or low > 9:
            return None  # Not valid BCD either
        nibbles.append(f"{high}{low}")
    return "".join(nibbles) or None


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
        if event.attribute_id == ATTR_LAST_PIN_CODE:
            coordinator.update_last_pin_code(_decode_pin_code(event.raw_value))
            return

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
