"""The ZHA transport against real Home Assistant registries and config entries.

tests/ runs the auto-wake against fake registries that only replay what
zha.py expects of them. Here the lock's ZHA device and entities are real
device and entity registry entries, created the way ZHA registers them, so
the lookup is checked against Home Assistant's own API in both pinned
releases. The capability tests do the same for the entry options and the
background task that a delivered command schedules.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN
from custom_components.onesti_lock.zha import ZhaLockTransport
from tests_ha.conftest import LOCK_IEEE, FakeDoorLockCluster, make_lock_proxy

OTHER_IEEE = "00:0d:6f:00:55:66:77:88"


def _register_zha_device(hass: HomeAssistant, zha_entry: MockConfigEntry, ieee: str, name: str) -> str:
    """A ZHA device with its lock and battery entities, as ZHA registers them."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        connections={(dr.CONNECTION_ZIGBEE, ieee)},
        identifiers={("zha", ieee)},
        name=name,
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor", "zha", f"{ieee}-1-1", device_id=device.id, config_entry=zha_entry, suggested_object_id=f"{name}_battery"
    )
    lock = registry.async_get_or_create(
        "lock", "zha", f"{ieee}-11-257", device_id=device.id, config_entry=zha_entry, suggested_object_id=name
    )
    return lock.entity_id


@pytest.fixture
def lock_entities(hass: HomeAssistant, mock_zha) -> dict[str, str]:
    """Two ZHA locks, ours and a neighbour's, in the real registries."""
    zha_entry = MockConfigEntry(domain="zha")
    zha_entry.add_to_hass(hass)
    return {
        LOCK_IEEE: _register_zha_device(hass, zha_entry, LOCK_IEEE, "front_door"),
        OTHER_IEEE: _register_zha_device(hass, zha_entry, OTHER_IEEE, "back_door"),
    }


@pytest.fixture
def lock_service_calls(hass: HomeAssistant) -> list[str]:
    """lock.lock as ZHA's lock platform would provide it; records entity ids."""
    calls: list[str] = []

    async def _lock(call: ServiceCall) -> None:
        # No schema on this stand-in, so entity_id arrives as the caller sent it.
        entity_ids = call.data["entity_id"]
        calls.extend([entity_ids] if isinstance(entity_ids, str) else entity_ids)

    hass.services.async_register("lock", "lock", _lock)
    return calls


def _scripted_zha_command(hass: HomeAssistant, effects: list[BaseException | None]) -> list[dict]:
    """ZHA's cluster command service; each call consumes one effect."""
    calls: list[dict] = []

    async def _issue(call: ServiceCall) -> None:
        calls.append(dict(call.data))
        effect = effects.pop(0) if effects else None
        if effect is not None:
            raise effect

    hass.services.async_register("zha", "issue_zigbee_cluster_command", _issue)
    return calls


async def test_timeout_wakes_our_lock_through_the_registries(
    hass: HomeAssistant, lock_entities, lock_service_calls
) -> None:
    commands = _scripted_zha_command(hass, [TimeoutError(), None])
    transport = ZhaLockTransport(hass, LOCK_IEEE)

    assert await transport.send(0x0007, {"user_id": 5}) is True

    assert lock_service_calls == [lock_entities[LOCK_IEEE]]
    assert len(commands) == 2
    assert transport.wake_echo_pending() is True


async def test_uppercase_ieee_in_the_entry_still_finds_the_lock(
    hass: HomeAssistant, lock_entities, lock_service_calls
) -> None:
    _scripted_zha_command(hass, [TimeoutError(), None])
    transport = ZhaLockTransport(hass, LOCK_IEEE.upper())

    await transport.wake()

    assert lock_service_calls == [lock_entities[LOCK_IEEE]]


async def test_disabled_lock_entity_is_not_actuated(hass: HomeAssistant, lock_entities, lock_service_calls) -> None:
    er.async_get(hass).async_update_entity(
        lock_entities[LOCK_IEEE], disabled_by=er.RegistryEntryDisabler.USER
    )
    transport = ZhaLockTransport(hass, LOCK_IEEE)

    await transport.wake()

    assert lock_service_calls == []
    assert transport.wake_echo_pending() is False


async def test_endpoint_is_read_from_the_cluster(hass: HomeAssistant, mock_zha) -> None:
    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(cluster=FakeDoorLockCluster(endpoint_id=1))}
    commands = _scripted_zha_command(hass, [])

    assert await ZhaLockTransport(hass, LOCK_IEEE).send(0x0007, {"user_id": 5}) is True

    assert commands[0]["endpoint_id"] == 1


# -- Capabilities --


def _sleeping_cluster(mock_zha) -> FakeDoorLockCluster:
    """The lock's cluster, answering no read until the test wakes it."""
    cluster = mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11].in_clusters[0x0101]
    answer = cluster.read_attributes

    async def asleep(attributes):
        raise TimeoutError

    cluster.read_attributes = asleep
    cluster.wake = lambda: setattr(cluster, "read_attributes", answer)
    return cluster


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=LOCK_IEEE,
        data={CONF_IEEE: LOCK_IEEE},
        options={"slots": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_capabilities_missed_at_startup_arrive_after_a_command(
    hass: HomeAssistant, mock_zha, zha_commands
) -> None:
    cluster = _sleeping_cluster(mock_zha)
    entry = await _setup_entry(hass)
    coordinator = entry.runtime_data
    assert coordinator.lock_capabilities == {}
    assert "capabilities" not in entry.options

    cluster.wake()
    assert await coordinator.clear_pin(5) is True
    await hass.async_block_till_done(wait_background_tasks=True)

    expected = {"num_pin_users": 50, "max_pin_length": 8, "min_pin_length": 4}
    assert coordinator.lock_capabilities == expected
    assert entry.options["capabilities"] == expected

    # A reload starts from the stored answer and does not ask again.
    reads: list = []

    async def counting_read(attributes):
        reads.append(attributes)
        return {}, {}

    cluster.read_attributes = counting_read
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.lock_capabilities == expected
    assert reads == []


async def test_capabilities_missed_at_startup_arrive_after_a_report(hass: HomeAssistant, mock_zha) -> None:
    cluster = _sleeping_cluster(mock_zha)
    entry = await _setup_entry(hass)

    cluster.wake()
    event = SimpleNamespace(attribute_id=0x0000, raw_value=1)
    for listener in list(cluster._event_listeners["attribute_report"]):
        listener(event)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.runtime_data.lock_capabilities["num_pin_users"] == 50
