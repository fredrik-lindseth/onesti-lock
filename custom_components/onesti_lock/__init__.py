"""Onesti Lock: PIN management and activity tracking for Onesti/Nimly locks."""
from __future__ import annotations

import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import NimlyConfigEntry, NimlyCoordinator
from .events import register_event_listener
from .localize import async_get_strings

PLATFORMS = ["sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once for all locks."""
    from .services import async_setup_services
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NimlyConfigEntry) -> bool:
    """Set up Onesti Lock from a config entry."""
    coordinator = NimlyCoordinator(hass, entry)
    coordinator.strings = await async_get_strings(hass, hass.config.language)
    entry.runtime_data = coordinator

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
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
