"""Tests for the capability-derived slot ceiling in pin_rules.py.

pin_rules imports nothing but .const, so a stub package whose __path__
points at the component directory is enough to execute the real module.
The source-text class covers services.py, which cannot be imported in CI
(no voluptuous, no homeassistant); tests/test_service_slot_limits.py
executes the handlers themselves under stubs.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import types

_COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock"
)
_PACKAGE = "onesti_lock_pin_rules_under_test"


def _load_pin_rules():
    """Load pin_rules.py under a stub package so .const resolves."""
    if _PACKAGE not in sys.modules:
        package = types.ModuleType(_PACKAGE)
        package.__path__ = [_COMPONENT_DIR]
        sys.modules[_PACKAGE] = package
    name = f"{_PACKAGE}.pin_rules"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_COMPONENT_DIR, "pin_rules.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pin_rules = _load_pin_rules()


def _services_source() -> str:
    with open(os.path.join(_COMPONENT_DIR, "services.py")) as f:
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

    def test_the_other_three_handlers_keep_the_manual_range(self):
        """clear_pin, set_name and clear_slot must still accept slots 3-999."""
        source = _services_source()
        occurrences = len(
            re.findall(r"SLOT_FIRST_USER <= slot < MAX_SLOTS", source)
        )
        assert occurrences == 3
