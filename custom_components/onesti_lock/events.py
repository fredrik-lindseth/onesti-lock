"""Decoding and listening for the Onesti operation event.

No Home Assistant imports at module level, so the pytest-only CI can
execute the decoder and the suppression rule directly. The hass object
the listener needs is passed in by the caller.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .const import (
    ACTION_LOCK,
    ACTION_UNKNOWN,
    ACTION_UNLOCK,
    SOURCE_AUTO,
    SOURCE_FINGERPRINT,
    SOURCE_KEYPAD,
    SOURCE_RFID,
    SOURCE_UNATTRIBUTED,
    SOURCE_UNKNOWN,
    SOURCE_ZIGBEE,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import NimlyCoordinator

_LOGGER = logging.getLogger(__name__)

# Onesti operation event: attrid 0x0100 on DoorLock cluster (0x0101)
# bitmap32: bits 0-15 user_slot (uint16 LE), bits 16-23 action, bits 24-31 source
ATTR_OPERATION_EVENT = 0x0100
# Attribute 0x0101 carries the actual PIN digits in BCD plaintext, not an
# opaque id (zha-device-handlers#4881). We deliberately ignore it: exposing
# it would write real access codes into HA's recorder, logbook and
# diagnostics. The frame format is documented in
# docs/zigbee-protocol/zigbee-captures.md if it is ever needed again.

SOURCE_MAP = {
    0x00: SOURCE_ZIGBEE,
    0x02: SOURCE_KEYPAD,
    0x03: SOURCE_FINGERPRINT,
    0x04: SOURCE_RFID,
    # NimlyCodePRO (fw 4.8) reports 0x05 for Zigbee, auto-relock and interior
    # keypad alike; the payload cannot distinguish them. Other models use
    # 0x00/0x0A instead.
    0x05: SOURCE_UNATTRIBUTED,
    0x0A: SOURCE_AUTO,
}

# Sources where a person presented a credential, so slot 0 is the master user
# rather than "no user". The master code unlocks the door (capture 29.03:
# 0x02020000 = slot 0, unlock, keypad), and Z2M and the ZHA quirk both report
# it as slot 0. Code Pro users on slots 1-2 are already > 0 and unaffected.
CREDENTIAL_SOURCES = frozenset({SOURCE_KEYPAD, SOURCE_FINGERPRINT, SOURCE_RFID})

ACTION_MAP = {
    0x01: ACTION_LOCK,
    0x02: ACTION_UNLOCK,
}


def decode_operation_event(coordinator, val: int) -> dict | None:
    """Decode attrid 0x0100 bitmap32 into action/source/user."""
    if not 0 <= val <= 0xFFFFFFFF:
        return None

    # Slot spans bits 0-15: the manual allows slots up to 999, and the
    # upstream converter (zha-device-handlers#4881) reads value & 0xFFFF.
    # Reading byte 0 alone truncated slot 300 to 44.
    user_slot = val & 0xFFFF
    action = ACTION_MAP.get((val >> 16) & 0xFF, ACTION_UNKNOWN)
    source = SOURCE_MAP.get((val >> 24) & 0xFF, SOURCE_UNKNOWN)
    # Slot 0 only means "no user" for system and remote sources (auto-lock,
    # Zigbee, CodePRO relock); from a credential source it is the master user.
    no_user = user_slot == 0 and source not in CREDENTIAL_SOURCES
    user_slot_or_none = None if no_user else user_slot

    return {
        "user_slot": user_slot_or_none,
        "user_name": (
            coordinator.get_slot_name(user_slot_or_none)
            if user_slot_or_none is not None
            else None
        ),
        "action": action,
        "source": source,
    }


def is_system_lock(decoded: dict, wake_echo_pending: bool = False) -> bool:
    """Whether a decoded event is a lock no person can be credited with.

    Only user-attributable events update the activity sensor. Otherwise
    auto-relock immediately overwrites the last meaningful entry, such as
    who unlocked with a code. Most models report auto-relock as
    SOURCE_AUTO. NimlyCodePRO reports it as an unattributed lock with no
    user slot, indistinguishable from a remote lock, so both are
    suppressed on that model. An unattributed unlock is a person acting
    on the lock and must stay visible.

    A Zigbee lock with no user slot is someone locking from Home Assistant
    and stays visible, except while wake_echo_pending: the auto-wake locks
    the door through ZHA before a PIN write, and the lock reports that as
    an ordinary Zigbee lock, which would otherwise replace the last
    activity every time a PIN is set on a sleeping lock.
    """
    source = decoded["source"]
    anonymous_lock = decoded["action"] == ACTION_LOCK and decoded["user_slot"] is None
    if source == SOURCE_AUTO:
        return True
    if source == SOURCE_UNATTRIBUTED:
        return anonymous_lock
    if source == SOURCE_ZIGBEE:
        return anonymous_lock and wake_echo_pending
    return False


class ZhaInternalsMissing(Exception):
    """The ZHA or zigpy structure the listener relies on is not there.

    detail names the missing piece in code terms, for the log and the
    repair issue.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def register_event_listener(
    hass: HomeAssistant, coordinator: NimlyCoordinator
) -> Callable[[], Any]:
    """Listen for attribute_report events on the DoorLock cluster.

    Returns the unsubscribe callable and records the cluster on
    coordinator.listened_cluster. Raises ZhaInternalsMissing when the
    cluster cannot be found or has no on_event.

    zigpy emits "attribute_report" via cluster.emit() for every Report_Attributes
    ZCL frame, even for unknown attributes and even when value is unchanged.
    This is the only reliable way to catch Onesti's custom attrid 0x0100.
    on_event is not documented zigpy API, which is why its absence is
    reported rather than assumed away.

    The alternatives don't work:
    - add_listener + attribute_updated: suppressed for unknown attributes
    - add_listener + general_command: not dispatched to listeners
    - add_listener + handle_cluster_request: only for cluster commands, not general
    """
    cluster = coordinator.transport.cluster()
    if cluster is None:
        raise ZhaInternalsMissing(f"Door Lock cluster for {coordinator.ieee}")
    on_event = getattr(cluster, "on_event", None)
    if not callable(on_event):
        raise ZhaInternalsMissing(f"{type(cluster).__name__}.on_event")

    def _on_attribute_report(event) -> None:
        # Any report means the radio is awake right now, the moment a
        # capability read that went unanswered at startup can succeed.
        coordinator.schedule_capability_refresh()
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

        decoded = decode_operation_event(coordinator, val)
        if not decoded:
            return

        _LOGGER.info(
            "Lock event: %s by %s via %s (raw: 0x%08x)",
            decoded["action"],
            decoded["user_name"] or "system",
            decoded["source"],
            val,
        )

        if not is_system_lock(decoded, coordinator.wake_echo_pending()):
            coordinator.update_activity(
                decoded["user_slot"], decoded["action"], decoded["source"]
            )
        elif decoded["source"] == SOURCE_ZIGBEE:
            _LOGGER.debug(
                "Zigbee lock on %s taken as the echo of our own wake, "
                "activity sensor left as it was",
                coordinator.ieee,
            )

        hass.bus.async_fire(
            "onesti_lock_activity",
            {"ieee": coordinator.ieee, **decoded},
        )

    unsub = on_event("attribute_report", _on_attribute_report)
    coordinator.listened_cluster = cluster

    _LOGGER.debug("Event listener registered on %s", type(cluster).__name__)
    return unsub
