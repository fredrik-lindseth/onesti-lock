"""Onesti Lock — PIN management and activity tracking for Onesti/Nimly locks."""
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
    DOORLOCK_CLUSTER_ID,
    SOURCE_AUTO,
    SOURCE_KEYPAD,
    SOURCE_MANUAL,
    SOURCE_RF,
    SOURCE_UNKNOWN,
    ZHA_DOMAIN,
)
from .coordinator import NimlyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

ATTR_OPERATION_EVENT = 0x0100

_SOURCE_MAP = {
    0x01: SOURCE_RF,
    0x02: SOURCE_KEYPAD,
    0x03: SOURCE_MANUAL,
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

    _register_cluster_listeners(hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
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


def _register_cluster_listeners(hass: HomeAssistant, coordinator: NimlyCoordinator) -> None:
    """Register attribute listeners on ALL DoorLock cluster objects in the device chain.

    The ZHA/zigpy quirk chain has multiple cluster objects for the same physical cluster:
    CustomDeviceV2 → Device → ZHADeviceProxy — each with their own cluster instance.
    zigpy dispatches attribute_updated to just one of them. We register on all to be safe.
    """
    zha_data = hass.data.get(ZHA_DOMAIN)
    if not zha_data or not hasattr(zha_data, "gateway_proxy"):
        _LOGGER.error("ZHA not available")
        return

    ieee = coordinator.ieee
    registered = 0

    # Find the device proxy
    for dev_ieee, proxy in zha_data.gateway_proxy.device_proxies.items():
        if str(dev_ieee).lower() != ieee.lower():
            continue

        # Walk the device chain and collect all DoorLock cluster objects
        clusters_found = {}
        obj = proxy
        for depth in range(4):
            if hasattr(obj, "endpoints"):
                for ep_id, ep in obj.endpoints.items():
                    if ep_id == 0:
                        continue
                    in_clusters = getattr(ep, "in_clusters", {})
                    if DOORLOCK_CLUSTER_ID in in_clusters:
                        cl = in_clusters[DOORLOCK_CLUSTER_ID]
                        if id(cl) not in clusters_found:
                            clusters_found[id(cl)] = (cl, depth, type(obj).__name__)
            if hasattr(obj, "device"):
                obj = obj.device
            else:
                break

        # Register listener on each unique cluster object
        for cl_id, (cluster, depth, dev_type) in clusters_found.items():
            listener = _OperationEventListener(hass, coordinator)
            cluster.add_listener(listener)
            registered += 1
            _LOGGER.warning(
                "Registered listener on depth %d (%s) cluster %s (id=%s, listeners=%d)",
                depth, dev_type, type(cluster).__name__, cl_id, len(cluster._listeners),
            )

    _LOGGER.warning("Total listeners registered: %d", registered)


class _OperationEventListener:
    """Zigpy cluster listener for Onesti operation events."""

    def __init__(self, hass: HomeAssistant, coordinator: NimlyCoordinator) -> None:
        self._hass = hass
        self._coordinator = coordinator

    def attribute_updated(self, attrid, value, timestamp=None) -> None:
        """Called by zigpy when attribute value CHANGES (cached)."""
        self._handle_attribute(attrid, value)

    def cluster_command(self, tsn, command_id, args) -> None:
        """Not used."""
        pass

    def handle_cluster_request(self, hdr, args, *, dst_addressing=None) -> None:
        """Called for ALL incoming ZCL commands, including Report_Attributes.

        This fires for every report, even when the value hasn't changed —
        unlike attribute_updated which only fires on value change.
        """
        # command_id 0x0A = Report_Attributes
        if hdr.command_id == 0x0A and args:
            for attr in args.attribute_reports:
                self._handle_attribute(attr.attrid, attr.value.value if hasattr(attr.value, 'value') else attr.value)

    def _handle_attribute(self, attrid, value) -> None:
        """Process an attribute report for operation events."""
        if attrid != ATTR_OPERATION_EVENT:
            return

        try:
            val = int(value)
        except (TypeError, ValueError):
            val = int(getattr(value, "value", 0))

        decoded = _decode_operation_event(self._coordinator, val)
        if not decoded:
            return

        _LOGGER.warning(
            "Lock event: %s by %s via %s (raw: 0x%08x)",
            decoded["action"],
            decoded["user_name"] or "system",
            decoded["source"],
            val,
        )

        self._coordinator.update_activity(
            decoded["user_slot"], decoded["action"], decoded["source"]
        )

        self._hass.bus.async_fire(
            "onesti_lock_activity",
            {
                "ieee": self._coordinator.ieee,
                **decoded,
            },
        )
