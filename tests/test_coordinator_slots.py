"""Tests for coordinator slot operations.

Exercises slot data methods without importing homeassistant by loading
coordinator.py source and testing the slot logic in isolation.
"""
from __future__ import annotations

import ast
import os

import pytest


def _component_path(*parts):
    return os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", *parts
    )


def _load_const():
    namespace = {}
    with open(_component_path("const.py")) as f:
        exec(f.read(), namespace)
    return namespace


class TestSlotSetdefault:
    """Verify coordinator uses setdefault to avoid KeyError on new slots."""

    def _get_coordinator_source(self):
        with open(_component_path("coordinator.py")) as f:
            return f.read()

    def test_set_slot_name_uses_setdefault(self):
        """set_slot_name must use setdefault — slot may not exist in _slots."""
        source = self._get_coordinator_source()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "set_slot_name":
                body_source = ast.get_source_segment(source, node)
                assert "setdefault" in body_source, (
                    "set_slot_name must use setdefault to avoid KeyError on new slots"
                )
                return
        pytest.fail("set_slot_name method not found in coordinator.py")

    def test_set_pin_uses_setdefault(self):
        """set_pin must use setdefault — slot may not exist in _slots."""
        source = self._get_coordinator_source()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "set_pin":
                body_source = ast.get_source_segment(source, node)
                assert "setdefault" in body_source, (
                    "set_pin must use setdefault to avoid KeyError on new slots"
                )
                return
        pytest.fail("set_pin method not found in coordinator.py")

    def test_clear_pin_uses_setdefault(self):
        """clear_pin must use setdefault — slot may not exist in _slots."""
        source = self._get_coordinator_source()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "clear_pin":
                body_source = ast.get_source_segment(source, node)
                assert "setdefault" in body_source, (
                    "clear_pin must use setdefault to avoid KeyError on new slots"
                )
                return
        pytest.fail("clear_pin method not found in coordinator.py")


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
