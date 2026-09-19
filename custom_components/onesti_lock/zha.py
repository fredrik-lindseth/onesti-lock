"""Everything that knows ZHA and zigpy internals.

ZHA offers no public API for reaching a device's zigpy clusters, so this
module leans on the object layout of a running ZHA: hass.data["zha"],
its gateway_proxy, the device_proxies mapping and the .device chain down
to the zigpy device. Keeping that knowledge here means a ZHA rename is a
change to one file, and the rest of the integration talks to a lock
through ZhaLockTransport.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOORLOCK_CLUSTER_ID, ZHA_DOMAIN

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


def _gateway_proxy(hass: HomeAssistant):
    """ZHA's gateway proxy, or None when ZHA is not loaded."""
    if ZHA_DOMAIN not in hass.data:
        return None
    return getattr(hass.data[ZHA_DOMAIN], "gateway_proxy", None)


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
    if ZHA_DOMAIN not in hass.data:
        _LOGGER.error("ZHA not found")
        return None

    if _gateway_proxy(hass) is None:
        _LOGGER.error("ZHA gateway_proxy not found")
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

    ZHA unique ids end in the cluster id in decimal, and 257 is DoorLock
    0x0101, so the suffix tells the lock entity from the device's sensors.
    """
    registry = er.async_get(hass)
    for entity in registry.entities.values():
        if entity.platform != "zha":
            continue
        uid = entity.unique_id or ""
        if ieee.lower() in uid.lower() and uid.endswith("257"):
            return entity.entity_id
    return None


class ZhaLockTransport:
    """Talks to one lock's Door Lock cluster through ZHA."""

    def __init__(self, hass: HomeAssistant, ieee: str) -> None:
        self.hass = hass
        self.ieee = ieee

    def cluster(self):
        """The lock's zigpy Door Lock cluster, or None."""
        return find_door_lock_cluster(self.hass, self.ieee)

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
        try:
            entity_id = find_lock_entity_id(self.hass, self.ieee)
            if entity_id is None:
                return
            _LOGGER.debug("Waking lock via %s", entity_id)
            await self.hass.services.async_call(
                "lock", "lock",
                {"entity_id": entity_id},
                blocking=True,
            )
            await asyncio.sleep(1)
        except Exception:
            _LOGGER.debug("Wake attempt failed, proceeding anyway")

    async def send(self, command: int, params: dict) -> bool:
        """Send a ZCL command, handling Nimly response quirk.

        Tries ZHA issue_zigbee_cluster_command first. If it times out,
        wakes the lock and retries once.

        Returns True if command was sent (even if response parsing failed).
        Returns False if command could not be sent at all.
        """
        for attempt in range(2):
            try:
                await self.hass.services.async_call(
                    "zha",
                    "issue_zigbee_cluster_command",
                    {
                        "ieee": self.ieee,
                        "endpoint_id": 11,
                        "cluster_id": DOORLOCK_CLUSTER_ID,
                        "cluster_type": "in",
                        "command": command,
                        "command_type": "server",
                        "params": params,
                    },
                    blocking=True,
                )
                return True
            except IndexError:
                # Nimly quirk: command was sent and received, but response
                # format is unexpected causing "tuple index out of range"
                # in zigpy response parsing. Command still reached the lock.
                _LOGGER.debug(
                    "Nimly response quirk (IndexError) for command 0x%04x, "
                    "command was sent successfully",
                    command,
                )
                return True
            except TimeoutError:
                if attempt == 0:
                    _LOGGER.info(
                        "Timeout on attempt 1 for command 0x%04x, waking lock and retrying",
                        command,
                    )
                    await self.wake()
                    continue
                _LOGGER.warning(
                    "Timeout sending command 0x%04x to %s after wake+retry; "
                    "lock may be unreachable",
                    command,
                    self.ieee,
                )
                return False
            except Exception:
                _LOGGER.exception("Failed to send command 0x%04x to %s", command, self.ieee)
                return False
        return False

    async def read_capabilities(self) -> dict[str, int]:
        """Read static lock properties from the DoorLock cluster.

        Returns whichever of num_pin_users, max_pin_length and
        min_pin_length the lock reported, possibly none. Degrades silently
        if the lock does not expose them: some Onesti variants skip these
        standard ZCL attributes, and a sleepy device may never respond.
        """
        cluster = self.cluster()
        if cluster is None:
            return {}
        try:
            result = await cluster.read_attributes(_CAPABILITY_ATTR_IDS)
        except TimeoutError:
            _LOGGER.debug("Lock capabilities read timed out (lock asleep or out of range)")
            return {}
        except (AttributeError, TypeError):
            _LOGGER.debug("Lock capabilities read failed (cluster API shape changed?)", exc_info=True)
            return {}
        except Exception:
            # zigpy/ZHA-side errors: DeliveryError, ZigbeeException, etc.
            # We deliberately keep this wide so an exotic firmware quirk on one
            # lock does not block integration setup for everyone else.
            _LOGGER.debug("Lock capabilities read failed", exc_info=True)
            return {}

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
