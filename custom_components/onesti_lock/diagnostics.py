"""Diagnostics for Onesti Lock: what a bug report needs, and no one's names.

Nothing in the integration stores a PIN, so there is none to redact here;
tests_ha/test_pin_canary.py proves that for this output too. Two things are
personal and are left out of what a user attaches to a public issue:

- The lock's IEEE address, which HA's own ZHA diagnostics already carries
  for anyone who needs it. It is redacted wherever it appears in the entry.
- Slot names, which are the names of the people in a household. A bug about
  slots turns on whether a slot is named, not on what the name is, so each
  name becomes "named" or "unnamed". A plain redaction would hide exactly
  that difference.

Only the known slot fields are copied, so a field added to storage later
does not reach a public issue until someone decides it should.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration

from . import ISSUE_ZHA_INTERNALS
from .const import CONF_IEEE, DOMAIN, ZHA_DOMAIN
from .coordinator import NimlyConfigEntry, NimlyCoordinator
from .zha import (
    device_metadata,
    find_lock_entity_id,
    has_door_lock_cluster,
    is_zha_loaded,
    iter_device_proxies,
)

# The title is "Onesti Lock (<end of the IEEE>)", so it goes with the rest.
TO_REDACT = {CONF_IEEE, "title", "unique_id"}

NAMED = "named"
UNNAMED = "unnamed"


def _name_state(name: Any) -> str:
    return NAMED if name else UNNAMED


def _slots(stored: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: {
            "name": _name_state(slot.get("name")),
            "has_pin": bool(slot.get("has_pin", False)),
        }
        for key, slot in stored.items()
    }


def _options(options: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(options)
    result["slots"] = _slots(options.get("slots", {}))
    return result


def _zha(hass: HomeAssistant, coordinator: NimlyCoordinator) -> dict[str, Any]:
    """ZHA's side: is it up, does it know the lock, and which cluster we hold."""
    proxy = next(
        (p for ieee, p in iter_device_proxies(hass) if str(ieee).lower() == coordinator.ieee.lower()),
        None,
    )
    # Looked up only once ZHA lists the device, so a missing lock is
    # reported here rather than as an error line in the log.
    cluster = coordinator.transport.cluster() if proxy is not None else None
    manufacturer, model = device_metadata(proxy) if proxy is not None else (None, None)
    return {
        "loaded": is_zha_loaded(hass),
        "entry_states": [
            zha_entry.state.value for zha_entry in hass.config_entries.async_entries(ZHA_DOMAIN)
        ],
        "device_found": proxy is not None,
        "manufacturer": manufacturer,
        "model": model,
        "door_lock_cluster_found": proxy is not None and has_door_lock_cluster(proxy),
        "cluster_type": type(cluster).__name__ if cluster is not None else None,
        "cluster_endpoint": getattr(getattr(cluster, "endpoint", None), "endpoint_id", None),
        "lock_entity_found": find_lock_entity_id(hass, coordinator.ieee) is not None,
    }


def _listener(coordinator: NimlyCoordinator, hass: HomeAssistant, entry: NimlyConfigEntry) -> dict[str, Any]:
    listened = coordinator.listened_cluster
    current = coordinator.transport.cluster() if listened is not None and is_zha_loaded(hass) else None
    return {
        "registered": listened is not None,
        "cluster_type": type(listened).__name__ if listened is not None else None,
        # False means ZHA rebuilt the cluster and the reload has not happened.
        "on_current_cluster": listened is not None and listened is current,
        "repair_issue": ir.async_get(hass).async_get_issue(
            DOMAIN, f"{ISSUE_ZHA_INTERNALS}_{entry.entry_id}"
        )
        is not None,
    }


def _last_activity(hass: HomeAssistant, coordinator: NimlyCoordinator) -> dict[str, Any] | None:
    """The raw fields of the last activity, the user's name reduced like a slot's.

    Read from the sensor's state attributes. The state itself is left out:
    it is these fields rendered as a sentence with the name in it.
    """
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{coordinator.ieee}-activity"
    )
    state = hass.states.get(entity_id) if entity_id else None
    if state is None or "action" not in state.attributes:
        return None
    attributes = state.attributes
    slot = attributes.get("user_slot")
    return {
        "user_slot": slot,
        "user_name": None if slot is None else _name_state(coordinator.get_slot(slot)["name"]),
        "action": attributes.get("action"),
        "source": attributes.get("source"),
        "timestamp": attributes.get("timestamp"),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NimlyConfigEntry
) -> dict[str, Any]:
    """Diagnostics for one lock's config entry."""
    coordinator = entry.runtime_data
    integration = await async_get_integration(hass, DOMAIN)
    return {
        "integration_version": str(integration.version),
        "home_assistant_version": HA_VERSION,
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "version": entry.version,
                "minor_version": entry.minor_version,
                "data": dict(entry.data),
                "options": _options(entry.options),
            },
            TO_REDACT,
        ),
        "first_user_slot": coordinator.first_user_slot(),
        "setup_first_user_slot": coordinator.setup_first_user_slot,
        "max_user_slot": coordinator.max_user_slot(),
        "capabilities_final": coordinator.capabilities_final,
        "lock_capabilities": dict(coordinator.lock_capabilities),
        "zha": _zha(hass, coordinator),
        "listener": _listener(coordinator, hass, entry),
        "wake_echo_pending": coordinator.wake_echo_pending(),
        "last_activity": _last_activity(hass, coordinator),
    }
