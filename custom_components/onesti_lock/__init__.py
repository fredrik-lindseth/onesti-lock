"""Onesti Lock: PIN management and activity tracking for Onesti/Nimly locks."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import NimlyConfigEntry, NimlyCoordinator
from .events import register_event_listener
from .localize import async_get_strings

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: NimlyConfigEntry) -> bool:
    """Set up Onesti Lock from a config entry."""
    coordinator = NimlyCoordinator(hass, entry)
    coordinator.strings = await async_get_strings(hass, hass.config.language)
    entry.runtime_data = coordinator

    from .services import async_setup_services
    await async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register event listener on the DoorLock cluster
    unsub = register_event_listener(hass, coordinator)
    if unsub:
        entry.async_on_unload(unsub)

    # Read lock capabilities in the background. The lock may be sleeping and
    # we don't want to block setup on a slow/missing response
    hass.async_create_task(coordinator.read_lock_capabilities())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: NimlyConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # The entry being unloaded is excluded by id: HA 2024.12 still reports it
    # as LOADED here, newer releases as UNLOAD_IN_PROGRESS.
    others = [
        other
        for other in hass.config_entries.async_loaded_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ]
    if not others:
        from .services import async_unload_services
        await async_unload_services(hass)

    return True
