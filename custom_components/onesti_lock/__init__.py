"""Onesti Lock: PIN management and activity tracking for Onesti/Nimly locks."""
from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from . import pin_rules
from .const import DEFAULT_SLOT, DOMAIN, ZHA_DOMAIN
from .coordinator import NimlyConfigEntry, NimlyCoordinator
from .events import ZhaInternalsMissing, register_event_listener
from .localize import async_get_strings
from .zha import is_zha_loaded

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ISSUE_ZHA_INTERNALS = "zha_internals"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once for all locks."""
    from .services import async_setup_services
    await async_setup_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: NimlyConfigEntry) -> bool:
    """Bring a stored entry up to the current config flow version.

    2.1 -> 2.2: stored slots lose has_rfid, a field nothing ever set.
    """
    if entry.version > 2:
        # Written by a newer release; this one cannot know its shape.
        return False

    if entry.minor_version < 2:
        slots = entry.options.get("slots", {})
        options = {
            **entry.options,
            "slots": {
                key: {f: slot[f] for f in DEFAULT_SLOT if f in slot}
                for key, slot in slots.items()
            },
        }
        hass.config_entries.async_update_entry(
            entry, options=options, version=2, minor_version=2
        )
        _LOGGER.debug("Migrated %s to version 2.2", entry.entry_id)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: NimlyConfigEntry) -> bool:
    """Set up Onesti Lock from a config entry."""
    coordinator = NimlyCoordinator(hass, entry)
    coordinator.strings = await async_get_strings(hass, hass.config.language)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _start_event_listener(hass, entry, coordinator)
    _watch_zha_entries(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Read lock capabilities in the background, tied to the entry so an
    # unload cancels a read still waiting on a sleeping lock. A no-op once
    # the lock has answered, since the answer is kept in the entry options.
    coordinator.schedule_capability_refresh()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: NimlyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _zha_issue_id(entry: NimlyConfigEntry) -> str:
    return f"{ISSUE_ZHA_INTERNALS}_{entry.entry_id}"


@callback
def _start_event_listener(
    hass: HomeAssistant, entry: NimlyConfigEntry, coordinator: NimlyCoordinator
) -> None:
    """Register the lock event listener, or raise a repair issue saying why not.

    Without the listener the integration still sets PINs but never sees who
    unlocked, so the failure is an error and a repair issue, not a debug line.
    """
    issue_id = _zha_issue_id(entry)
    try:
        unsub = register_event_listener(hass, coordinator)
    except ZhaInternalsMissing as err:
        detail = err.detail if is_zha_loaded(hass) else "ZHA gateway (get_zha_gateway_proxy)"
        _LOGGER.error(
            "Lock events for %s cannot be received, ZHA internals missing: %s. "
            "Report the Home Assistant version in an issue if ZHA itself is running",
            coordinator.ieee,
            detail,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_ZHA_INTERNALS,
            translation_placeholders={"detail": detail},
        )
    else:
        entry.async_on_unload(unsub)
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    # An unloaded entry listens to nothing, so it has nothing to report.
    entry.async_on_unload(lambda: ir.async_delete_issue(hass, DOMAIN, issue_id))


@callback
def _watch_zha_entries(
    hass: HomeAssistant, entry: NimlyConfigEntry, coordinator: NimlyCoordinator
) -> None:
    """Reload when ZHA comes back with a different Door Lock cluster.

    A ZHA reload or re-pair builds new zigpy objects. The listener would
    stay on the old cluster and lock events would stop arriving without a
    word, so a ZHA entry reaching LOADED with another cluster (or with one
    where there was none) reloads this entry onto it.
    """

    @callback
    def _on_zha_state_change(zha_entry) -> None:
        if zha_entry.state is not ConfigEntryState.LOADED:
            return
        if entry.state is not ConfigEntryState.LOADED:
            return
        cluster = coordinator.transport.cluster()
        if cluster is coordinator.listened_cluster:
            return
        _LOGGER.info(
            "ZHA was loaded again with a new Door Lock cluster for %s, reloading",
            coordinator.ieee,
        )
        hass.config_entries.async_schedule_reload(entry.entry_id)

    for zha_entry in hass.config_entries.async_entries(ZHA_DOMAIN):
        entry.async_on_unload(
            zha_entry.async_on_state_change(
                lambda zha_entry=zha_entry: _on_zha_state_change(zha_entry)
            )
        )


async def _async_options_updated(hass: HomeAssistant, entry: NimlyConfigEntry) -> None:
    """Reload only when the first user slot changed.

    The coordinator writes slot data and capabilities to the same options,
    and each write calls this listener. Reloading on every options change
    would reload after every PIN operation.
    """
    if pin_rules.first_user_slot(entry.options) != entry.runtime_data.setup_first_user_slot:
        hass.config_entries.async_schedule_reload(entry.entry_id)
