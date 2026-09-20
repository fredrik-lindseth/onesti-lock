"""Slot and activity sensors against a real Home Assistant.

The entry is set up through the real config entry machinery, with ZHA
mocked at the gateway proxy (see conftest.py). The coordinator, the
ZhaLockTransport and the event listener are the integration's own code.
Lock events enter the way zigpy delivers them: as attribute_report events
on the fake Door Lock cluster.

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_restore_state_shutdown_restart,
    mock_restore_cache_with_extra_data,
)

from custom_components.onesti_lock.const import (
    CONF_IEEE,
    CONF_RESERVED_SLOTS,
    DOMAIN,
    NUM_USER_SLOTS,
    SLOT_FIRST_USER,
)
from custom_components.onesti_lock.events import ATTR_OPERATION_EVENT
from tests_ha.conftest import DOORLOCK_CLUSTER_ID, LISTENER_PATHS, LOCK_IEEE

USER_SLOTS = range(SLOT_FIRST_USER, SLOT_FIRST_USER + NUM_USER_SLOTS)

# attrid 0x0100 payloads: source byte, action byte, user slot (uint16).
KARI_UNLOCKS_WITH_CODE = 0x02020005  # keypad, unlock, slot 5
AUTO_LOCK = 0x0A010000  # auto, lock, no user


def _add_entry(hass: HomeAssistant, slots: dict | None = None, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=LOCK_IEEE,
        title="Onesti Lock (11:22:33:44)",
        data={CONF_IEEE: LOCK_IEEE},
        options={"slots": slots or {}, **options},
    )
    entry.add_to_hass(hass)
    return entry


async def _setup_entry(hass: HomeAssistant, slots: dict | None = None, **options) -> MockConfigEntry:
    entry = _add_entry(hass, slots, **options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _coordinator(hass: HomeAssistant, entry: MockConfigEntry):
    return entry.runtime_data


def _cluster(mock_zha):
    return mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11].in_clusters[DOORLOCK_CLUSTER_ID]


def _enabled_entities(hass: HomeAssistant, entry: MockConfigEntry) -> list:
    """The registry entries that have a state, so the disabled ones are left out."""
    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    return [registry_entry for registry_entry in entries if not registry_entry.disabled]


def _entity_id(hass: HomeAssistant, unique_suffix: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{LOCK_IEEE}-{unique_suffix}")
    assert entity_id is not None, f"no sensor with unique_id suffix {unique_suffix!r}"
    return entity_id


async def _report(hass: HomeAssistant, mock_zha, attribute_id: int, raw_value) -> None:
    """Deliver an attribute report the way the installed zigpy does."""
    _cluster(mock_zha).deliver(attribute_id, raw_value)
    await hass.async_block_till_done()


# -- Platform --


async def test_platform_creates_eleven_enabled_entities(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)

    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    by_unique_id = {e.unique_id: e.entity_id for e in entries if not e.disabled}

    expected = {f"{LOCK_IEEE}-slot-{slot}": f"sensor.onesti_lock_slot_{slot}" for slot in USER_SLOTS}
    expected[f"{LOCK_IEEE}-activity"] = "sensor.onesti_lock_last_activity"
    assert by_unique_id == expected
    for entity_id in expected.values():
        assert hass.states.get(entity_id) is not None


async def test_every_sensor_sits_on_one_device(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)

    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    device_ids = {e.device_id for e in entries}
    assert len(device_ids) == 1

    device = dr.async_get(hass).async_get(device_ids.pop())
    assert device.identifiers == {(DOMAIN, LOCK_IEEE)}
    assert device.name == "Onesti Lock"
    assert device.manufacturer == "Onesti Products AS"


async def test_every_sensor_is_available_once_the_listener_is_registered(
    hass: HomeAssistant, mock_zha
) -> None:
    entry = await _setup_entry(hass)

    assert _coordinator(hass, entry).available is True
    for entity in _enabled_entities(hass, entry):
        assert hass.states.get(entity.entity_id).state != "unavailable", entity.entity_id


async def test_every_sensor_is_unavailable_without_a_listener(hass: HomeAssistant, mock_zha) -> None:
    """No listener means no lock event arrives, so nothing here is kept up to date."""
    entry = await _setup_entry(hass)
    coordinator = _coordinator(hass, entry)

    coordinator.set_available(False)
    await hass.async_block_till_done()

    for entity in _enabled_entities(hass, entry):
        assert hass.states.get(entity.entity_id).state == "unavailable", entity.entity_id

    coordinator.set_available(True)
    await hass.async_block_till_done()

    for entity in _enabled_entities(hass, entry):
        assert hass.states.get(entity.entity_id).state != "unavailable", entity.entity_id


# -- Slot sensors --


@pytest.mark.parametrize(("language", "vacant"), [("en", "Vacant"), ("nb", "Ledig")])
async def test_vacant_slot_sensor(hass: HomeAssistant, mock_zha, language: str, vacant: str) -> None:
    hass.config.language = language
    await _setup_entry(hass)

    state = hass.states.get(_entity_id(hass, "slot-4"))

    assert state.state == vacant
    assert state.attributes["slot_id"] == 4
    assert state.attributes["has_pin"] is False


async def test_named_slot_sensor_shows_name_and_pin(hass: HomeAssistant, mock_zha) -> None:
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})

    state = hass.states.get(_entity_id(hass, "slot-5"))

    assert state.state == "Kari"
    assert state.attributes["slot_id"] == 5
    assert state.attributes["has_pin"] is True


async def test_slot_listeners_registered_on_setup_and_removed_on_unload(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)
    coordinator = _coordinator(hass, entry)

    # One per slot sensor for the slot data, and one for the activity
    # sensor, which follows the coordinator for availability only.
    assert len(coordinator._listeners) == NUM_USER_SLOTS + 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert coordinator._listeners == []


# Slots that have never been used are not in storage. Each write below must
# create the slot instead of raising KeyError, and the sensor must follow.


async def test_naming_an_unused_slot_updates_its_sensor(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)

    await _coordinator(hass, entry).set_slot_name(6, "Ola")
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, "slot-6"))
    assert state.state == "Ola"
    assert state.attributes["has_pin"] is False
    assert entry.options["slots"]["6"]["name"] == "Ola"


async def test_set_pin_on_an_unused_slot_updates_its_sensor(hass: HomeAssistant, mock_zha, zha_commands) -> None:
    entry = await _setup_entry(hass)

    assert await _coordinator(hass, entry).set_pin(7, "Kari", "1234")
    await hass.async_block_till_done()

    assert [c["command"] for c in zha_commands] == [0x0005]
    state = hass.states.get(_entity_id(hass, "slot-7"))
    assert state.state == "Kari"
    assert state.attributes["has_pin"] is True
    assert entry.options["slots"]["7"]["has_pin"] is True


async def test_clear_pin_on_an_unused_slot_updates_its_sensor(hass: HomeAssistant, mock_zha, zha_commands) -> None:
    entry = await _setup_entry(hass)

    assert await _coordinator(hass, entry).clear_pin(8)
    await hass.async_block_till_done()

    assert [c["command"] for c in zha_commands] == [0x0007]
    state = hass.states.get(_entity_id(hass, "slot-8"))
    assert state.state == "Vacant"
    assert state.attributes["has_pin"] is False
    assert entry.options["slots"]["8"]["has_pin"] is False


# -- Activity sensor --


@pytest.mark.parametrize("cluster_class", LISTENER_PATHS, indirect=True)
@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "Kari unlocked with code"), ("nb", "Kari låste opp med kode")],
)
async def test_decoded_event_sets_activity_state(
    hass: HomeAssistant, mock_zha, language: str, expected: str
) -> None:
    """The end-to-end path, through both of zigpy's listener hooks."""
    hass.config.language = language
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})

    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)

    state = hass.states.get(_entity_id(hass, "activity"))
    assert state.state == expected
    assert state.attributes["user_name"] == "Kari"
    assert state.attributes["user_slot"] == 5
    assert state.attributes["action"] == "unlock"
    assert state.attributes["source"] == "keypad"


@pytest.mark.parametrize("cluster_class", LISTENER_PATHS, indirect=True)
async def test_auto_lock_does_not_overwrite_activity(hass: HomeAssistant, mock_zha) -> None:
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    fired = []
    hass.bus.async_listen("onesti_lock_activity", fired.append)

    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)
    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, AUTO_LOCK)

    assert hass.states.get(_entity_id(hass, "activity")).state == "Kari unlocked with code"
    assert [e.data["source"] for e in fired] == ["keypad", "auto"]


async def test_update_activity_writes_state(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)
    entity_id = _entity_id(hass, "activity")
    assert hass.states.get(entity_id).state == "unknown"

    _coordinator(hass, entry).update_activity(None, "lock", "zigbee")
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Locked via Zigbee"
    assert state.attributes["user_name"] is None
    assert state.attributes["user_slot"] is None


async def test_activity_attributes_are_only_the_event(hass: HomeAssistant, mock_zha) -> None:
    """What the lock reports about itself moved to its own sensors."""
    entry = await _setup_entry(hass)
    assert _coordinator(hass, entry).lock_capabilities == {
        "num_pin_users": 50,
        "max_pin_length": 8,
        "min_pin_length": 4,
    }

    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)

    attributes = hass.states.get(_entity_id(hass, "activity")).attributes
    assert attributes["action"] == "unlock"
    for key in ("num_pin_users", "max_pin_length", "min_pin_length"):
        assert key not in attributes


async def test_pin_report_never_reaches_activity_state(hass: HomeAssistant, mock_zha) -> None:
    """Attrid 0x0101 carries the PIN itself in BCD, and must be ignored."""
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)
    before = hass.states.get(_entity_id(hass, "activity"))

    await _report(hass, mock_zha, 0x0101, 0x04123456)

    after = hass.states.get(_entity_id(hass, "activity"))
    assert after.state == before.state
    assert dict(after.attributes) == dict(before.attributes)
    assert not any("pin_code" in key for key in after.attributes)
    assert not any("123456" in str(value) for value in after.attributes.values())


async def test_activity_timestamp_is_utc(hass: HomeAssistant, mock_zha) -> None:
    """Aware and in UTC, whatever zone the server runs in."""
    await hass.config.async_set_time_zone("Europe/Oslo")
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})

    before = datetime.now().astimezone()
    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)
    after = datetime.now().astimezone()

    timestamp = datetime.fromisoformat(hass.states.get(_entity_id(hass, "activity")).attributes["timestamp"])
    assert timestamp.utcoffset() == timedelta(0)
    assert before <= timestamp <= after


# -- Activity across restarts --

ACTIVITY_ENTITY_ID = "sensor.onesti_lock_last_activity"
STORED_ACTIVITY = {
    "user_name": "Kari",
    "user_slot": 5,
    "action": "unlock",
    "source": "keypad",
    "timestamp": "2026-09-19T15:04:05.123456+00:00",
}


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "Kari unlocked with code"), ("nb", "Kari låste opp med kode")],
)
async def test_activity_is_restored_from_the_raw_fields(
    hass: HomeAssistant, mock_zha, language: str, expected: str
) -> None:
    """The state is rebuilt in the current language, not copied from the cache."""
    # The entity was created while the server ran in English; the language
    # may have changed since.
    entry = _add_entry(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{LOCK_IEEE}-activity",
        config_entry=entry,
        suggested_object_id="onesti_lock_last_activity",
    )
    hass.config.language = language
    mock_restore_cache_with_extra_data(
        hass, [(State(ACTIVITY_ENTITY_ID, "Kari unlocked with code"), STORED_ACTIVITY)]
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ACTIVITY_ENTITY_ID)
    assert state.state == expected
    for key, value in STORED_ACTIVITY.items():
        assert state.attributes[key] == value


async def test_activity_survives_a_restart(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)
    before = hass.states.get(ACTIVITY_ENTITY_ID)

    # Dump the restore cache to storage and read it back, as a shutdown and
    # start would, then set the entry up again from scratch.
    await async_mock_restore_state_shutdown_restart(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    after = hass.states.get(ACTIVITY_ENTITY_ID)
    assert after.state == "Kari unlocked with code"
    assert after.attributes["timestamp"] == before.attributes["timestamp"]
    assert after.attributes["user_slot"] == 5


async def test_unusable_restore_data_leaves_the_sensor_unknown(hass: HomeAssistant, mock_zha) -> None:
    mock_restore_cache_with_extra_data(
        hass, [(State(ACTIVITY_ENTITY_ID, "whatever"), {"user_name": "Kari", "pin_code": "1234"})]
    )

    await _setup_entry(hass)

    state = hass.states.get(ACTIVITY_ENTITY_ID)
    assert state.state == "unknown"
    assert "pin_code" not in state.attributes


async def test_restored_data_is_filtered_to_known_fields(hass: HomeAssistant, mock_zha) -> None:
    mock_restore_cache_with_extra_data(
        hass, [(State(ACTIVITY_ENTITY_ID, "whatever"), {**STORED_ACTIVITY, "pin_code": "1234"})]
    )

    await _setup_entry(hass)

    assert "pin_code" not in hass.states.get(ACTIVITY_ENTITY_ID).attributes


# -- Activity sensor lifecycle --


async def test_activity_sensor_deregisters_on_unload(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)
    coordinator = _coordinator(hass, entry)
    assert coordinator._activity_sensor is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert coordinator._activity_sensor is None
    # An event arriving after the entities are gone reaches nothing.
    coordinator.update_activity(5, "unlock", "keypad")


async def test_activity_sensor_deregisters_when_its_entity_is_removed(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)
    coordinator = _coordinator(hass, entry)
    entity_id = _entity_id(hass, "activity")

    er.async_get(hass).async_remove(entity_id)
    await hass.async_block_till_done()

    assert coordinator._activity_sensor is None
    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)
    assert hass.states.get(entity_id) is None


# -- Slot row follows reserved_slots --


def _slot_unique_ids(hass: HomeAssistant, entry: MockConfigEntry) -> set[int]:
    prefix = f"{LOCK_IEEE}-slot-"
    return {
        int(e.unique_id.removeprefix(prefix))
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.unique_id.startswith(prefix)
    }


async def test_slot_row_starts_at_the_first_user_slot(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass, **{CONF_RESERVED_SLOTS: 1})

    assert _slot_unique_ids(hass, entry) == set(range(1, 1 + NUM_USER_SLOTS))
    assert hass.states.get(_entity_id(hass, "slot-1")).attributes["slot_id"] == 1


async def test_slot_sensors_outside_the_row_leave_the_registry(hass: HomeAssistant, mock_zha) -> None:
    """Moving from 3 reserved slots to 1 drops slots 11-12 and adds 1-2."""
    entry = await _setup_entry(hass)
    registry = er.async_get(hass)
    slot_3_entity_id = _entity_id(hass, "slot-3")
    slot_12_entity_id = _entity_id(hass, "slot-12")
    activity_entity_id = _entity_id(hass, "activity")

    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_RESERVED_SLOTS: 1})
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _slot_unique_ids(hass, entry) == set(range(1, 1 + NUM_USER_SLOTS))
    assert registry.async_get(slot_12_entity_id) is None
    assert hass.states.get(slot_12_entity_id) is None
    # A slot in both rows keeps its entity, and the activity sensor is untouched.
    assert _entity_id(hass, "slot-3") == slot_3_entity_id
    assert _entity_id(hass, "activity") == activity_entity_id


async def test_cleanup_only_touches_this_entrys_slot_sensors(hass: HomeAssistant, mock_zha) -> None:
    entry = _add_entry(hass, **{CONF_RESERVED_SLOTS: 1})
    registry = er.async_get(hass)
    stale = registry.async_get_or_create("sensor", DOMAIN, f"{LOCK_IEEE}-slot-12", config_entry=entry)
    other = registry.async_get_or_create("sensor", DOMAIN, "some-other-lock-slot-12")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None
    assert registry.async_get(other.entity_id) is not None


async def test_slot_attributes_have_no_has_rfid(hass: HomeAssistant, mock_zha) -> None:
    """RFID and fingerprint cannot be detected over Zigbee, so it is not shown."""
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True, "has_rfid": True}})

    attributes = hass.states.get(_entity_id(hass, "slot-5")).attributes

    assert "has_rfid" not in attributes
    assert attributes["has_pin"] is True


# -- Capability sensors --

# What the fake cluster reports (0x0012=50, 0x0017=8, 0x0018=4), by the
# unique_id suffix of the sensor that shows it.
CAPABILITY_SENSORS = {
    "pin-users": 50,
    "pin-length-min": 4,
    "pin-length-max": 8,
}


async def _enable_capability_sensors(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Turn the three sensors on the way a user does, and reload for them."""
    registry = er.async_get(hass)
    for suffix in CAPABILITY_SENSORS:
        registry.async_update_entity(_entity_id(hass, suffix), disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_capability_sensors_are_diagnostic_and_off_by_default(hass: HomeAssistant, mock_zha) -> None:
    """They describe the lock, not what it is doing, so they stay out of the way."""
    await _setup_entry(hass)
    registry = er.async_get(hass)

    for suffix in CAPABILITY_SENSORS:
        registry_entry = registry.async_get(_entity_id(hass, suffix))
        assert registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert registry_entry.entity_category is EntityCategory.DIAGNOSTIC
        assert hass.states.get(registry_entry.entity_id) is None


async def test_enabled_capability_sensors_show_what_the_lock_reported(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)

    await _enable_capability_sensors(hass, entry)

    for suffix, value in CAPABILITY_SENSORS.items():
        assert hass.states.get(_entity_id(hass, suffix)).state == str(value)


async def test_capability_sensors_have_no_value_until_the_lock_answers(hass: HomeAssistant, mock_zha) -> None:
    """The lock sleeps, so the first read usually goes unanswered."""
    cluster = _cluster(mock_zha)

    async def asleep(attributes):
        raise TimeoutError

    cluster.read_attributes = asleep
    entry = await _setup_entry(hass)
    await _enable_capability_sensors(hass, entry)

    assert _coordinator(hass, entry).lock_capabilities == {}
    for suffix in CAPABILITY_SENSORS:
        assert hass.states.get(_entity_id(hass, suffix)).state == "unknown"

    # A lock event means the radio is awake, so the read is tried again.
    del cluster.read_attributes
    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)

    for suffix, value in CAPABILITY_SENSORS.items():
        assert hass.states.get(_entity_id(hass, suffix)).state == str(value)
