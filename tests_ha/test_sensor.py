"""Slot and activity sensors against a real Home Assistant.

The entry is set up through the real config entry machinery, with ZHA
mocked at the gateway proxy (see conftest.py). The coordinator, the
ZhaLockTransport and the event listener are the integration's own code.
Lock events enter the way zigpy delivers them: as attribute_report events
on the fake Door Lock cluster.

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN, NUM_USER_SLOTS, SLOT_FIRST_USER
from custom_components.onesti_lock.events import ATTR_OPERATION_EVENT
from tests_ha.conftest import DOORLOCK_CLUSTER_ID, LOCK_IEEE

USER_SLOTS = range(SLOT_FIRST_USER, SLOT_FIRST_USER + NUM_USER_SLOTS)

# attrid 0x0100 payloads: source byte, action byte, user slot (uint16).
KARI_UNLOCKS_WITH_CODE = 0x02020005  # keypad, unlock, slot 5
AUTO_LOCK = 0x0A010000  # auto, lock, no user


async def _setup_entry(hass: HomeAssistant, slots: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=LOCK_IEEE,
        title="Onesti Lock (11:22:33:44)",
        data={CONF_IEEE: LOCK_IEEE},
        options={"slots": slots or {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _coordinator(hass: HomeAssistant, entry: MockConfigEntry):
    return entry.runtime_data


def _cluster(mock_zha):
    return mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11].in_clusters[DOORLOCK_CLUSTER_ID]


def _entity_id(hass: HomeAssistant, unique_suffix: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{LOCK_IEEE}-{unique_suffix}")
    assert entity_id is not None, f"no sensor with unique_id suffix {unique_suffix!r}"
    return entity_id


async def _report(hass: HomeAssistant, mock_zha, attribute_id: int, raw_value) -> None:
    """Deliver an attribute report the way zigpy's cluster.emit() does."""
    event = SimpleNamespace(attribute_id=attribute_id, raw_value=raw_value)
    for listener in list(_cluster(mock_zha)._event_listeners["attribute_report"]):
        listener(event)
    await hass.async_block_till_done()


# -- Platform --


async def test_platform_creates_eleven_entities(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)

    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    by_unique_id = {e.unique_id: e.entity_id for e in entries}

    expected = {f"{LOCK_IEEE}-slot-{slot}": f"sensor.onesti_lock_slot_{slot}" for slot in USER_SLOTS}
    expected[f"{LOCK_IEEE}-activity"] = "sensor.onesti_lock_last_activity"
    assert len(entries) == 11
    assert by_unique_id == expected
    for entity_id in expected.values():
        assert hass.states.get(entity_id) is not None


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

    assert len(coordinator._listeners) == NUM_USER_SLOTS

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


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "Kari unlocked with code"), ("nb", "Kari låste opp med kode")],
)
async def test_decoded_event_sets_activity_state(
    hass: HomeAssistant, mock_zha, language: str, expected: str
) -> None:
    hass.config.language = language
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})

    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)

    state = hass.states.get(_entity_id(hass, "activity"))
    assert state.state == expected
    assert state.attributes["user_name"] == "Kari"
    assert state.attributes["user_slot"] == 5
    assert state.attributes["action"] == "unlock"
    assert state.attributes["source"] == "keypad"


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


async def test_activity_attributes_include_lock_capabilities(hass: HomeAssistant, mock_zha) -> None:
    # Setup reads the capabilities in the background from the fake cluster
    # (0x0012=50, 0x0017=8, 0x0018=4); the next state write carries them.
    entry = await _setup_entry(hass)
    assert _coordinator(hass, entry).lock_capabilities == {
        "num_pin_users": 50,
        "max_pin_length": 8,
        "min_pin_length": 4,
    }

    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KARI_UNLOCKS_WITH_CODE)

    attributes = hass.states.get(_entity_id(hass, "activity")).attributes
    assert attributes["num_pin_users"] == 50
    assert attributes["max_pin_length"] == 8
    assert attributes["min_pin_length"] == 4
    assert attributes["action"] == "unlock"


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
