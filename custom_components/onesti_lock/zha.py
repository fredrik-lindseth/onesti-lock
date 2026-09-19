"""Everything that knows ZHA and zigpy internals.

ZHA offers no public API for reaching a device's zigpy clusters, so this
module leans on the object layout of a running ZHA: the gateway proxy from
ZHA's own get_zha_gateway_proxy helper, its device_proxies mapping and the
.device chain down to the zigpy device. Keeping that knowledge here means a
ZHA rename is a change to one file, and the rest of the integration talks to
a lock through ZhaLockTransport.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# ZHA is a manifest dependency, so its helpers and the zigpy it ships are
# importable whenever this integration is.
from homeassistant.components.zha.helpers import get_zha_gateway_proxy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from zigpy.exceptions import DeliveryError, ZigbeeException
from zigpy.zcl.foundation import Status

from .const import DOORLOCK_CLUSTER_ID, WAKE_ECHO_WINDOW_S, ZHA_DOMAIN
from .redact import redact_digits

_LOGGER = logging.getLogger(__name__)

# How far down the .device chain to look: ZHADeviceProxy -> Device ->
# CustomDeviceV2 is three objects, one spare level covers a future wrapper.
_CHAIN_DEPTH = 4

# Standard ZCL DoorLock attributes (per zigpy.zcl.clusters.closures):
#   0x0012 NumberOfPINUsersSupported
#   0x0017 MaxPINCodeLength
#   0x0018 MinPINCodeLength
_CAPABILITY_ATTR_IDS = [0x0012, 0x0017, 0x0018]
# Keyed by both the numeric id and zigpy's own attribute name for the
# same attribute, because zigpy keys the success dict by whatever the
# caller passed in and a quirk or a future zigpy may hand back names
# instead. Looking up only ids drops a name-keyed reading silently,
# which is how the Z2M converter missed numOfPinUsersSupported.
# Names are from zigpy.zcl.clusters.closures.DoorLock (unchanged
# between zigpy 1.2.1 and 2.1.0).
_CAPABILITY_NAMES = {
    0x0012: "num_pin_users",
    "num_of_pin_users_supported": "num_pin_users",
    0x0017: "max_pin_length",
    "max_pin_len": "max_pin_length",
    0x0018: "min_pin_length",
    "min_pin_len": "min_pin_length",
}


# Set PIN Code (0x0005) and its response. The ZCL Door Lock spec gives the
# response's status byte four values: 0 success, 1 general failure, 2 memory
# full, 3 duplicate code. Which of them a Nimly lock actually sends has not
# been captured on hardware, so 2 and 3 are read by the spec alone.
_SET_PIN_COMMAND = 0x0005
_SET_PIN_STATUS_MEMORY_FULL = 0x02
_SET_PIN_STATUS_DUPLICATE_CODE = 0x03


class Delivery(enum.Enum):
    """What became of one ZCL command sent to the lock."""

    # The lock received it and reported no failure.
    DELIVERED = "delivered"
    # The lock answered, so it is awake, but with a failure status.
    REJECTED = "rejected"
    # No answer, or the command could not be sent at all.
    UNREACHED = "unreached"


class Rejection(enum.Enum):
    """Why the lock refused a command, where the status tells."""

    DUPLICATE_CODE = "duplicate_code"
    MEMORY_FULL = "memory_full"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """The result of ZhaLockTransport.send.

    status is the ZCL status the lock answered with, set only for REJECTED.
    It is None there too when the answer carried a status that is not a
    number, which zigpy never produces but a quirk could.
    """

    delivery: Delivery
    status: int | None = None
    rejection: Rejection | None = None

    @property
    def delivered(self) -> bool:
        return self.delivery is Delivery.DELIVERED

    @property
    def lock_answered(self) -> bool:
        """Whether the lock's radio answered, which it only does awake."""
        return self.delivery is not Delivery.UNREACHED

    @property
    def error_key(self) -> str | None:
        """The translation key for this outcome, None when delivered.

        The same key names the service exception (exceptions section) and
        the options flow error (options.error section).
        """
        if self.delivery is Delivery.DELIVERED:
            return None
        if self.delivery is Delivery.UNREACHED:
            return "lock_unreachable"
        if self.rejection is Rejection.DUPLICATE_CODE:
            return "lock_rejected_duplicate"
        if self.rejection is Rejection.MEMORY_FULL:
            return "lock_rejected_memory_full"
        return "lock_rejected"

    @property
    def status_text(self) -> str:
        """The status for messages: its number, or "?" when it had none."""
        return "?" if self.status is None else str(self.status)


SEND_DELIVERED = SendOutcome(Delivery.DELIVERED)
SEND_UNREACHED = SendOutcome(Delivery.UNREACHED)


def rejected(command: int, response: Any, status: Any) -> SendOutcome:
    """The outcome for an answer with a failure status.

    Memory full and duplicate code are only told apart for Set PIN Code's
    own response. A Default Response carries a general ZCL status, where
    2 and 3 mean nothing of the kind, and it is the one with command_id.
    """
    try:
        code: int | None = int(status)
    except (TypeError, ValueError):
        code = None
    rejection = Rejection.OTHER
    if command == _SET_PIN_COMMAND and not hasattr(response, "command_id"):
        if code == _SET_PIN_STATUS_DUPLICATE_CODE:
            rejection = Rejection.DUPLICATE_CODE
        elif code == _SET_PIN_STATUS_MEMORY_FULL:
            rejection = Rejection.MEMORY_FULL
    return SendOutcome(Delivery.REJECTED, status=code, rejection=rejection)


def _gateway_proxy(hass: HomeAssistant):
    """ZHA's gateway proxy, or None when ZHA has no running gateway."""
    try:
        return get_zha_gateway_proxy(hass)
    except ValueError:
        # ZHA's own signal for "no gateway object exists": not set up yet,
        # failed to start, or being reloaded.
        return None


def is_zha_loaded(hass: HomeAssistant) -> bool:
    """Whether ZHA is set up far enough to list its devices."""
    return _gateway_proxy(hass) is not None


def iter_device_proxies(hass: HomeAssistant) -> Iterator[tuple[Any, Any]]:
    """Yield (ieee, ZHADeviceProxy) for every ZHA device, nothing without ZHA.

    The ieee is ZHA's own key, an EUI64 whose str() may differ in case from
    the ieee stored in a config entry.
    """
    gateway_proxy = _gateway_proxy(hass)
    if gateway_proxy is None:
        return
    yield from gateway_proxy.device_proxies.items()


def device_metadata(proxy) -> tuple[str, str]:
    """(manufacturer, model) as the ZHA device reports them."""
    device = proxy.device if hasattr(proxy, "device") else proxy
    return getattr(device, "manufacturer", ""), getattr(device, "model", "")


def _walk_to_door_lock_cluster(obj):
    """The Door Lock cluster below obj, or None.

    Walks the ZHA object chain: ZHADeviceProxy → Device → CustomDeviceV2
    because clusters live on the deepest zigpy device object, not the
    ZHA wrapper layers.
    """
    for _ in range(_CHAIN_DEPTH):
        if hasattr(obj, "endpoints"):
            for ep_id, ep in obj.endpoints.items():
                if ep_id == 0:
                    continue
                clusters = getattr(ep, "in_clusters", {})
                if DOORLOCK_CLUSTER_ID in clusters:
                    return clusters[DOORLOCK_CLUSTER_ID]
        if hasattr(obj, "device"):
            obj = obj.device
        else:
            break
    return None


def has_door_lock_cluster(obj) -> bool:
    """Whether the ZHA device exposes the Door Lock cluster."""
    return _walk_to_door_lock_cluster(obj) is not None


def find_door_lock_cluster(hass: HomeAssistant, ieee: str):
    """Get the Door Lock cluster for one device from ZHA, or None."""
    if _gateway_proxy(hass) is None:
        _LOGGER.error("ZHA has no running gateway, so the lock cannot be reached")
        return None

    for dev_ieee, proxy in iter_device_proxies(hass):
        if str(dev_ieee).lower() != ieee.lower():
            continue
        cluster = _walk_to_door_lock_cluster(proxy)
        if cluster is not None:
            return cluster

    _LOGGER.error("Door Lock cluster not found for %s", ieee)
    return None


def find_lock_entity_id(hass: HomeAssistant, ieee: str) -> str | None:
    """Entity id of ZHA's own lock entity for this device, or None.

    ZHA registers its devices with a zigbee connection holding str(EUI64),
    which zigpy renders in lowercase. The device is looked up among the
    devices of ZHA's own config entries: from HA 2026.9 a connection is
    only unique within one config entry, and async_get_device, which
    searched them all, is deprecated. The lock entity is then the one
    entity on that device in the lock domain from the zha platform, so no
    unique_id format has to be parsed. Disabled entities are skipped: HA
    would refuse the service call anyway.
    """
    connection = (dr.CONNECTION_ZIGBEE, ieee.lower())
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    for zha_entry in hass.config_entries.async_entries(ZHA_DOMAIN):
        for device in dr.async_entries_for_config_entry(device_registry, zha_entry.entry_id):
            if connection not in device.connections:
                continue
            for entity in er.async_entries_for_device(entity_registry, device.id):
                if entity.domain == "lock" and entity.platform == ZHA_DOMAIN:
                    return entity.entity_id
    return None


def _status_name(status: Any) -> str:
    """A ZCL status as text, by name when zigpy knows it."""
    name = getattr(status, "name", None)
    return name if isinstance(name, str) else str(status)


class ZhaLockTransport:
    """Talks to one lock's Door Lock cluster through ZHA."""

    def __init__(self, hass: HomeAssistant, ieee: str) -> None:
        self.hass = hass
        self.ieee = ieee
        # time.monotonic() of the last wake actuation, for wake_echo_pending.
        self._last_wake: float | None = None

    def cluster(self):
        """The lock's zigpy Door Lock cluster, or None."""
        return find_door_lock_cluster(self.hass, self.ieee)

    def wake_echo_pending(self) -> bool:
        """Whether a Zigbee lock event now may be the echo of our own wake.

        True within WAKE_ECHO_WINDOW_S of the last wake actuation. Not
        consumed by asking: the lock may report the wake more than once.
        """
        return (
            self._last_wake is not None
            and time.monotonic() - self._last_wake < WAKE_ECHO_WINDOW_S
        )

    async def wake(self) -> None:
        """Wake the lock's radio by sending a real lock command via ZHA.

        This is a physical actuation: an unlocked door gets locked, and an
        open door drives the bolt into the air. We use lock.lock because it
        works and attribute reads through our own cluster path time out (see
        read_capabilities). Why it works is not established. ZHA's lock
        entity wraps the command in longer timeouts and retries for sleepy
        devices, which is the likely reason, but at the radio level a read
        and a write are queued the same way. Swapping this for a wake that
        does not move the bolt needs hardware verification first, tracked as
        a separate issue.
        """
        previous_wake = self._last_wake
        try:
            entity_id = find_lock_entity_id(self.hass, self.ieee)
            if entity_id is None:
                _LOGGER.warning(
                    "No ZHA lock entity found for %s, so the lock cannot be woken",
                    self.ieee,
                )
                return
            _LOGGER.debug("Waking lock via %s", entity_id)
            # Stamped before the call: the lock may report the lock event
            # while the blocking service call is still waiting.
            self._last_wake = time.monotonic()
            await self.hass.services.async_call(
                "lock", "lock",
                {"entity_id": entity_id},
                blocking=True,
            )
            await asyncio.sleep(1)
        except Exception as err:
            # This lock command failed, so a Zigbee lock event in the next
            # window is not known to be its echo. Keeping the stamp would
            # hide a real lock from the dashboard. An earlier wake that did
            # go out keeps its own window.
            self._last_wake = previous_wake
            # A failed wake must not abort the send: the retry runs anyway.
            _LOGGER.debug(
                "Wake attempt failed (%s), proceeding anyway", type(err).__name__
            )

    async def send(self, command: int, params: dict) -> SendOutcome:
        """Send a ZCL command to the lock's Door Lock cluster.

        Calls the command on the zigpy cluster directly, the same call ZHA's
        issue_zigbee_cluster_command service ends in, with zigpy's default
        reply timeout and no manufacturer code, as the service does for a
        standard cluster. The service is not used because Home Assistant
        fires a call_service event with the full service data for every
        call, and the recorder stores it: a PIN would land in the database.

        If the command times out or zigpy reports a failed delivery, both
        of which a sleeping lock causes, the lock is woken and the command
        retried once. Any other Zigbee error is not about sleep, so it fails
        at once without actuating the door. Neither does an answer with a
        failure status: the lock is awake, and it refused.

        Returns DELIVERED when the lock received the command and did not
        answer with a failure status, REJECTED with the status when it did,
        and UNREACHED when the command did not get through. Never raises.

        Nothing here logs a traceback or a raw exception message: params
        may hold a PIN code, and an error may quote them. Messages go
        through redact_digits.
        """
        cluster = self.cluster()
        if cluster is None:
            # find_door_lock_cluster has logged why.
            return SEND_UNREACHED
        for attempt in (1, 2):
            try:
                response = await cluster.command(command, **params)
            except IndexError:
                # Nimly quirk: the command reached the lock, but its answer
                # could not be read ("tuple index out of range"). See
                # _outcome for where the known case came from.
                _LOGGER.debug(
                    "Nimly response quirk (IndexError) for command 0x%04x, "
                    "command was sent successfully",
                    command,
                )
                return SEND_DELIVERED
            except (TimeoutError, DeliveryError) as err:
                if attempt == 1:
                    _LOGGER.info(
                        "%s on attempt 1 for command 0x%04x, waking lock and retrying",
                        type(err).__name__,
                        command,
                    )
                    await self.wake()
                    continue
                _LOGGER.warning(
                    "%s sending command 0x%04x to %s after wake and retry, "
                    "lock may be unreachable: %s",
                    type(err).__name__,
                    command,
                    self.ieee,
                    redact_digits(err),
                )
                return SEND_UNREACHED
            except ZigbeeException as err:
                _LOGGER.warning(
                    "Zigbee error sending command 0x%04x to %s: %s: %s",
                    command,
                    self.ieee,
                    type(err).__name__,
                    redact_digits(err),
                )
                return SEND_UNREACHED
            except Exception as err:
                # The caller gets an outcome, never a raise.
                _LOGGER.error(
                    "Failed to send command 0x%04x to %s: %s: %s",
                    command,
                    self.ieee,
                    type(err).__name__,
                    redact_digits(err),
                )
                return SEND_UNREACHED
            return self._outcome(command, response)
        return SEND_UNREACHED

    def _outcome(self, command: int, response: Any) -> SendOutcome:
        """What the lock's answer to a delivered command says.

        Mirrors how ZHA's issue_cluster_command reads the answer (zha 2.x):
        nothing to read counts as success, an exception handed back as the
        result is a failure, and otherwise the answer's status field decides
        if it has one. The answer is a Default Response or the command's own
        response, such as Set PIN Code Response, and both name the field
        status. zha 0.0.x, which HA 2025.6 ships, read response[1] instead,
        which raises IndexError on the one-field Set PIN Code Response. That
        is the most likely source of the Nimly IndexError quirk, and it
        means the status was never checked there.

        An exception handed back is not the lock's answer, so it counts as
        unreached, not as a refusal.
        """
        if response is None:
            return SEND_DELIVERED
        if isinstance(response, Exception):
            _LOGGER.warning(
                "Command 0x%04x to %s failed: %s: %s",
                command,
                self.ieee,
                type(response).__name__,
                redact_digits(response),
            )
            return SEND_UNREACHED
        status = getattr(response, "status", None)
        if status is None or status == Status.SUCCESS:
            return SEND_DELIVERED
        outcome = rejected(command, response, status)
        _LOGGER.warning(
            "Lock %s refused command 0x%04x with status %s (%s)",
            self.ieee,
            command,
            redact_digits(_status_name(status)),
            outcome.rejection.value if outcome.rejection else "",
        )
        return outcome

    async def read_capabilities(self) -> dict[str, int] | None:
        """Read static lock properties from the DoorLock cluster.

        Returns None when the lock was not reached, so the read is worth
        repeating once the radio is awake. Otherwise returns whichever of
        num_pin_users, max_pin_length and min_pin_length the lock reported,
        possibly none: an answer without them is final, since some Onesti
        variants skip these standard ZCL attributes.
        """
        cluster = self.cluster()
        if cluster is None:
            return None
        try:
            result = await cluster.read_attributes(_CAPABILITY_ATTR_IDS)
        except (TimeoutError, DeliveryError) as err:
            _LOGGER.debug(
                "Lock capabilities read failed with %s (lock asleep or out of range)",
                type(err).__name__,
            )
            return None
        except (AttributeError, TypeError):
            _LOGGER.debug("Lock capabilities read failed (cluster API shape changed?)", exc_info=True)
            return None
        except Exception:
            # Other zigpy/ZHA-side errors. Deliberately wide so an exotic
            # firmware quirk on one lock does not block setup for everyone.
            _LOGGER.debug("Lock capabilities read failed", exc_info=True)
            return None

        # zigpy returns (success_dict, failure_dict). Keys may be attribute
        # IDs or attribute names depending on cluster metadata.
        success = result[0] if isinstance(result, tuple) and len(result) >= 1 else {}
        failure = result[1] if isinstance(result, tuple) and len(result) >= 2 else {}
        if failure:
            _LOGGER.debug("Lock did not expose capabilities: %s", failure)
        capabilities: dict[str, int] = {}
        for key, value in success.items():
            name = _CAPABILITY_NAMES.get(key)
            if name and value is not None:
                capabilities[name] = int(value)
        return capabilities
