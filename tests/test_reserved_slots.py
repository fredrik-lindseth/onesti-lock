"""The reserved-slots setting, run through the real coordinator and handlers.

Naming is the integration's own data, so set_name accepts every slot.
PIN writes and clears reach the lock, so set_pin, clear_pin and clear_slot
refuse the master slots: 0-2 by default (Touch Pro, PRO, Code), or only
slot 0 once the user sets reserved_slots to 1 (Code Pro). Slot 0 is never
opened. The coordinator comes from the test_coordinator_behavior.py
harness and the handlers from the stubs in test_service_slot_limits.py,
so both sides are the shipped code.
"""
from __future__ import annotations

import asyncio

import pytest

from .conftest import load_component_module
from .test_coordinator_behavior import _make_coordinator
from .test_service_slot_limits import FakeCall, ServiceValidationError, _handlers


class _DeliveringTransport:
    """Records (command, user_id) for every send and reports it delivered."""

    def __init__(self):
        self.sent = []

    async def send(self, command, params):
        self.sent.append((command, params["user_id"]))
        return load_component_module("zha").SEND_DELIVERED


def _lock(options=None):
    """A real coordinator whose ZCL send always reaches the lock."""
    transport = _DeliveringTransport()
    hass, entry, coord = _make_coordinator(options, transport=transport)
    return hass, entry, coord, transport.sent


def _call(coord, service, **data):
    asyncio.run(_handlers(coord)[service](FakeCall(**data)))


def _refused(coord, service, **data):
    with pytest.raises(ServiceValidationError) as excinfo:
        _call(coord, service, **data)
    assert excinfo.value.translation_key == "invalid_slot"
    return excinfo.value


class TestCoordinatorFirstUserSlot:
    def test_default_is_three(self):
        _hass, _entry, coord, _sent = _lock({"slots": {}})
        assert coord.first_user_slot() == 3

    def test_reads_the_entry_option(self):
        _hass, _entry, coord, _sent = _lock({"slots": {}, "reserved_slots": 1})
        assert coord.first_user_slot() == 1

    def test_saving_slots_keeps_the_setting(self):
        hass, entry, coord, _sent = _lock({"slots": {}, "reserved_slots": 1})
        asyncio.run(coord.set_slot_name(3, "Kari"))
        assert hass.config_entries.written[-1]["reserved_slots"] == 1
        assert entry.options["reserved_slots"] == 1
        assert coord.first_user_slot() == 1


class TestSetPinFloor:
    def test_slot_2_refused_by_default(self):
        _hass, _entry, coord, sent = _lock({"slots": {}})
        error = _refused(coord, "set_pin", slot=2, name="Kari", code="1234")
        assert error.translation_placeholders["min"] == "3"
        assert sent == []

    def test_slot_1_refused_by_default(self):
        _hass, _entry, coord, sent = _lock({"slots": {}})
        _refused(coord, "set_pin", slot=1, name="Kari", code="1234")
        assert sent == []

    def test_slot_2_accepted_with_one_reserved(self):
        _hass, _entry, coord, sent = _lock({"slots": {}, "reserved_slots": 1})
        _call(coord, "set_pin", slot=2, name="Kari", code="1234")
        assert sent == [(0x0005, 2)]
        assert coord.get_slot(2)["has_pin"] is True

    def test_slot_1_accepted_with_one_reserved(self):
        _hass, _entry, coord, sent = _lock({"slots": {}, "reserved_slots": 1})
        _call(coord, "set_pin", slot=1, name="Kari", code="1234")
        assert sent == [(0x0005, 1)]

    @pytest.mark.parametrize("reserved", [None, 0, 1, 2, 3])
    def test_slot_0_always_refused(self, reserved):
        options = {"slots": {}}
        if reserved is not None:
            options["reserved_slots"] = reserved
        _hass, _entry, coord, sent = _lock(options)
        _refused(coord, "set_pin", slot=0, name="Kari", code="1234")
        assert sent == []


class TestClearFloor:
    def test_clear_pin_slot_1_refused_by_default(self):
        _hass, _entry, coord, sent = _lock({"slots": {}})
        error = _refused(coord, "clear_pin", slot=1)
        assert error.translation_placeholders == {"min": "3", "max": "999"}
        assert sent == []

    def test_clear_pin_slot_1_accepted_with_one_reserved(self):
        _hass, _entry, coord, sent = _lock({"slots": {}, "reserved_slots": 1})
        _call(coord, "clear_pin", slot=1)
        assert sent == [(0x0007, 1)]

    def test_clear_slot_slot_2_refused_by_default(self):
        _hass, _entry, coord, sent = _lock({"slots": {}})
        _refused(coord, "clear_slot", slot=2)
        assert sent == []

    def test_clear_slot_slot_0_refused_even_with_one_reserved(self):
        _hass, _entry, coord, sent = _lock({"slots": {}, "reserved_slots": 1})
        _refused(coord, "clear_slot", slot=0)
        assert sent == []


class TestSetNameIsOpen:
    @pytest.mark.parametrize("slot", [0, 1])
    def test_master_slots_can_be_named(self, slot):
        hass, _entry, coord, sent = _lock({"slots": {}})
        _call(coord, "set_name", slot=slot, name="Master")
        assert coord.get_slot(slot)["name"] == "Master"
        assert hass.config_entries.written[-1]["slots"][str(slot)]["name"] == "Master"
        assert sent == []

    def test_slot_999_can_be_named(self):
        _hass, _entry, coord, _sent = _lock({"slots": {}})
        _call(coord, "set_name", slot=999, name="Last")
        assert coord.get_slot(999)["name"] == "Last"

    @pytest.mark.parametrize("slot", [-1, 1000])
    def test_out_of_range_refused(self, slot):
        _hass, _entry, coord, _sent = _lock({"slots": {}})
        error = _refused(coord, "set_name", slot=slot, name="X")
        assert error.translation_placeholders == {"min": "0", "max": "999"}


class TestCoordinatorIsTheLastGuard:
    """The coordinator refuses reserved slots itself, whatever the caller."""

    @pytest.mark.parametrize("reserved", [None, 1, 3])
    @pytest.mark.parametrize(
        "method,args",
        [("set_pin", ("Kari", "1234")), ("clear_pin", ()), ("clear_slot", ())],
    )
    def test_slot_0_refused(self, reserved, method, args):
        options = {"slots": {}}
        if reserved is not None:
            options["reserved_slots"] = reserved
        hass, _entry, coord, sent = _lock(options)
        with pytest.raises(ValueError, match="reserved master slot"):
            asyncio.run(getattr(coord, method)(0, *args))
        assert sent == []
        assert hass.config_entries.written == []

    @pytest.mark.parametrize(
        "method,args",
        [("set_pin", ("Kari", "1234")), ("clear_pin", ()), ("clear_slot", ())],
    )
    def test_slot_below_the_floor_refused(self, method, args):
        _hass, _entry, coord, sent = _lock({"slots": {}})
        with pytest.raises(ValueError, match="start at slot 3"):
            asyncio.run(getattr(coord, method)(2, *args))
        assert sent == []

    @pytest.mark.parametrize(
        "method,args",
        [("set_pin", ("Kari", "1234")), ("clear_pin", ()), ("clear_slot", ())],
    )
    def test_first_user_slot_accepted(self, method, args):
        _hass, _entry, coord, sent = _lock({"slots": {}, "reserved_slots": 1})
        assert asyncio.run(getattr(coord, method)(1, *args)).delivered
        assert sent and sent[0][1] == 1


class TestEmptyNameLeavesNoRecord:
    """An empty name removes the name and never stores a blank slot."""

    def test_empty_name_on_unknown_slot_stores_nothing(self):
        hass, _entry, coord, _sent = _lock({"slots": {}})
        asyncio.run(coord.set_slot_name(5, ""))
        assert "5" not in coord._slots
        assert hass.config_entries.written == []

    def test_empty_name_drops_a_name_only_slot(self):
        hass, _entry, coord, _sent = _lock({"slots": {}})
        asyncio.run(coord.set_slot_name(0, "Master"))
        asyncio.run(coord.set_slot_name(0, ""))
        assert "0" not in coord._slots
        assert "0" not in hass.config_entries.written[-1]["slots"]

    def test_empty_name_keeps_a_slot_with_a_pin(self):
        hass, _entry, coord, _sent = _lock({"slots": {}})
        asyncio.run(coord.set_pin(4, "Kari", "1234"))
        asyncio.run(coord.set_slot_name(4, ""))
        stored = hass.config_entries.written[-1]["slots"]["4"]
        assert stored["name"] == ""
        assert stored["has_pin"] is True
