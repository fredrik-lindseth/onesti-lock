"""Nimly PRO — PIN management and activity tracking for Nimly locks."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nimly PRO from a config entry."""
    coordinator = NimlyCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    # Register services (idempotent)
    from .services import async_setup_services
    await async_setup_services(hass)

    # Set up sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for lock activity via ZHA sensors + zha_event
    unsubs = _setup_listeners(hass, entry, coordinator)
    hass.data[DOMAIN][entry.entry_id]["unsub_listeners"] = unsubs

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unsubscribe from events
    for unsub in hass.data[DOMAIN][entry.entry_id].get("unsub_listeners", []):
        unsub()

    # Unload platforms
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove entry data
    hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove services if no more entries
    if not hass.data[DOMAIN]:
        from .services import async_unload_services
        await async_unload_services(hass)

    return True


def _find_zha_sensor(hass: HomeAssistant, ieee: str, suffix: str) -> str | None:
    """Find a ZHA sensor entity ID by IEEE and unique_id suffix."""
    registry = er.async_get(hass)
    for entity in registry.entities.values():
        if entity.platform != "zha":
            continue
        uid = entity.unique_id or ""
        # Match exact suffix to avoid last_action matching last_action_source
        if ieee.lower() in uid.lower() and uid.endswith(suffix):
            _LOGGER.warning("Matched ZHA sensor: %s → %s", suffix, entity.entity_id)
            return entity.entity_id
    return None


def _setup_listeners(hass: HomeAssistant, entry: ConfigEntry, coordinator: NimlyCoordinator) -> list:
    """Set up both state-change and zha_event listeners."""
    ieee = entry.data[CONF_IEEE]
    unsubs = []

    # Find ZHA sensor entity IDs for this lock
    action_entity = _find_zha_sensor(hass, ieee, "last_action")
    source_entity = _find_zha_sensor(hass, ieee, "last_action_source")
    user_entity = _find_zha_sensor(hass, ieee, "last_action_user")

    _LOGGER.warning(
        "ZHA sensor entities: action=%s, source=%s, user=%s",
        action_entity, source_entity, user_entity,
    )

    if action_entity:
        # Also find the lock entity for state change tracking
        lock_entity = _find_zha_sensor(hass, ieee, "257")  # lock cluster unique_id ends with 257
        _LOGGER.warning("Lock entity: %s", lock_entity)

        @callback
        def _handle_action_change(event: Event) -> None:
            """Handle state changes on lock or ZHA sensors."""
            eid = event.data.get("entity_id", "")

            # Log any dorlasen state change for debugging
            if "dorlasen" in eid:
                new = event.data.get("new_state")
                old = event.data.get("old_state")
                if new and old and new.state != old.state:
                    _LOGGER.warning(
                        "STATE: %s: %s → %s",
                        eid, old.state, new.state,
                    )

            # Track lock entity changes (locked/unlocked)
            if eid == lock_entity:
                new_state = event.data.get("new_state")
                old_state = event.data.get("old_state")
                if not new_state or not old_state:
                    return
                if new_state.state == old_state.state:
                    return

                action = ACTION_UNLOCK if new_state.state == "unlocked" else ACTION_LOCK

                # Read user from ZHA sensor
                user_state = hass.states.get(user_entity) if user_entity else None
                source_state = hass.states.get(source_entity) if source_entity else None

                user_slot = None
                if user_state and user_state.state not in ("unknown", "unavailable"):
                    try:
                        user_slot = int(user_state.state)
                    except (ValueError, TypeError):
                        pass

                source_raw = source_state.state if source_state else "unknown"
                source_map = {
                    "keypad": SOURCE_KEYPAD,
                    "rf": SOURCE_RF,
                    "manual": SOURCE_MANUAL,
                    "self": "remote",
                    "auto": SOURCE_AUTO,
                }
                source = source_map.get(source_raw.lower(), source_raw)

                _LOGGER.warning(
                    "Lock activity: action=%s source=%s user_slot=%s",
                    action, source, user_slot,
                )

                coordinator.update_activity(user_slot, action, source)

                hass.bus.async_fire(
                    "nimly_pro_lock_activity",
                    {
                        "ieee": ieee,
                        "user_slot": user_slot,
                        "user_name": coordinator.get_slot_name(user_slot)
                        if user_slot is not None
                        else None,
                        "action": action,
                        "source": source,
                    },
                )
                return

            if eid != action_entity:
                return

            new_state = event.data.get("new_state")
            if new_state is None:
                return

            action_raw = new_state.state
            if action_raw in ("unknown", "unavailable", None):
                return

            # Read source and user from their current states
            source_state = hass.states.get(source_entity) if source_entity else None
            user_state = hass.states.get(user_entity) if user_entity else None

            source_raw = source_state.state if source_state else "unknown"
            user_raw = user_state.state if user_state else None

            # Map action
            if action_raw.lower() in ("unlock", "unlocked"):
                action = ACTION_UNLOCK
            elif action_raw.lower() in ("lock", "locked"):
                action = ACTION_LOCK
            else:
                action = action_raw

            # Map source
            source_map = {
                "keypad": SOURCE_KEYPAD,
                "rf": SOURCE_RF,
                "manual": SOURCE_MANUAL,
                "self": SOURCE_RF,  # "self" = remote/HA command
                "auto": SOURCE_AUTO,
            }
            source = source_map.get(source_raw.lower(), source_raw)

            # Parse user slot
            user_slot = None
            if user_raw and user_raw not in ("unknown", "unavailable", "None"):
                try:
                    user_slot = int(user_raw)
                except (ValueError, TypeError):
                    pass

            _LOGGER.warning(
                "Lock activity: action=%s source=%s user_slot=%s",
                action, source, user_slot,
            )

            coordinator.update_activity(user_slot, action, source)

            # Fire HA event for automations
            hass.bus.async_fire(
                "nimly_pro_lock_activity",
                {
                    "ieee": ieee,
                    "user_slot": user_slot,
                    "user_name": coordinator.get_slot_name(user_slot)
                    if user_slot is not None
                    else None,
                    "action": action,
                    "source": source,
                },
            )

        unsubs.append(hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_action_change))
    else:
        _LOGGER.warning("Could not find ZHA last_action sensor for %s", ieee)

    # Also keep zha_event listener as fallback
    @callback
    def _handle_zha_event(event: Event) -> None:
        data = event.data
        if data.get("device_ieee", "").lower() != ieee.lower():
            return
        command = data.get("command")
        if command == "operation_event_notification":
            args = data.get("args", {})
            _LOGGER.debug("ZHA event: %s %s", command, args)

    unsubs.append(hass.bus.async_listen("zha_event", _handle_zha_event))

    return unsubs
