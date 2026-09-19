"""Tests for the capability-derived slot and PIN rules in pin_rules.py.

pin_rules imports nothing but .const, so a stub package whose __path__
points at the component directory is enough to execute the real module.
TestOnlySetPinIsCapped runs the real service handlers on the stubs from
conftest.py, with the harness from tests/test_service_slot_limits.py.
"""
from __future__ import annotations

import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError

from .conftest import load_component_module
from .test_service_slot_limits import FakeCall, FakeCoordinator, _handlers

pin_rules = load_component_module("pin_rules")


class TestMaxUserSlotFallback:
    """Without a trustworthy attribute the manual's range still applies."""

    def test_none_falls_back_to_the_manual(self):
        assert pin_rules.max_user_slot(None) == 999

    def test_empty_capabilities_fall_back_to_the_manual(self):
        assert pin_rules.max_user_slot({}) == 999

    def test_missing_key_falls_back_to_the_manual(self):
        assert pin_rules.max_user_slot({"max_pin_length": 8}) == 999

    def test_zero_never_blocks_anything(self):
        """A lock reporting 0 must not lock the user out of every slot."""
        assert pin_rules.max_user_slot({"num_pin_users": 0}) == 999

    def test_no_room_for_a_user_slot_falls_back(self):
        assert pin_rules.max_user_slot({"num_pin_users": 3}) == 999

    def test_negative_falls_back(self):
        assert pin_rules.max_user_slot({"num_pin_users": -5}) == 999

    def test_above_the_manual_range_falls_back(self):
        assert pin_rules.max_user_slot({"num_pin_users": 1001}) == 999

    def test_string_falls_back(self):
        assert pin_rules.max_user_slot({"num_pin_users": "50"}) == 999

    def test_none_value_falls_back(self):
        assert pin_rules.max_user_slot({"num_pin_users": None}) == 999


class TestMaxUserSlotCeiling:
    """A trustworthy count caps the range at N-1."""

    def test_reported_capacity_of_fifty(self):
        """NimlyPRO and NimlyCodePRO both report 50, so slot 49 is the last."""
        assert pin_rules.max_user_slot({"num_pin_users": 50}) == 49

    def test_smallest_usable_capacity(self):
        assert pin_rules.max_user_slot({"num_pin_users": 4}) == 3

    def test_full_manual_capacity(self):
        assert pin_rules.max_user_slot({"num_pin_users": 1000}) == 999


class _EveryHandlerCoordinator(FakeCoordinator):
    """A lock reporting 50 PIN users, recording all four operations."""

    def __init__(self):
        super().__init__({"num_pin_users": 50})
        self.calls = []

    async def set_pin(self, slot, name, code):
        self.calls.append(("set_pin", slot))
        return True

    async def clear_pin(self, slot):
        self.calls.append(("clear_pin", slot))
        return True

    async def clear_slot(self, slot):
        self.calls.append(("clear_slot", slot))
        return True

    async def set_slot_name(self, slot, name):
        self.calls.append(("set_name", slot))


def _call(handlers, service, slot):
    data = {"slot": slot, "name": "Kari", "code": "1234"}
    if service in ("clear_pin", "clear_slot"):
        del data["name"], data["code"]
    elif service == "set_name":
        del data["code"]
    asyncio.run(handlers[service](FakeCall(**data)))


class TestOnlySetPinIsCapped:
    """The ceiling belongs to set_pin; the other services stay open to 999.

    The lock reports 50 PIN users. A capacity cap on clear_pin or
    clear_slot would strand codes written before the capacity was known,
    and names never reach the lock at all. Their floors differ (the
    reserved-slots setting for the two that touch the lock, 0 for
    set_name), which tests/test_reserved_slots.py covers.
    """

    def test_set_pin_stops_at_the_reported_capacity(self):
        coordinator = _EveryHandlerCoordinator()
        handlers = _handlers(coordinator)
        with pytest.raises(HomeAssistantError) as excinfo:
            _call(handlers, "set_pin", 50)
        assert excinfo.value.translation_placeholders["max"] == "49"
        assert coordinator.calls == []

    @pytest.mark.parametrize("service", ["clear_pin", "clear_slot", "set_name"])
    def test_the_other_three_reach_slot_999(self, service):
        coordinator = _EveryHandlerCoordinator()
        _call(_handlers(coordinator), service, 999)
        assert coordinator.calls == [(service, 999)]

    @pytest.mark.parametrize("service", ["clear_pin", "clear_slot", "set_name"])
    def test_the_other_three_stop_at_the_manual_ceiling(self, service):
        coordinator = _EveryHandlerCoordinator()
        with pytest.raises(HomeAssistantError) as excinfo:
            _call(_handlers(coordinator), service, 1000)
        assert excinfo.value.translation_key == "invalid_slot"
        assert excinfo.value.translation_placeholders["max"] == "999"
        assert coordinator.calls == []


class TestFirstUserSlot:
    """The reserved-slots option, clamped so slot 0 stays protected."""

    def test_missing_options_fall_back_to_three(self):
        assert pin_rules.first_user_slot(None) == 3
        assert pin_rules.first_user_slot({}) == 3

    def test_missing_key_falls_back_to_three(self):
        assert pin_rules.first_user_slot({"slots": {}}) == 3

    def test_invalid_values_fall_back_to_three(self):
        for value in ("1", None, [], 1.5, True):
            assert pin_rules.first_user_slot({"reserved_slots": value}) == 3

    def test_zero_is_clamped_to_one(self):
        """Slot 0 is the master code on every model and is never opened."""
        assert pin_rules.first_user_slot({"reserved_slots": 0}) == 1

    def test_negative_is_clamped_to_one(self):
        assert pin_rules.first_user_slot({"reserved_slots": -2}) == 1

    def test_four_is_clamped_to_three(self):
        assert pin_rules.first_user_slot({"reserved_slots": 4}) == 3

    def test_two_is_kept(self):
        assert pin_rules.first_user_slot({"reserved_slots": 2}) == 2

    def test_one_is_kept(self):
        """Code Pro reserves only slot 000."""
        assert pin_rules.first_user_slot({"reserved_slots": 1}) == 1

    def test_integral_float_from_hand_edited_options(self):
        """Hand-edited or older stored options may hold 1.0 instead of 1."""
        assert pin_rules.first_user_slot({"reserved_slots": 1.0}) == 1


class TestPinLengthRange:
    """The reported MinPINCodeLength/MaxPINCodeLength, or 4-8 without them."""

    def test_unread_capabilities_fall_back_to_four_to_eight(self):
        assert pin_rules.pin_length_range(None) == (4, 8)
        assert pin_rules.pin_length_range({}) == (4, 8)

    def test_reported_values_are_used(self):
        caps = {"min_pin_length": 6, "max_pin_length": 10}
        assert pin_rules.pin_length_range(caps) == (6, 10)

    def test_nimlypro_reports_the_fallback_itself(self):
        caps = {"min_pin_length": 4, "max_pin_length": 8, "num_pin_users": 50}
        assert pin_rules.pin_length_range(caps) == (4, 8)

    def test_each_bound_falls_back_on_its_own(self):
        assert pin_rules.pin_length_range({"max_pin_length": 6}) == (4, 6)
        assert pin_rules.pin_length_range({"min_pin_length": 5}) == (5, 8)

    def test_equal_bounds_are_kept(self):
        caps = {"min_pin_length": 6, "max_pin_length": 6}
        assert pin_rules.pin_length_range(caps) == (6, 6)

    def test_min_below_one_falls_back(self):
        caps = {"min_pin_length": 0, "max_pin_length": 6}
        assert pin_rules.pin_length_range(caps) == (4, 6)

    def test_reported_min_below_four_is_not_trusted(self):
        """redact.py masks from 4 digits, so a shorter PIN would reach the log."""
        for reported in (1, 2, 3):
            caps = {"min_pin_length": reported, "max_pin_length": 6}
            assert pin_rules.pin_length_range(caps) == (4, 6), reported

    def test_the_sane_floor_itself_is_kept(self):
        caps = {"min_pin_length": pin_rules.PIN_LENGTH_SANE_MIN, "max_pin_length": 6}
        assert pin_rules.pin_length_range(caps) == (4, 6)

    def test_reported_max_below_four_falls_back(self):
        assert pin_rules.pin_length_range({"min_pin_length": 1, "max_pin_length": 3}) == (4, 8)

    def test_max_above_the_sane_ceiling_falls_back(self):
        caps = {"min_pin_length": 4, "max_pin_length": 255}
        assert pin_rules.pin_length_range(caps) == (4, 8)

    def test_the_sane_ceiling_itself_is_kept(self):
        caps = {"min_pin_length": 4, "max_pin_length": pin_rules.PIN_LENGTH_SANE_MAX}
        assert pin_rules.pin_length_range(caps) == (4, 20)

    def test_min_above_max_drops_both(self):
        """A contradiction means neither value can be trusted."""
        caps = {"min_pin_length": 9, "max_pin_length": 6}
        assert pin_rules.pin_length_range(caps) == (4, 8)

    def test_min_above_the_fallback_max_drops_both(self):
        assert pin_rules.pin_length_range({"min_pin_length": 10}) == (4, 8)

    def test_non_int_values_fall_back(self):
        for value in ("6", None, 6.0, True, [6]):
            caps = {"min_pin_length": value, "max_pin_length": value}
            assert pin_rules.pin_length_range(caps) == (4, 8), value


class TestIsValidPin:
    """Digits only, and a length inside the lock's range."""

    def test_fallback_bounds_are_inclusive(self):
        assert pin_rules.is_valid_pin("1234", None)
        assert pin_rules.is_valid_pin("12345678", None)

    def test_outside_the_fallback_range(self):
        assert not pin_rules.is_valid_pin("123", None)
        assert not pin_rules.is_valid_pin("123456789", None)
        assert not pin_rules.is_valid_pin("", None)

    def test_reported_range_is_followed(self):
        caps = {"min_pin_length": 6, "max_pin_length": 10}
        assert not pin_rules.is_valid_pin("12345", caps)
        assert pin_rules.is_valid_pin("123456", caps)
        assert pin_rules.is_valid_pin("1234567890", caps)
        assert not pin_rules.is_valid_pin("12345678901", caps)

    def test_three_digit_pin_rejected_even_when_the_lock_allows_it(self):
        caps = {"min_pin_length": 3, "max_pin_length": 8}
        assert not pin_rules.is_valid_pin("123", caps)
        assert pin_rules.is_valid_pin("1234", caps)

    def test_non_digits_are_rejected(self):
        for code in ("12a4", "12 34", "-1234", "1234\n", "12.34"):
            assert not pin_rules.is_valid_pin(code, None), repr(code)

    def test_digits_no_keypad_can_type_are_rejected(self):
        """str.isdigit accepts these, the lock's keypad cannot enter them."""
        for code in ("\u00b2\u00b3\u00b9\u2074", "\u0661\u0662\u0663\u0664", "\uff11\uff12\uff13\uff14"):
            assert code.isdigit()
            assert not pin_rules.is_valid_pin(code, None), repr(code)
