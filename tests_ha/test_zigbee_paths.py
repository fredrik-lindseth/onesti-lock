"""What the lock reports, and what the integration makes of it.

Everything here goes in the way the radio delivers it: an attribute report
on the fake Door Lock cluster, or a capability read answered by it. The
decoder, the suppression rule and the PIN and slot rules run as the real
listener and the real options flow call them, not as direct function calls.

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, CONF_RESERVED_SLOTS, DOMAIN
from custom_components.onesti_lock.events import ATTR_OPERATION_EVENT
from tests_ha.conftest import LOCK_IEEE, lock_cluster

# attrid 0x0100 payloads: source byte, action byte, user slot (uint16).
KARI_UNLOCKS_WITH_CODE = 0x02020005  # keypad, unlock, slot 5
UNATTRIBUTED_UNLOCK = 0x05020000  # a person at the lock, on a NimlyCodePRO
UNATTRIBUTED_LOCK = 0x05010000  # that model's auto-relock, with no user


async def _setup_entry(hass: HomeAssistant, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=LOCK_IEEE,
        title="Onesti Lock (11:22:33:44)",
        data={CONF_IEEE: LOCK_IEEE},
        options={"slots": {}, **options},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _report(hass: HomeAssistant, mock_zha, raw_value: Any) -> None:
    lock_cluster(mock_zha).deliver(ATTR_OPERATION_EVENT, raw_value)
    await hass.async_block_till_done()


def _activity(hass: HomeAssistant) -> Any:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{LOCK_IEEE}-activity")
    assert entity_id is not None
    return hass.states.get(entity_id)


async def _pin_length_placeholders(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, str]:
    """{min} and {max} as the set_pin form shows them."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "set_pin"}
    )
    assert result["type"] is FlowResultType.FORM
    return result["description_placeholders"]


# -- Events the decoder has to make sense of --


async def test_unattributed_unlock_stays_on_the_activity_sensor(hass: HomeAssistant, mock_zha) -> None:
    """A NimlyCodePRO unlock is a person at the door, whoever it was.

    That model reports source 0x05 for everything, so the unlock carries no
    user. It is still someone opening the door and must stay visible.
    """
    await _setup_entry(hass)

    await _report(hass, mock_zha, UNATTRIBUTED_UNLOCK)

    state = _activity(hass)
    assert state.state == "Unlocked"
    assert state.attributes["source"] == "unattributed"
    assert state.attributes["user_slot"] is None


async def test_unattributed_lock_does_not_overwrite_the_activity_sensor(
    hass: HomeAssistant, mock_zha
) -> None:
    """On that model the auto-relock looks like this, so it is suppressed."""
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    fired: list[Any] = []
    hass.bus.async_listen("onesti_lock_activity", fired.append)

    await _report(hass, mock_zha, KARI_UNLOCKS_WITH_CODE)
    await _report(hass, mock_zha, UNATTRIBUTED_LOCK)

    assert _activity(hass).state == "Kari unlocked with code"
    # The event still goes out: an automation may want the relock.
    assert [e.data["source"] for e in fired] == ["keypad", "unattributed"]


async def test_report_wrapped_in_a_zigpy_type_is_read_through_value(
    hass: HomeAssistant, mock_zha
) -> None:
    """zigpy hands over its own types, not always a plain int."""
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})

    await _report(hass, mock_zha, SimpleNamespace(value=KARI_UNLOCKS_WITH_CODE))

    assert _activity(hass).state == "Kari unlocked with code"


async def test_unreadable_report_is_logged_and_dropped(
    hass: HomeAssistant, mock_zha, caplog: pytest.LogCaptureFixture
) -> None:
    """A payload that is neither a number nor wraps one leaves the sensor alone."""
    caplog.set_level(logging.WARNING, logger="custom_components.onesti_lock")
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    await _report(hass, mock_zha, KARI_UNLOCKS_WITH_CODE)

    await _report(hass, mock_zha, object())

    assert _activity(hass).state == "Kari unlocked with code"
    assert "Could not parse operation event" in caplog.text


async def test_report_outside_bitmap32_is_dropped(hass: HomeAssistant, mock_zha) -> None:
    """The attribute is a bitmap32; anything else is not an operation event."""
    await _setup_entry(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    fired: list[Any] = []
    hass.bus.async_listen("onesti_lock_activity", fired.append)
    await _report(hass, mock_zha, KARI_UNLOCKS_WITH_CODE)

    await _report(hass, mock_zha, -1)

    assert _activity(hass).state == "Kari unlocked with code"
    assert [e.data["source"] for e in fired] == ["keypad"]


# -- Reserved slots, as they can be stored --


@pytest.mark.parametrize(
    ("stored", "first_user_slot"),
    [
        pytest.param(1.0, 1, id="integral float"),
        pytest.param(True, 3, id="boolean"),
        pytest.param("2", 3, id="string"),
    ],
)
async def test_reserved_slots_from_storage(
    hass: HomeAssistant, mock_zha, stored: Any, first_user_slot: int
) -> None:
    """The option is stored as JSON and can be edited by hand in .storage.

    An integral float is read as its int; anything else that is not a whole
    number, a boolean included, falls back to the conservative default, so
    slot 0 stays protected whatever is in the file.
    """
    entry = await _setup_entry(hass, **{CONF_RESERVED_SLOTS: stored})

    assert entry.runtime_data.first_user_slot() == first_user_slot
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{LOCK_IEEE}-slot-{first_user_slot}")
    assert not registry.async_get_entity_id("sensor", DOMAIN, f"{LOCK_IEEE}-slot-{first_user_slot - 1}")


# -- PIN lengths, as the lock and the store can report them --


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        pytest.param({0x0018: 2, 0x0017: 8}, {"min": "4", "max": "8"}, id="minimum below the masking floor"),
        pytest.param({0x0018: 4, 0x0017: 40}, {"min": "4", "max": "8"}, id="maximum beyond any keypad"),
        pytest.param({0x0018: 8, 0x0017: 5}, {"min": "4", "max": "8"}, id="minimum above maximum"),
    ],
)
async def test_unusable_reported_pin_lengths_fall_back(
    hass: HomeAssistant, mock_zha, reported: dict[int, int], expected: dict[str, str]
) -> None:
    """A length the lock reports is only used when it can be true.

    Below PIN_LENGTH_SANE_MIN the log masking would no longer cover the code,
    above PIN_LENGTH_SANE_MAX it is a garbled read, and a minimum above the
    maximum means neither can be trusted.
    """
    lock_cluster(mock_zha).capabilities = reported
    entry = await _setup_entry(hass)

    assert await _pin_length_placeholders(hass, entry) == expected


async def test_pin_lengths_stored_as_text_fall_back(hass: HomeAssistant, mock_zha) -> None:
    """Capabilities are read back from .storage, where the types can be anything."""
    entry = await _setup_entry(hass, capabilities={"min_pin_length": "6", "max_pin_length": "10"})

    assert await _pin_length_placeholders(hass, entry) == {"min": "4", "max": "8"}
