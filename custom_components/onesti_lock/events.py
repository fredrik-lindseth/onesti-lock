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


def decode_operation_event(coordinator: NimlyCoordinator, val: int) -> dict[str, Any] | None:
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


def is_system_lock(decoded: dict[str, Any], wake_echo_pending: bool = False) -> bool:
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


class _AttributeUpdatedListener:
    """A zigpy listener object for the pre-0.91 add_listener path.

    zigpy's ListenableMixin dispatches by method name, so the hook is a
    method rather than a callback. Older zigpy calls it with three
    positional arguments; the default keeps the two-argument form working
    if that ever changes back.
    """

    def __init__(self, handle: Callable[[Any, Any], None]) -> None:
        self._handle = handle

    def attribute_updated(self, attrid: Any, value: Any, timestamp: Any = None) -> None:
        self._handle(attrid, value)


def register_event_listener(
    hass: HomeAssistant, coordinator: NimlyCoordinator
) -> Callable[[], Any]:
    """Listen for attribute reports on the DoorLock cluster.

    Returns the unsubscribe callable and records the cluster on
    coordinator.listened_cluster. Raises ZhaInternalsMissing when the
    cluster cannot be found, or when neither hook below exists.

    Which hook is there depends on the zigpy version Home Assistant's ZHA
    pins, so both are supported and the same handler runs behind them:

    - zigpy 0.91 and newer (HA 2026.2 and up): Cluster inherits EventBase
      and emits "attribute_report" for every Report_Attributes frame, even
      for unknown attributes and even when the value is unchanged.
      cluster.on_event("attribute_report", ...) subscribes to it.
    - zigpy before 0.91 (HA 2025.6 through 2026.1 pin 0.80.1 to 0.90.0):
      no Cluster.on_event at all. A listener object registered with
      cluster.add_listener gets attribute_updated(attrid, value, timestamp)
      instead, and cluster.remove_listener takes it off again.

    The second path was checked against real zigpy 0.80.1 on 2026-09-19:
    handle_cluster_general_request calls _update_attribute for every
    attribute in a Report_Attributes frame, unknown attrids included, and
    _update_attribute fires listener_event("attribute_updated", ...)
    unconditionally. An earlier version of this docstring claimed
    attribute_updated was suppressed for unknown attributes; that is wrong
    for 0.80.1, and the fallback rests on it not being. The path also fires
    for our own attribute reads (0x0012 and friends), which the attrid
    filter drops and which are the same "radio is awake" signal anyway.

    Neither hook is documented zigpy API, which is why the absence of both
    is reported rather than assumed away.

    The alternatives still don't work:
    - add_listener + general_command: not dispatched to listeners
    - add_listener + handle_cluster_request: only for cluster commands, not general
    """
    cluster = coordinator.transport.cluster()
    if cluster is None:
        raise ZhaInternalsMissing(f"Door Lock cluster for {coordinator.ieee}")

    def _handle_report(attribute_id: Any, raw: Any) -> None:
        # Any report means the radio is awake right now, the moment a
        # capability read that went unanswered at startup can succeed.
        coordinator.schedule_capability_refresh()
        if attribute_id != ATTR_OPERATION_EVENT:
            return

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

    unsub, how = _subscribe(cluster, _handle_report)
    coordinator.listened_cluster = cluster

    _LOGGER.debug("Event listener registered on %s via %s", type(cluster).__name__, how)
    return unsub


def _subscribe(cluster: Any, handle: Callable[[Any, Any], None]) -> tuple[Callable[[], Any], str]:
    """Subscribe handle to the cluster's attribute reports.

    Returns the unsubscribe callable and the name of the hook used, for
    the debug line. Raises ZhaInternalsMissing when the cluster offers
    neither hook.
    """
    on_event = getattr(cluster, "on_event", None)
    if callable(on_event):
        return on_event("attribute_report", lambda event: handle(event.attribute_id, event.raw_value)), "on_event"

    add_listener = getattr(cluster, "add_listener", None)
    remove_listener = getattr(cluster, "remove_listener", None)
    if not callable(add_listener) or not callable(remove_listener):
        raise ZhaInternalsMissing(
            f"{type(cluster).__name__}.on_event, and no add_listener/remove_listener either"
        )

    listener = _AttributeUpdatedListener(handle)
    add_listener(listener)
    return lambda: remove_listener(listener), "add_listener"
