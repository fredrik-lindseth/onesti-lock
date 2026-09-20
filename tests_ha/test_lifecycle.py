"""Entry lifecycle against real Home Assistant.

Migration, the setup retry for a lock missing from ZHA, the repair issue
for missing ZHA internals, the reload when ZHA comes back with new zigpy
objects, the options update listener, the startup capability read and the
wake echo through the real event listener. All of it runs through Home Assistant's own config entry machinery, issue registry
and service registry, with ZHA mocked at the gateway proxy (see conftest.py).

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.onesti_lock.const import (
    CONF_IEEE,
    CONF_MODEL,
    CONF_RESERVED_SLOTS,
    DOMAIN,
)
from custom_components.onesti_lock.entity import HAS_VIA_DEVICE_ID
from custom_components.onesti_lock.events import ATTR_OPERATION_EVENT
from tests_ha.conftest import (
    DEVICE_SLUG,
    DOORLOCK_CLUSTER_ID,
    LISTENER_PATHS,
    LOCK_IEEE,
    LOCK_MODEL,
    FakeDoorLockCluster,
    make_lock_proxy,
)

ACTIVITY_ENTITY_ID = f"sensor.{DEVICE_SLUG}_last_activity"

# attrid 0x0100 payloads: source byte, action byte, user slot (uint16).
KARI_UNLOCKS_WITH_CODE = 0x02020005  # keypad, unlock, slot 5
ZIGBEE_LOCK = 0x00010000  # zigbee, lock, no user


def _entry(**kwargs) -> MockConfigEntry:
    defaults = {
        "domain": DOMAIN,
        "version": 2,
        "minor_version": 3,
        "unique_id": LOCK_IEEE,
        "title": "Onesti Lock (11:22:33:44)",
        "data": {CONF_IEEE: LOCK_IEEE, CONF_MODEL: LOCK_MODEL},
        "options": {"slots": {}},
    }
    return MockConfigEntry(**{**defaults, **kwargs})


async def _setup(hass: HomeAssistant, entry: MockConfigEntry | None = None) -> MockConfigEntry:
    entry = entry or _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _cluster(mock_zha) -> FakeDoorLockCluster:
    return mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11].in_clusters[DOORLOCK_CLUSTER_ID]


def _zha_issue(hass: HomeAssistant, entry: MockConfigEntry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"zha_internals_{entry.entry_id}")


class ClusterWithoutAnyHook:
    """A Door Lock cluster from a zigpy with neither listener hook.

    No zigpy release looks like this: 0.80.1 has add_listener without
    on_event, 0.91 and newer have both. It stands for a future one that
    drops them, which is the only case still worth a repair issue.
    """

    endpoint = SimpleNamespace(endpoint_id=11)

    async def read_attributes(self, attributes):
        return {}, {}


def _without_any_hook(mock_zha) -> None:
    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=ClusterWithoutAnyHook())}


async def _retry_setup(hass: HomeAssistant) -> None:
    """Move time past Home Assistant's longest setup retry backoff."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    await hass.async_block_till_done(wait_background_tasks=True)


def _info_lines(caplog: pytest.LogCaptureFixture, text: str) -> int:
    """How many INFO lines of ours hold this text."""
    return len(
        [
            record
            for record in caplog.records
            if record.levelname == "INFO"
            and record.name.startswith("custom_components.onesti_lock")
            and text in record.getMessage()
        ]
    )


def _loss_lines(caplog: pytest.LogCaptureFixture) -> int:
    return _info_lines(caplog, "stopped, ZHA is not running")


def _return_lines(caplog: pytest.LogCaptureFixture) -> int:
    return _info_lines(caplog, "arriving again, ZHA is running")


async def _report(hass: HomeAssistant, cluster: FakeDoorLockCluster, raw_value: int) -> None:
    """Deliver an operation event the way the installed zigpy does."""
    cluster.deliver(ATTR_OPERATION_EVENT, raw_value)
    await hass.async_block_till_done()


# -- Migration --


async def test_migration_strips_has_rfid_and_bumps_minor(hass: HomeAssistant, mock_zha) -> None:
    entry = _entry(
        minor_version=1,
        data={CONF_IEEE: LOCK_IEEE},
        options={
            "slots": {
                "4": {"name": "Ola", "has_pin": False, "has_rfid": True},
                "5": {"name": "Kari", "has_pin": True, "has_rfid": False},
            },
            CONF_RESERVED_SLOTS: 2,
        },
    )

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert (entry.version, entry.minor_version) == (2, 3)
    assert entry.options["slots"] == {
        "4": {"name": "Ola", "has_pin": False},
        "5": {"name": "Kari", "has_pin": True},
    }
    # Everything outside the slots is left alone.
    assert entry.options[CONF_RESERVED_SLOTS] == 2


async def test_current_entry_is_not_rewritten(hass: HomeAssistant, mock_zha) -> None:
    options = {"slots": {"5": {"name": "Kari", "has_pin": True}}}
    entry = await _setup(hass, _entry(options=options))

    assert entry.state is ConfigEntryState.LOADED
    assert entry.options["slots"] == options["slots"]


async def test_migration_to_entry_id_keys_keeps_the_entities(
    hass: HomeAssistant, mock_zha
) -> None:
    """2.2 -> 2.3: the registry keys move, the user's entities do not.

    A 2.2 install has the device and every entity keyed on the IEEE
    address. The migration rewrites both keys in place, so the entity ids
    people put in dashboards and automations, and the names they typed,
    are the same afterwards.

    The device is the one a 2.2 install really has: through HA 2026.8 a
    zigbee connection is unique across config entries, so ours and ZHA's
    are a single registry entry carrying ("zha", ieee) as well. ZHA finds
    its device by that identifier, so the migration must leave it alone.
    """
    entry = _entry(minor_version=2, data={CONF_IEEE: LOCK_IEEE})
    entry.add_to_hass(hass)
    zha_entry = MockConfigEntry(domain="zha", title="ZHA")
    zha_entry.add_to_hass(hass)
    registry_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        identifiers={("zha", LOCK_IEEE)},
        connections={(dr.CONNECTION_ZIGBEE, LOCK_IEEE)},
        name="Onesti Products AS NimlyPRO",
    )
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, LOCK_IEEE)},
        connections={(dr.CONNECTION_ZIGBEE, LOCK_IEEE)},
        name="Onesti Lock",
    )
    # From 2026.9 the connection is unique per config entry and the two
    # stay apart, so how many identifiers our device carries is up to the
    # Home Assistant under test. Whatever it has, the migration may only
    # swap ours.
    identifiers_before = device.identifiers
    if device.id == registry_device.id:
        assert ("zha", LOCK_IEEE) in identifiers_before
    registry = er.async_get(hass)
    activity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{LOCK_IEEE}-activity",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="onesti_lock_last_activity",
    )
    registry.async_update_entity(activity.entity_id, name="Front door activity")
    slot = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{LOCK_IEEE}-slot-5",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="onesti_lock_slot_5",
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert (entry.version, entry.minor_version) == (2, 3)
    # The model is read off ZHA, so the device has it without a reconfigure.
    assert entry.data[CONF_MODEL] == LOCK_MODEL
    assert dr.async_get(hass).async_get(device.id).identifiers == (
        identifiers_before - {(DOMAIN, LOCK_IEEE)}
    ) | {(DOMAIN, entry.entry_id)}

    migrated = registry.async_get(activity.entity_id)
    assert migrated is not None, "the activity sensor kept its entity id"
    assert migrated.unique_id == f"{entry.entry_id}-activity"
    assert migrated.name == "Front door activity"
    assert registry.async_get(slot.entity_id).unique_id == f"{entry.entry_id}-slot-5"


async def test_migration_leaves_a_model_that_is_already_stored(
    hass: HomeAssistant, mock_zha
) -> None:
    """ZHA is not asked again for a model the entry already has."""
    mock_zha.device_proxies[LOCK_IEEE] = make_lock_proxy(model="NimlyTwist")
    entry = _entry(minor_version=2, data={CONF_IEEE: LOCK_IEEE, CONF_MODEL: "NimlyCodePRO"})

    await _setup(hass, entry)

    assert entry.data[CONF_MODEL] == "NimlyCodePRO"


async def test_migration_without_zha_leaves_the_model_empty(
    hass: HomeAssistant, zha_dependency
) -> None:
    """A model nobody can read is no worse than the 2.2 entry had."""
    entry = _entry(minor_version=2, data={CONF_IEEE: LOCK_IEEE})

    await _setup(hass, entry)

    assert (entry.version, entry.minor_version) == (2, 3)
    assert entry.data[CONF_MODEL] == ""


async def test_the_model_is_filled_in_once_zha_answers(
    hass: HomeAssistant, zha_dependency
) -> None:
    """The migration can run before ZHA is up, and then nothing else fills it.

    A slow Zigbee stick puts ZHA in SETUP_RETRY at the first start after
    the upgrade, so the migration finds no model. Setup reads it the next
    time the entry loads, rather than leaving the device named after its
    address until the user runs a reconfigure nothing asks for.
    """
    entry = await _setup(hass, _entry(minor_version=2, data={CONF_IEEE: LOCK_IEEE}))
    assert entry.data[CONF_MODEL] == ""

    hass.data["zha"] = SimpleNamespace(
        gateway_proxy=SimpleNamespace(device_proxies={LOCK_IEEE: make_lock_proxy()})
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.data[CONF_MODEL] == LOCK_MODEL
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [device.name for device in devices] == ["NimlyPRO (3344)"]


def _ieee_keyed_rows(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    object_id_prefix: str = "onesti_lock",
) -> tuple[str, dict[str, str]]:
    """The device and entities a release keyed on the IEEE address leaves.

    Returns the device id and the entity ids by key, so a test can show
    the user's own entity ids either surviving or being the ones kept.
    """
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, LOCK_IEEE)},
        name="Onesti Lock",
    )
    registry = er.async_get(hass)
    entity_ids = {}
    for key in ("activity", "slot-5"):
        entity_ids[key] = registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{LOCK_IEEE}-{key}",
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=f"{object_id_prefix}_{key.replace('-', '_')}",
        ).entity_id
    return device.id, entity_ids


async def test_an_interrupted_migration_is_finished_on_the_next_start(
    hass: HomeAssistant, mock_zha
) -> None:
    """The version bump lands on disk long before the registry write.

    A config entry is saved a second after it changes; the registries use
    the 180 second delay during startup, which is when a migration runs.
    A restart inside that window leaves an entry that says 2.3 next to
    registry rows still keyed on the address. The rewrite therefore runs
    on every setup, off the registries rather than off the version, and
    this test is that state: 2.3 stored, IEEE-keyed rows on disk.

    Both HA targets prove this one: no device of ZHA's is involved, so
    nothing here depends on how the registry treats a connection.
    """
    entry = _entry(minor_version=3)
    entry.add_to_hass(hass)
    device_id, entity_ids = _ieee_keyed_rows(hass, entry)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    registry = er.async_get(hass)
    assert dr.async_get(hass).async_get(device_id).identifiers == {(DOMAIN, entry.entry_id)}
    assert registry.async_get(entity_ids["activity"]).unique_id == f"{entry.entry_id}-activity"
    assert registry.async_get(entity_ids["slot-5"]).unique_id == f"{entry.entry_id}-slot-5"


async def test_an_ieee_stored_in_another_case_is_still_rewritten(
    hass: HomeAssistant, mock_zha
) -> None:
    """The stored address is spelled the way the Zigbee stack spelled it."""
    entry = _entry(minor_version=3, data={CONF_IEEE: LOCK_IEEE.upper(), CONF_MODEL: LOCK_MODEL})
    entry.add_to_hass(hass)
    device_id, entity_ids = _ieee_keyed_rows(hass, entry)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert dr.async_get(hass).async_get(device_id).identifiers == {(DOMAIN, entry.entry_id)}
    assert (
        er.async_get(hass).async_get(entity_ids["activity"]).unique_id
        == f"{entry.entry_id}-activity"
    )


async def test_a_rollback_duplicate_is_folded_back_in(
    hass: HomeAssistant, mock_zha, caplog: pytest.LogCaptureFixture
) -> None:
    """Downgrading and upgrading again leaves one set of entities, the user's.

    A release keyed on the address does not know about 2.3 and registers
    the old keys a second time, so the user ends up with two devices and
    two of every entity, the new ones suffixed. Loading this release again
    rewrites what it can and drops what the entry-id rows already hold, so
    the entity ids in dashboards and automations are the ones that stay.

    Both HA targets prove this one: the two device rows are built here
    without a connection, so neither registry merges them.
    """
    entry = _entry(minor_version=3)
    entry.add_to_hass(hass)
    kept_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="NimlyPRO (3344)",
    )
    registry = er.async_get(hass)
    kept = {
        key: registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}-{key}",
            config_entry=entry,
            device_id=kept_device.id,
            suggested_object_id=f"{DEVICE_SLUG}_{key.replace('-', '_')}",
        ).entity_id
        for key in ("activity", "slot-5")
    }
    registry.async_update_entity(kept["activity"], name="Front door activity")
    duplicate_device, duplicates = _ieee_keyed_rows(hass, entry, object_id_prefix=DEVICE_SLUG)
    assert duplicates["activity"] != kept["activity"], "the rollback's entity id is suffixed"

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert dr.async_get(hass).async_get(duplicate_device) is None
    assert registry.async_get(duplicates["activity"]) is None
    assert registry.async_get(duplicates["slot-5"]) is None
    survivor = registry.async_get(kept["activity"])
    assert survivor is not None and survivor.name == "Front door activity"
    assert registry.async_get(kept["slot-5"]) is not None
    assert [device.id for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)] == [
        kept_device.id
    ]
    # This is the only path that looks the entry-id device up, so it is where
    # a deprecated registry lookup would show. From HA 2026.9 such a call
    # warns through homeassistant.helpers.frame, names this integration and
    # asks the user to file a bug, and the warning reaches everyone who
    # upgrades. On the minimum HA nothing reports, and the assert is free.
    deprecated = [r for r in caplog.records if "is deprecated" in r.message and DOMAIN in r.message]
    assert not deprecated, [r.message for r in deprecated]


async def test_a_leftover_entity_row_does_not_kill_the_entry(
    hass: HomeAssistant, mock_zha
) -> None:
    """A mixed registry: the new unique id is taken and the old one is still there.

    A registry restored from a backup newer than core.config_entries has
    both. Rewriting the old row onto the taken id raises ValueError, and
    the exception would take the setup down with it, leaving the lock dead
    until the user deletes the entry. The stale row goes instead.

    Both HA targets prove this one: nothing here depends on the registry's
    connection rules.
    """
    entry = _entry(minor_version=3)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="NimlyPRO (3344)",
    )
    registry = er.async_get(hass)
    kept = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}-activity",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id=f"{DEVICE_SLUG}_last_activity",
    ).entity_id
    leftover = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{LOCK_IEEE}-activity",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id=f"{DEVICE_SLUG}_last_activity",
    ).entity_id

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert registry.async_get(leftover) is None
    assert registry.async_get(kept).unique_id == f"{entry.entry_id}-activity"


async def test_the_device_is_never_folded_into_zhas_row(hass: HomeAssistant, mock_zha) -> None:
    """ZHA deletes its registry row whole, so ours must not be part of it.

    Through HA 2026.8 a zigbee connection is unique across config entries
    and the registry merges any device that carries one into ZHA's, which
    ZHA removes when the lock leaves the network. The minimum target is
    what proves that half: there the device must stand alone. From 2026.9
    a connection is unique per entry, so the current target proves the
    other half, the device carrying the connection and hanging off ZHA's.
    """
    zha_entry = MockConfigEntry(domain="zha", title="ZHA")
    zha_entry.add_to_hass(hass)
    zha_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        identifiers={("zha", LOCK_IEEE)},
        connections={(dr.CONNECTION_ZIGBEE, LOCK_IEEE)},
        name="front_door",
    )

    entry = await _setup(hass)

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.id != zha_device.id
    assert device.config_entries == {entry.entry_id}
    assert device.identifiers == {(DOMAIN, entry.entry_id)}
    if HAS_VIA_DEVICE_ID:
        assert device.via_device_id == zha_device.id
        assert (dr.CONNECTION_ZIGBEE, LOCK_IEEE) in device.connections
    else:
        # A connection here is what would have merged the two rows.
        assert device.connections == set()


async def test_entry_from_a_newer_major_version_is_refused(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup(hass, _entry(version=3, minor_version=1))

    assert entry.state is ConfigEntryState.MIGRATION_ERROR


# -- Repair issue for missing ZHA internals --


@pytest.mark.parametrize("cluster_class", LISTENER_PATHS, indirect=True)
async def test_listener_registered_leaves_no_issue(hass: HomeAssistant, mock_zha) -> None:
    """Either hook is enough: no repair issue, and someone is listening."""
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert _zha_issue(hass, entry) is None
    assert _cluster(mock_zha).listener_count == 1


async def test_no_listener_hook_at_all_raises_a_repair_issue(
    hass: HomeAssistant, mock_zha, caplog: pytest.LogCaptureFixture
) -> None:
    _without_any_hook(mock_zha)

    entry = await _setup(hass)

    # PIN management still works without events, so the entry loads.
    assert entry.state is ConfigEntryState.LOADED
    issue = _zha_issue(hass, entry)
    assert issue is not None
    assert issue.translation_key == "zha_internals"
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    detail = issue.translation_placeholders["detail"]
    assert "ClusterWithoutAnyHook.on_event" in detail
    assert "add_listener" in detail
    assert detail in caplog.text
    assert any(r.levelname == "ERROR" and "ZHA internals missing" in r.message for r in caplog.records)


async def test_missing_door_lock_cluster_raises_a_repair_issue(hass: HomeAssistant, mock_zha) -> None:
    """ZHA lists the lock, but the chain walk finds no Door Lock cluster."""
    lock_proxy = make_lock_proxy()
    lock_proxy.device.device.endpoints[11].in_clusters.clear()
    mock_zha.device_proxies = {LOCK_IEEE: lock_proxy}

    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    issue = _zha_issue(hass, entry)
    assert issue is not None
    assert LOCK_IEEE in issue.translation_placeholders["detail"]


# -- Lock missing from a running ZHA --


async def test_lock_missing_from_zha_retries_setup(
    hass: HomeAssistant, mock_zha, caplog: pytest.LogCaptureFixture
) -> None:
    """A lock removed from ZHA is not a ZHA fault: retry, no repair issue."""
    mock_zha.device_proxies = {}

    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _zha_issue(hass, entry) is None
    assert not ir.async_get(hass).issues
    # The translated message is what Settings shows as the reason.
    assert entry.reason is not None
    assert LOCK_IEEE in entry.reason
    assert "not among ZHA's devices" in entry.reason
    assert not [
        r for r in caplog.records if r.levelname == "ERROR" and r.name.startswith("custom_components.onesti_lock")
    ]


async def test_lock_back_in_zha_is_set_up_on_retry(hass: HomeAssistant, mock_zha) -> None:
    lock_proxy = mock_zha.device_proxies.pop(LOCK_IEEE)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY

    mock_zha.device_proxies[LOCK_IEEE] = lock_proxy
    await _retry_setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.listened_cluster is _cluster(mock_zha)
    assert _cluster(mock_zha).listener_count == 1
    assert _zha_issue(hass, entry) is None


async def test_lock_ieee_is_matched_without_regard_to_case(hass: HomeAssistant, mock_zha) -> None:
    mock_zha.device_proxies = {LOCK_IEEE.upper(): mock_zha.device_proxies[LOCK_IEEE]}

    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED


async def test_retry_message_renders_in_every_language(hass: HomeAssistant, mock_zha) -> None:
    from homeassistant.helpers.translation import async_get_translations

    for language in ("en", "nb", "sv", "da"):
        strings = await async_get_translations(hass, language, "exceptions", [DOMAIN])
        message = strings.get(f"component.{DOMAIN}.exceptions.lock_not_in_zha.message")
        assert message, language
        assert "{ieee}" in message, language


async def test_zha_not_loaded_yet_is_not_an_internals_issue(
    hass: HomeAssistant, zha_dependency, caplog: pytest.LogCaptureFixture
) -> None:
    """ZHA still starting (no gateway, entry not LOADED) is normal, not broken."""
    MockConfigEntry(domain="zha", state=ConfigEntryState.SETUP_RETRY).add_to_hass(hass)
    hass.data["zha"] = SimpleNamespace(gateway_proxy=None)

    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert _zha_issue(hass, entry) is None
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    assert _loss_lines(caplog) == 1
    assert _return_lines(caplog) == 0
    assert entry.runtime_data.available is False


async def test_loaded_zha_without_gateway_names_the_gateway(hass: HomeAssistant, zha_dependency) -> None:
    MockConfigEntry(domain="zha", state=ConfigEntryState.LOADED).add_to_hass(hass)
    hass.data["zha"] = SimpleNamespace(gateway_proxy=None)

    entry = await _setup(hass)

    issue = _zha_issue(hass, entry)
    assert issue is not None
    assert issue.translation_placeholders["detail"].startswith("ZHA gateway")


async def test_unload_removes_the_issue(hass: HomeAssistant, mock_zha) -> None:
    _without_any_hook(mock_zha)
    entry = await _setup(hass)
    assert _zha_issue(hass, entry) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert _zha_issue(hass, entry) is None


async def test_issue_translation_renders_in_every_language(hass: HomeAssistant, mock_zha) -> None:
    from homeassistant.helpers.translation import async_get_translations

    for language in ("en", "nb", "sv", "da"):
        strings = await async_get_translations(hass, language, "issues", [DOMAIN])
        title = strings.get(f"component.{DOMAIN}.issues.zha_internals.title")
        description = strings.get(f"component.{DOMAIN}.issues.zha_internals.description")
        assert title, language
        assert "{detail}" in description, language


# -- Reload when ZHA is reloaded --


@pytest.fixture
def zha_entry(hass: HomeAssistant, mock_zha) -> MockConfigEntry:
    """ZHA's own config entry, loaded. ZHA itself cannot run here, so tests
    move it between states with mock_state, as a reload would."""
    entry = MockConfigEntry(domain="zha", state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    return entry


async def _reload_zha(hass: HomeAssistant, zha_entry: MockConfigEntry) -> None:
    zha_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    await hass.async_block_till_done()
    zha_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()


async def test_zha_reload_with_new_cluster_moves_the_listener(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    old_cluster = _cluster(mock_zha)
    entry = await _setup(hass)
    first_coordinator = entry.runtime_data
    assert old_cluster.listener_count == 1

    new_cluster = FakeDoorLockCluster()
    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=new_cluster)}
    await _reload_zha(hass, zha_entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not first_coordinator
    assert entry.runtime_data.listened_cluster is new_cluster
    assert old_cluster.listener_count == 0
    assert new_cluster.listener_count == 1


async def test_zha_reload_with_same_cluster_does_not_reload(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data

    await _reload_zha(hass, zha_entry)

    assert entry.runtime_data is coordinator
    assert _cluster(mock_zha).listener_count == 1


async def test_zha_coming_back_with_a_listener_hook_clears_the_issue(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    lock_proxy = mock_zha.device_proxies[LOCK_IEEE]
    _without_any_hook(mock_zha)
    entry = await _setup(hass)
    assert _zha_issue(hass, entry) is not None

    mock_zha.device_proxies = {LOCK_IEEE: lock_proxy}
    await _reload_zha(hass, zha_entry)

    assert entry.state is ConfigEntryState.LOADED
    assert _zha_issue(hass, entry) is None
    assert _cluster(mock_zha).listener_count == 1


async def test_zha_in_setup_retry_then_loaded_starts_the_listener(
    hass: HomeAssistant, zha_dependency, caplog: pytest.LogCaptureFixture
) -> None:
    """The coordinator stick comes up late: ZHA retries, we wait, then follow it."""
    zha_entry = MockConfigEntry(domain="zha", state=ConfigEntryState.SETUP_RETRY)
    zha_entry.add_to_hass(hass)
    hass.data["zha"] = SimpleNamespace(gateway_proxy=None)
    entry = await _setup(hass)
    assert entry.runtime_data.listened_cluster is None

    cluster = FakeDoorLockCluster()
    hass.data["zha"] = SimpleNamespace(
        gateway_proxy=SimpleNamespace(device_proxies={LOCK_IEEE: make_lock_proxy(cluster=cluster)})
    )
    zha_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.listened_cluster is cluster
    assert cluster.listener_count == 1
    assert entry.runtime_data.capabilities_final
    assert _zha_issue(hass, entry) is None
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_zha_reloaded_without_the_lock_retries_setup(
    hass: HomeAssistant,
    mock_zha,
    zha_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The lock is removed from ZHA while we listen: the watch reloads us into
    SETUP_RETRY, and the retry sets it up again once the lock is re-paired."""
    entry = await _setup(hass)
    lock_proxy = mock_zha.device_proxies.pop(LOCK_IEEE)

    caplog.clear()
    await _reload_zha(hass, zha_entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _zha_issue(hass, entry) is None
    # The watch looks the cluster up to see whether the one it listens to
    # is still the right one. Not finding it is the retried state above,
    # so the lookup must not log an error on the way there.
    assert not [
        r for r in caplog.records if r.levelname == "ERROR" and r.name.startswith("custom_components.onesti_lock")
    ]

    mock_zha.device_proxies[LOCK_IEEE] = lock_proxy
    await _retry_setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.listened_cluster is _cluster(mock_zha)


async def test_zha_starting_late_without_the_lock_retries_setup(
    hass: HomeAssistant, zha_dependency
) -> None:
    """We wait for a ZHA still starting; once it is up without the lock, the
    reload the watch schedules ends in SETUP_RETRY, not a repair issue."""
    zha_entry = MockConfigEntry(domain="zha", state=ConfigEntryState.SETUP_RETRY)
    zha_entry.add_to_hass(hass)
    hass.data["zha"] = SimpleNamespace(gateway_proxy=None)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    hass.data["zha"] = SimpleNamespace(gateway_proxy=SimpleNamespace(device_proxies={}))
    zha_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _zha_issue(hass, entry) is None


async def test_zha_added_again_with_a_new_entry_is_followed(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    entry = await _setup(hass)
    await hass.config_entries.async_remove(zha_entry.entry_id)
    await hass.async_block_till_done()

    new_cluster = FakeDoorLockCluster()
    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=new_cluster)}
    new_zha_entry = MockConfigEntry(domain="zha", state=ConfigEntryState.NOT_LOADED)
    # async_add, not add_to_hass, so HA announces the new entry the way a
    # user adding ZHA does. Its setup is skipped: ZHA itself cannot run here.
    with patch.object(hass.config_entries, "async_setup", AsyncMock(return_value=True)):
        await hass.config_entries.async_add(new_zha_entry)
    new_zha_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.listened_cluster is new_cluster


async def test_zha_state_listener_is_removed_on_unload(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=FakeDoorLockCluster())}
    await _reload_zha(hass, zha_entry)

    assert entry.state is ConfigEntryState.NOT_LOADED


# -- Availability --


async def test_the_activity_sensor_is_unavailable_while_zha_is_down(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    """The slot row keeps showing our own stored data: ZHA cannot make it stale."""
    entry = await _setup(hass)
    assert entry.runtime_data.available is True
    assert hass.states.get(ACTIVITY_ENTITY_ID).state != "unavailable"

    zha_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.available is False
    assert hass.states.get(ACTIVITY_ENTITY_ID).state == "unavailable"
    assert hass.states.get(f"sensor.{DEVICE_SLUG}_slot_5").state != "unavailable"

    new_cluster = FakeDoorLockCluster()
    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=new_cluster)}
    zha_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()

    assert entry.runtime_data.listened_cluster is new_cluster
    assert entry.runtime_data.available is True
    assert hass.states.get(ACTIVITY_ENTITY_ID).state != "unavailable"
    assert hass.states.get(f"sensor.{DEVICE_SLUG}_slot_5").state != "unavailable"


async def test_zha_back_with_the_same_objects_makes_the_entities_available(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    """Nothing was rebuilt, so there is nothing to reload; the listener fits."""
    entry = await _setup(hass)
    coordinator = entry.runtime_data

    await _reload_zha(hass, zha_entry)

    assert entry.runtime_data is coordinator
    assert coordinator.available is True
    assert hass.states.get(ACTIVITY_ENTITY_ID).state != "unavailable"


async def test_loss_and_return_are_logged_once_each_cycle(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    """Two cycles, two lines each, however many state changes ZHA makes."""
    entry = await _setup(hass)
    caplog.clear()

    for _ in range(2):
        zha_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
        await hass.async_block_till_done()
        # ZHA passes through more than one state on the way back up, and
        # only the first of them is worth a line.
        zha_entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
        await hass.async_block_till_done()
        mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=FakeDoorLockCluster())}
        zha_entry.mock_state(hass, ConfigEntryState.LOADED)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.available is True
    assert _loss_lines(caplog) == 2
    assert _return_lines(caplog) == 2


async def test_a_sleeping_lock_stays_available(
    hass: HomeAssistant, mock_zha, caplog: pytest.LogCaptureFixture
) -> None:
    """A command that never reaches the radio says nothing about events."""
    entry = await _setup(hass)
    cluster = _cluster(mock_zha)
    # Two: the send retries once after waking, and no ZHA lock entity is
    # registered here, so the wake only logs a warning.
    cluster.command_effects = [TimeoutError(), TimeoutError()]

    outcome = await entry.runtime_data.clear_pin(5)
    await hass.async_block_till_done()

    assert outcome.lock_answered is False
    assert entry.runtime_data.available is True
    assert hass.states.get(ACTIVITY_ENTITY_ID).state != "unavailable"
    assert _loss_lines(caplog) == 0


# -- Update listener --


async def test_changing_reserved_slots_reloads(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.setup_first_user_slot == 3

    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_RESERVED_SLOTS: 1})
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not coordinator
    assert entry.runtime_data.setup_first_user_slot == 1


async def test_slot_and_capability_writes_do_not_reload(hass: HomeAssistant, mock_zha, zha_commands) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data

    assert (await coordinator.set_pin(5, "Kari", "1234")).delivered
    await coordinator.set_slot_name(6, "Ola")
    assert (await coordinator.clear_pin(5)).delivered
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "capabilities": {"num_pin_users": 20}}
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.runtime_data is coordinator
    assert entry.options["slots"]["6"]["name"] == "Ola"


async def test_saving_the_same_reserved_slots_does_not_reload(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup(hass, _entry(options={"slots": {}, CONF_RESERVED_SLOTS: 2}))
    coordinator = entry.runtime_data

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_RESERVED_SLOTS: 2, "slots": {"7": {"name": "X", "has_pin": False}}}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data is coordinator


# -- Startup capability read --


async def test_startup_read_is_cancelled_on_unload(hass: HomeAssistant, mock_zha) -> None:
    cluster = _cluster(mock_zha)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hangs(attributes):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    cluster.read_attributes = hangs
    entry = await _setup(hass)
    assert started.is_set()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert cancelled.is_set()
    assert "capabilities" not in entry.options


# -- Wake echo through the real listener --


@pytest.fixture
def lock_entity(hass: HomeAssistant, mock_zha) -> str:
    """ZHA's lock entity for our lock, in the real registries."""
    zha_config = MockConfigEntry(domain="zha")
    zha_config.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_config.entry_id,
        connections={(dr.CONNECTION_ZIGBEE, LOCK_IEEE)},
        identifiers={("zha", LOCK_IEEE)},
        name="front_door",
    )
    return er.async_get(hass).async_get_or_create(
        "lock", "zha", f"{LOCK_IEEE}-11-257", device_id=device.id, config_entry=zha_config
    ).entity_id


@pytest.fixture
def sleeping_lock(hass: HomeAssistant, mock_zha, lock_entity: str) -> list[str]:
    """The lock's cluster answering the first command with a timeout, as a
    sleeping lock does, and a lock.lock service. Returns the woken entity ids."""
    _cluster(mock_zha).command_effects = [TimeoutError()]

    woken: list[str] = []

    async def _lock(call: ServiceCall) -> None:
        woken.append(call.data["entity_id"])

    hass.services.async_register("lock", "lock", _lock)
    return woken


async def test_wake_echo_leaves_activity_but_fires_the_event(
    hass: HomeAssistant, mock_zha, sleeping_lock: list[str]
) -> None:
    entry = await _setup(hass)
    cluster = _cluster(mock_zha)
    fired: list = []
    hass.bus.async_listen("onesti_lock_activity", fired.append)

    await _report(hass, cluster, KARI_UNLOCKS_WITH_CODE)
    before = hass.states.get(ACTIVITY_ENTITY_ID).state

    assert (await entry.runtime_data.set_pin(6, "Ola", "1234")).delivered
    assert len(sleeping_lock) == 1
    await _report(hass, cluster, ZIGBEE_LOCK)

    assert hass.states.get(ACTIVITY_ENTITY_ID).state == before
    assert [e.data["source"] for e in fired] == ["keypad", "zigbee"]
    assert fired[-1].data["action"] == "lock"


async def test_zigbee_lock_without_a_wake_updates_activity(hass: HomeAssistant, mock_zha) -> None:
    await _setup(hass)
    cluster = _cluster(mock_zha)

    await _report(hass, cluster, KARI_UNLOCKS_WITH_CODE)
    before = hass.states.get(ACTIVITY_ENTITY_ID).state
    await _report(hass, cluster, ZIGBEE_LOCK)

    assert hass.states.get(ACTIVITY_ENTITY_ID).state != before
