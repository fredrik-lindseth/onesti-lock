"""Onesti Lock: PIN management and activity tracking for Onesti/Nimly locks."""
from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    SOURCE_INTEGRATION_DISCOVERY,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType

from . import pin_rules
from .const import CONF_IEEE, CONF_MODEL, DEFAULT_SLOT, DOMAIN, ZHA_DOMAIN
from .coordinator import OnestiConfigEntry, OnestiCoordinator
from .events import ZhaInternalsMissing, register_event_listener
from .localize import async_get_strings
from .zha import is_zha_loaded, iter_device_proxies, iter_onesti_locks, model_in_zha

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ISSUE_ZHA_INTERNALS = "zha_internals"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services and the discovery watch once for all locks."""
    from .services import async_setup_services
    await async_setup_services(hass)
    _watch_for_undiscovered_locks(hass)
    return True


@callback
def _watch_for_undiscovered_locks(hass: HomeAssistant) -> None:
    """Offer every Onesti lock in ZHA that no config entry owns.

    Registered in async_setup, so it lives for the whole Home Assistant run
    like the services do. Home Assistant never loads a custom integration
    without a config entry, so the first lock has to be added by hand; from
    then on this is what makes lock number two show up under Discovered.

    Two things start a look: a device registry entry from ZHA (a newly
    paired device, or one that gained its Door Lock cluster after the
    interview finished), and a ZHA entry reaching LOADED (ZHA starting
    after us, or coming back from a reload with devices we have not seen).
    Both only say "something changed in ZHA"; the list itself comes from
    the gateway either way.
    """

    @callback
    def _zha_entry_ids() -> set[str]:
        return {entry.entry_id for entry in hass.config_entries.async_entries(ZHA_DOMAIN)}

    @callback
    def _on_device_registry_updated(event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        if event.data["action"] not in ("create", "update"):
            return
        device = dr.async_get(hass).async_get(event.data["device_id"])
        # A child device (HA 2026.9 and up) has no connections of its own,
        # and a lock is never one.
        if not isinstance(device, dr.DeviceEntry):
            return
        if not any(conn[0] == dr.CONNECTION_ZIGBEE for conn in device.connections):
            return
        if device.config_entries.isdisjoint(_zha_entry_ids()):
            return
        _async_discover_locks(hass)

    @callback
    def _on_zha_state_change(zha_entry: ConfigEntry) -> None:
        if zha_entry.state is ConfigEntryState.LOADED:
            _async_discover_locks(hass)

    @callback
    def _watch(zha_entry: ConfigEntry) -> None:
        zha_entry.async_on_state_change(lambda: _on_zha_state_change(zha_entry))

    @callback
    def _on_config_entry_changed(change: ConfigEntryChange, changed: ConfigEntry) -> None:
        if change is ConfigEntryChange.ADDED and changed.domain == ZHA_DOMAIN:
            _watch(changed)

    for zha_entry in hass.config_entries.async_entries(ZHA_DOMAIN):
        _watch(zha_entry)
    async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _on_config_entry_changed)
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _on_device_registry_updated)


@callback
def _async_discover_locks(hass: HomeAssistant) -> None:
    """Start a discovery flow for every Onesti lock without an entry.

    A lock that already has an entry, or that the user pressed Ignore on,
    is stopped by the unique id in async_step_integration_discovery, and so
    is a second flow for a lock already being asked about. The check here
    only keeps the common case from making a flow at all.

    The unique id counts as known next to the stored address, because an
    ignored entry has no data at all. Without it every device registry
    event from ZHA, for any device, started and aborted a flow per
    ignored lock.
    """
    known = {
        address.lower()
        for entry in hass.config_entries.async_entries(DOMAIN)
        for address in (str(entry.data.get(CONF_IEEE, "")), str(entry.unique_id or ""))
        if address
    }
    for ieee, model in iter_onesti_locks(hass):
        if ieee.lower() in known:
            continue
        _LOGGER.debug("Onesti lock %s in ZHA has no config entry, offering it", ieee)
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_IEEE: ieee, CONF_MODEL: model},
            )
        )


def _migrate_to_entry_id_keys(hass: HomeAssistant, entry: OnestiConfigEntry) -> None:
    """Rewrite registry keys from the IEEE address to the config entry id.

    Up to 2.2 the device identifier and every entity unique id held the
    lock's IEEE address, which made a replaced Connect Module a different
    lock: new device, new entities, and the user's names, areas and
    dashboards left behind. Keyed on the entry id instead, the reconfigure
    flow can point the same entry at a new address and keep all of it.

    Both registries are rewritten in place, so entity ids, user-set names
    and everything else Home Assistant stores per entity survive.

    Called from setup rather than from the version step, so what drives it
    is the state of the registries and not the stored version. A config
    entry is written to disk a second after it changes; the registries use
    the long delay during startup, which is three minutes, and a migration
    runs during startup. An entry saved at 2.3 whose registry write never
    landed would otherwise keep IEEE-keyed rows that nothing ever looks at
    again. It is also what repairs a rollback to a release that keyed on
    the address: that one registers the old keys a second time, and the
    next load of this release folds them back in.

    Only our own identifier is swapped, never the whole set. Through HA
    2026.8 a zigbee connection is unique across config entries, so this
    device and ZHA's can be one registry entry holding both identifiers.
    Replacing the set would drop ("zha", ieee), and ZHA looks its device
    up by exactly that in device triggers, device actions, logbook and
    its own diagnostics.

    The IEEE is matched without regard to case, as services.py does: the
    address is stored as the user's Zigbee stack spelled it.
    """
    ieee: str = entry.data[CONF_IEEE]
    prefix = f"{ieee.lower()}-"
    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    # The entry-id key is looked for in the entry's own devices rather than
    # through async_get_device, which searched every config entry and is
    # deprecated from HA 2026.9 with a warning telling the user to file a
    # bug against us. Its replacement, async_get_device_by_identifier, does
    # not exist on the minimum HA, and the list is already at hand.
    owner = next((d for d in devices if (DOMAIN, entry.entry_id) in d.identifiers), None)
    for device in devices:
        stale = {
            identifier
            for identifier in device.identifiers
            if identifier[0] == DOMAIN and identifier[1].lower() == ieee.lower()
        }
        if not stale:
            continue
        if owner is not None and owner.id != device.id:
            # A rollback re-registered the old key as a second device. The
            # entry-id one is the user's own row, with their name, area and
            # entity ids, so the duplicate is what goes. Dropping our entry
            # from it removes the row entirely unless ZHA shares it.
            _LOGGER.debug("Removing the duplicate device %s of %s", device.id, entry.entry_id)
            device_registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
            continue
        updated = device_registry.async_update_device(
            device.id,
            new_identifiers=(device.identifiers - stale) | {(DOMAIN, entry.entry_id)},
        )
        if owner is None:
            owner = updated
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if not registry_entry.unique_id.lower().startswith(prefix):
            continue
        unique_id = f"{entry.entry_id}-{registry_entry.unique_id[len(prefix):]}"
        if entity_registry.async_get_entity_id(
            registry_entry.domain, registry_entry.platform, unique_id
        ):
            # Taken: a rollback, or a registry restored from a backup
            # newer than the config entries. Rewriting onto it raises, and
            # the exception would take the whole setup with it, so the
            # stale row goes instead and the user keeps their entity id.
            _LOGGER.debug("Removing the duplicate entity %s", registry_entry.entity_id)
            entity_registry.async_remove(registry_entry.entity_id)
            continue
        entity_registry.async_update_entity(registry_entry.entity_id, new_unique_id=unique_id)


async def async_migrate_entry(hass: HomeAssistant, entry: OnestiConfigEntry) -> bool:
    """Bring a stored entry up to the current config flow version.

    2.1 -> 2.2: stored slots lose has_rfid, a field nothing ever set.
    2.2 -> 2.3: entry.data gains the model string. The registry keys move
    from the IEEE address to the entry id as well, but that half is done
    by _migrate_to_entry_id_keys() from setup, on every load, because a
    registry write outlives this bump by up to three minutes. See its
    docstring.
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

    if entry.minor_version < 3:
        # ZHA may not be up yet, and an empty model is no worse than what
        # 2.2 had. The reconfigure flow fills it in when it is.
        data = {
            **entry.data,
            CONF_MODEL: entry.data.get(CONF_MODEL) or model_in_zha(hass, entry.data[CONF_IEEE]),
        }
        hass.config_entries.async_update_entry(
            entry, data=data, version=2, minor_version=3
        )
        _LOGGER.debug("Migrated %s to version 2.3", entry.entry_id)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: OnestiConfigEntry) -> bool:
    """Set up Onesti Lock from a config entry.

    Raises ConfigEntryNotReady when ZHA is running without this lock, so
    Home Assistant retries with backoff until the lock is back in ZHA.
    """
    ieee: str = entry.data[CONF_IEEE]
    # Before anything registers an entity, and on every load: the rewrite
    # is driven by what the registries hold, not by the stored version.
    _migrate_to_entry_id_keys(hass, entry)
    if is_zha_loaded(hass) and not _lock_in_zha(hass, ieee):
        # Removed from ZHA, or replaced by a Connect Module with a new
        # IEEE. Nothing in ZHA is broken, so this is not a repair issue.
        # Raised before the platforms are forwarded, as HA requires.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="lock_not_in_zha",
            translation_placeholders={"ieee": ieee},
        )

    if not entry.data.get(CONF_MODEL) and (model := model_in_zha(hass, ieee)):
        # The 2.3 migration reads the model off ZHA, but it runs whenever
        # the entry loads, and ZHA can still be in SETUP_RETRY behind a
        # slow Zigbee stick. Nothing else fills it in short of a
        # reconfigure the user has no reason to run, so the device would
        # stay "Onesti Lock (3344)" for good. Written to data rather than
        # options, and before the update listener is registered.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_MODEL: model}
        )

    coordinator = OnestiCoordinator(hass, entry)
    coordinator.strings = await async_get_strings(hass, hass.config.language)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _watch_zha_entries(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    if not is_zha_loaded(hass) and not _zha_entry_loaded(hass):
        # ZHA is still starting, usually in SETUP_RETRY because the
        # coordinator stick came up late. Nothing is wrong yet: the ZHA
        # watch reloads this entry once ZHA is LOADED, and that setup
        # registers the listener and reads the capabilities. Until then no
        # lock event can arrive, which the entities and one log line say.
        coordinator.set_available(False)
        return True

    _start_event_listener(hass, entry, coordinator)

    # Read lock capabilities in the background, tied to the entry so an
    # unload cancels a read still waiting on a sleeping lock. A no-op once
    # the lock has answered, since the answer is kept in the entry options.
    coordinator.schedule_capability_refresh()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnestiConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _lock_in_zha(hass: HomeAssistant, ieee: str) -> bool:
    """Whether ZHA knows a device with this IEEE, cluster or not.

    A device without the Door Lock cluster still counts: that is ZHA's
    object layout changing under us, which the repair issue reports.
    """
    return any(str(dev_ieee).lower() == ieee.lower() for dev_ieee, _ in iter_device_proxies(hass))


def _zha_entry_loaded(hass: HomeAssistant) -> bool:
    return any(
        zha_entry.state is ConfigEntryState.LOADED
        for zha_entry in hass.config_entries.async_entries(ZHA_DOMAIN)
    )


def _zha_issue_id(entry: OnestiConfigEntry) -> str:
    return f"{ISSUE_ZHA_INTERNALS}_{entry.entry_id}"


@callback
def _start_event_listener(
    hass: HomeAssistant, entry: OnestiConfigEntry, coordinator: OnestiCoordinator
) -> None:
    """Register the lock event listener, or raise a repair issue saying why not.

    Only called while ZHA is running and, when its gateway answers, lists
    the lock, so a missing piece here means ZHA's internals changed.
    Without the listener the integration still sets PINs but never sees
    who unlocked, so the failure is an error and a repair issue, not a
    debug line.
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
        # The coordinator starts available when ZHA is up, so that the
        # entities do not blink through unavailable on the way. ZHA is up
        # and the listener still did not register, so that guess was
        # wrong. quiet because the ERROR above names the missing piece,
        # and the INFO line would claim ZHA is not running.
        coordinator.set_available(False, quiet=True)
    else:
        entry.async_on_unload(unsub)
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    # An unloaded entry listens to nothing, so it has nothing to report.
    entry.async_on_unload(lambda: ir.async_delete_issue(hass, DOMAIN, issue_id))


@callback
def _watch_zha_entries(
    hass: HomeAssistant, entry: OnestiConfigEntry, coordinator: OnestiCoordinator
) -> None:
    """Reload when ZHA comes up with a Door Lock cluster we do not listen to.

    A ZHA reload or re-pair builds new zigpy objects. The listener would
    stay on the old cluster and lock events would stop arriving without a
    word, so a ZHA entry reaching LOADED with another cluster reloads this
    entry onto it. So does ZHA reaching LOADED while nothing is listened to
    (ZHA was still starting, or its internals were missing), and that setup
    registers the listener, raises the repair issue, or goes into
    SETUP_RETRY when the lock is not among ZHA's devices.

    A lock missing from ZHA never reaches this watch: that setup raised
    ConfigEntryNotReady before it, and Home Assistant's own retry picks the
    lock up once ZHA lists it again.

    ZHA entries added while this entry is loaded are watched too, so a ZHA
    that is removed and added again is still followed.

    The watch is also where the entities learn that they are unavailable:
    while no ZHA entry is loaded, no lock event can arrive, and the
    coordinator says so until a listener is registered again.
    """

    @callback
    def _on_zha_state_change(zha_entry: ConfigEntry) -> None:
        if entry.state is not ConfigEntryState.LOADED:
            return
        if zha_entry.state is not ConfigEntryState.LOADED:
            if not _zha_entry_loaded(hass):
                # ZHA stopped under a loaded entry. The listener is still on
                # a cluster of objects ZHA is tearing down, so no lock event
                # can arrive until ZHA is back.
                coordinator.set_available(False)
            return
        if coordinator.listened_cluster is not None:
            # quiet: a lock missing from ZHA here ends in the reload below,
            # which raises ConfigEntryNotReady and is retried. Nothing is
            # broken, so the lookup must not log an error on the way.
            if coordinator.transport.cluster(quiet=True) is coordinator.listened_cluster:
                # The same objects came back, so the listener still fits
                # and a reload would only throw the entities away.
                coordinator.set_available(True)
                return
            _LOGGER.debug(
                "ZHA was loaded again with a new Door Lock cluster for %s, reloading",
                coordinator.ieee,
            )
        hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def _watch(zha_entry: ConfigEntry) -> None:
        entry.async_on_unload(
            zha_entry.async_on_state_change(lambda: _on_zha_state_change(zha_entry))
        )

    @callback
    def _on_config_entry_changed(change: ConfigEntryChange, changed: ConfigEntry) -> None:
        if change is ConfigEntryChange.ADDED and changed.domain == ZHA_DOMAIN:
            _watch(changed)

    for zha_entry in hass.config_entries.async_entries(ZHA_DOMAIN):
        _watch(zha_entry)
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _on_config_entry_changed)
    )


async def _async_options_updated(hass: HomeAssistant, entry: OnestiConfigEntry) -> None:
    """Reload only when the first user slot changed.

    The coordinator writes slot data and capabilities to the same options,
    and each write calls this listener. Reloading on every options change
    would reload after every PIN operation.
    """
    if pin_rules.first_user_slot(entry.options) != entry.runtime_data.setup_first_user_slot:
        hass.config_entries.async_schedule_reload(entry.entry_id)
