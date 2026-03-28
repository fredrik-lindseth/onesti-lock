"""Nimly PRO — PIN management and activity tracking for Nimly locks."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    ACTION_LOCK,
    ACTION_UNLOCK,
    ACTION_UNKNOWN,
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

    # Listen for ZHA events from this lock
    unsub = _setup_event_listener(hass, coordinator)
    hass.data[DOMAIN][entry.entry_id]["unsub_event"] = unsub

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unsubscribe from events
    unsub = hass.data[DOMAIN][entry.entry_id].get("unsub_event")
    if unsub:
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


def _setup_event_listener(hass: HomeAssistant, coordinator: NimlyCoordinator):
    """Listen for zha_event from this lock and update activity sensor."""

    @callback
    def _handle_zha_event(event: Event) -> None:
        """Handle ZHA event from the lock."""
        data = event.data
        device_ieee = data.get("device_ieee", "")

        if device_ieee.lower() != coordinator.ieee.lower():
            return

        command = data.get("command")
        args = data.get("args", {})

        _LOGGER.debug("ZHA event from %s: command=%s args=%s", device_ieee, command, args)

        # Parse operation_event_notification
        if command == "operation_event_notification":
            source_raw = args.get("operation_event_source", 0)
            operation = args.get("operation_event_code", 0)
            user_id = args.get("userid", None)

            # Map source
            source_map = {0: SOURCE_KEYPAD, 1: SOURCE_RF, 2: SOURCE_MANUAL}
            source = source_map.get(source_raw, SOURCE_UNKNOWN)

            # Map action (odd = unlock, even = lock)
            if operation in (1, 3, 5, 7, 9, 11):
                action = ACTION_UNLOCK
            elif operation in (0, 2, 4, 6, 8, 10):
                action = ACTION_LOCK
            else:
                action = ACTION_UNKNOWN

            # Auto-lock has no user
            if source_raw == 3 or operation == 11:
                source = SOURCE_AUTO
                user_id = None

            coordinator.update_activity(user_id, action, source)

            # Fire HA event for automations
            hass.bus.async_fire(
                "nimly_pro_lock_activity",
                {
                    "ieee": coordinator.ieee,
                    "user_slot": user_id,
                    "user_name": coordinator.get_slot_name(user_id)
                    if user_id is not None
                    else None,
                    "action": action,
                    "source": source,
                },
            )

    return hass.bus.async_listen("zha_event", _handle_zha_event)
