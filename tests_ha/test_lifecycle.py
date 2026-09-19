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

from custom_components.onesti_lock.const import CONF_IEEE, CONF_RESERVED_SLOTS, DOMAIN
from custom_components.onesti_lock.events import ATTR_OPERATION_EVENT
from tests_ha.conftest import DOORLOCK_CLUSTER_ID, LOCK_IEEE, FakeDoorLockCluster, make_lock_proxy

ACTIVITY_ENTITY_ID = "sensor.onesti_lock_last_activity"

# attrid 0x0100 payloads: source byte, action byte, user slot (uint16).
KARI_UNLOCKS_WITH_CODE = 0x02020005  # keypad, unlock, slot 5
ZIGBEE_LOCK = 0x00010000  # zigbee, lock, no user


def _entry(**kwargs) -> MockConfigEntry:
    defaults = {
        "domain": DOMAIN,
        "version": 2,
        "minor_version": 2,
        "unique_id": LOCK_IEEE,
        "title": "Onesti Lock (11:22:33:44)",
        "data": {CONF_IEEE: LOCK_IEEE},
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


class ClusterWithoutOnEvent:
    """A Door Lock cluster from a zigpy that dropped on_event."""

    endpoint = SimpleNamespace(endpoint_id=11)

    async def read_attributes(self, attributes):
        return {}, {}


def _without_on_event(mock_zha) -> None:
    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=ClusterWithoutOnEvent())}


async def _retry_setup(hass: HomeAssistant) -> None:
    """Move time past Home Assistant's longest setup retry backoff."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    await hass.async_block_till_done(wait_background_tasks=True)


async def _report(hass: HomeAssistant, cluster: FakeDoorLockCluster, raw_value: int) -> None:
    """Deliver an operation event the way zigpy's cluster.emit() does."""
    event = SimpleNamespace(attribute_id=ATTR_OPERATION_EVENT, raw_value=raw_value)
    for listener in list(cluster._event_listeners["attribute_report"]):
        listener(event)
    await hass.async_block_till_done()


# -- Migration --


async def test_migration_strips_has_rfid_and_bumps_minor(hass: HomeAssistant, mock_zha) -> None:
    entry = _entry(
        minor_version=1,
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
    assert (entry.version, entry.minor_version) == (2, 2)
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


async def test_entry_from_a_newer_major_version_is_refused(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup(hass, _entry(version=3, minor_version=1))

    assert entry.state is ConfigEntryState.MIGRATION_ERROR


# -- Repair issue for missing ZHA internals --


async def test_listener_registered_leaves_no_issue(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert _zha_issue(hass, entry) is None


async def test_missing_on_event_raises_a_repair_issue(
    hass: HomeAssistant, mock_zha, caplog: pytest.LogCaptureFixture
) -> None:
    _without_on_event(mock_zha)

    entry = await _setup(hass)

    # PIN management still works without events, so the entry loads.
    assert entry.state is ConfigEntryState.LOADED
    issue = _zha_issue(hass, entry)
    assert issue is not None
    assert issue.translation_key == "zha_internals"
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert issue.translation_placeholders == {"detail": "ClusterWithoutOnEvent.on_event"}
    assert "ClusterWithoutOnEvent.on_event" in caplog.text
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
    assert len(_cluster(mock_zha)._event_listeners["attribute_report"]) == 1
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
    assert any(
        r.levelname == "INFO" and "ZHA is not loaded yet" in r.getMessage()
        for r in caplog.records
    )


async def test_loaded_zha_without_gateway_names_the_gateway(hass: HomeAssistant, zha_dependency) -> None:
    MockConfigEntry(domain="zha", state=ConfigEntryState.LOADED).add_to_hass(hass)
    hass.data["zha"] = SimpleNamespace(gateway_proxy=None)

    entry = await _setup(hass)

    issue = _zha_issue(hass, entry)
    assert issue is not None
    assert issue.translation_placeholders["detail"].startswith("ZHA gateway")


async def test_unload_removes_the_issue(hass: HomeAssistant, mock_zha) -> None:
    _without_on_event(mock_zha)
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
    assert len(old_cluster._event_listeners["attribute_report"]) == 1

    new_cluster = FakeDoorLockCluster()
    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=new_cluster)}
    await _reload_zha(hass, zha_entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not first_coordinator
    assert entry.runtime_data.listened_cluster is new_cluster
    assert old_cluster._event_listeners["attribute_report"] == []
    assert len(new_cluster._event_listeners["attribute_report"]) == 1


async def test_zha_reload_with_same_cluster_does_not_reload(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data

    await _reload_zha(hass, zha_entry)

    assert entry.runtime_data is coordinator
    assert len(_cluster(mock_zha)._event_listeners["attribute_report"]) == 1


async def test_zha_coming_back_with_on_event_clears_the_issue(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    lock_proxy = mock_zha.device_proxies[LOCK_IEEE]
    _without_on_event(mock_zha)
    entry = await _setup(hass)
    assert _zha_issue(hass, entry) is not None

    mock_zha.device_proxies = {LOCK_IEEE: lock_proxy}
    await _reload_zha(hass, zha_entry)

    assert entry.state is ConfigEntryState.LOADED
    assert _zha_issue(hass, entry) is None
    assert len(_cluster(mock_zha)._event_listeners["attribute_report"]) == 1


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
    assert len(cluster._event_listeners["attribute_report"]) == 1
    assert entry.runtime_data.capabilities_final
    assert _zha_issue(hass, entry) is None
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_zha_reloaded_without_the_lock_retries_setup(
    hass: HomeAssistant, mock_zha, zha_entry: MockConfigEntry
) -> None:
    """The lock is removed from ZHA while we listen: the watch reloads us into
    SETUP_RETRY, and the retry sets it up again once the lock is re-paired."""
    entry = await _setup(hass)
    lock_proxy = mock_zha.device_proxies.pop(LOCK_IEEE)

    await _reload_zha(hass, zha_entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _zha_issue(hass, entry) is None

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
