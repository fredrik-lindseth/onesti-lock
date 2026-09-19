"""Onesti Lock: PIN management and activity tracking for Onesti/Nimly locks."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import NimlyCoordinator
from .events import register_event_listener
from .localize import async_get_strings

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Onesti Lock from a config entry."""
    coordinator = NimlyCoordinator(hass, entry)
    coordinator.strings = await async_get_strings(hass, hass.config.language)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    from .services import async_setup_services
    await async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register event listener on the DoorLock cluster
    unsub = register_event_listener(hass, coordinator)
    if unsub:
        hass.data[DOMAIN][entry.entry_id]["unsub_listener"] = unsub

    # Read lock capabilities in the background. The lock may be sleeping and
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
