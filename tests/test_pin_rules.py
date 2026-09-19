"""Tests for the capability-derived slot and PIN rules in pin_rules.py.

pin_rules imports nothing but .const, so a stub package whose __path__
points at the component directory is enough to execute the real module.
The source-text class covers services.py, which cannot be imported in CI
(no voluptuous, no homeassistant); tests/test_service_slot_limits.py
executes the handlers themselves under stubs.
"""
from __future__ import annotations

import os
import re

from .conftest import COMPONENT_DIR, load_component_module

pin_rules = load_component_module("pin_rules")


def _services_source() -> str:
    with open(os.path.join(COMPONENT_DIR, "services.py")) as f:
        return f.read()


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


class TestOnlySetPinIsCapped:
    """The ceiling belongs to set_pin; the other services stay permissive."""

    def _set_pin_body(self) -> str:
        source = _services_source()
        start = source.index("async def handle_set_pin")
        end = source.index("async def handle_clear_pin")
        return source[start:end]

    def test_set_pin_uses_the_dynamic_ceiling(self):
        body = self._set_pin_body()
        assert "coordinator.max_user_slot()" in body
        assert '"max": str(max_slot)' in body

    def test_set_pin_no_longer_uses_the_static_ceiling(self):
        assert "MAX_SLOTS - 1" not in self._set_pin_body()

    def test_the_other_three_handlers_keep_the_manual_ceiling(self):
        """clear_pin, set_name and clear_slot stay open up to slot 999.

        Their floors differ (the reserved-slots setting for the two that
        touch the lock, 0 for set_name), which the handler tests in
        test_reserved_slots.py execute; here only the static ceiling is
        pinned, since a capacity cap on them would strand old codes.
        """
        source = _services_source()
        assert len(re.findall(r"slot < MAX_SLOTS", source)) == 3
        assert "SLOT_FIRST_USER" not in source


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

    def test_non_digits_are_rejected(self):
        for code in ("12a4", "12 34", "-1234", "1234\n", "12.34"):
            assert not pin_rules.is_valid_pin(code, None), repr(code)

    def test_digits_no_keypad_can_type_are_rejected(self):
        """str.isdigit accepts these, the lock's keypad cannot enter them."""
        for code in ("\u00b2\u00b3\u00b9\u2074", "\u0661\u0662\u0663\u0664", "\uff11\uff12\uff13\uff14"):
            assert code.isdigit()
            assert not pin_rules.is_valid_pin(code, None), repr(code)
