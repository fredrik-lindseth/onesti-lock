"""Tests for the slot dict pattern the coordinator relies on.

Exercises DEFAULT_SLOT from const.py without importing homeassistant. That
set_slot_name, set_pin and clear_pin create unused slots instead of raising
KeyError is tested end to end in tests_ha/test_sensor.py.
"""
from __future__ import annotations

import os


def _component_path(*parts):
    return os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", *parts
    )


def _load_const():
    namespace = {}
    with open(_component_path("const.py")) as f:
        exec(f.read(), namespace)
    return namespace


class TestSlotLogic:
    """Test slot dict operations directly (no HA dependency)."""

    def _default_slot(self):
        c = _load_const()
        return c["DEFAULT_SLOT"]

    def test_setdefault_on_empty_slots(self):
        """setdefault pattern must work when slot doesn't exist."""
        slots: dict = {}
        default = self._default_slot()

        # Simulate: self._slots.setdefault(str(slot), {**DEFAULT_SLOT})["name"] = name
        slots.setdefault("5", {**default})["name"] = "Kari"

        assert slots["5"]["name"] == "Kari"
        assert slots["5"]["has_pin"] is False

    def test_setdefault_preserves_existing(self):
        """setdefault must not overwrite existing slot data."""
        default = self._default_slot()
        slots = {
            "5": {"name": "Kari", "has_pin": True, "has_rfid": False},
        }

        # Simulate set_pin on existing slot
        slot_data = slots.setdefault("5", {**default})
        slot_data["name"] = "Kari"
        slot_data["has_pin"] = True

        assert slots["5"]["name"] == "Kari"
        assert slots["5"]["has_pin"] is True

    def test_setdefault_new_slot_has_all_default_keys(self):
        """New slot created via setdefault must have all DEFAULT_SLOT keys."""
        slots: dict = {}
        default = self._default_slot()

        slots.setdefault("99", {**default})["name"] = "Test"

        for key in default:
            assert key in slots["99"], f"Missing key '{key}' in new slot"

    def test_clear_slot_resets_to_default(self):
        """clear_slot should reset slot to DEFAULT_SLOT."""
        default = self._default_slot()
        slots = {
            "5": {"name": "Kari", "has_pin": True, "has_rfid": True},
        }

        # Simulate: self._slots[str(slot)] = {**DEFAULT_SLOT}
        slots["5"] = {**default}

        assert slots["5"]["name"] == ""
        assert slots["5"]["has_pin"] is False
        assert slots["5"]["has_rfid"] is False
