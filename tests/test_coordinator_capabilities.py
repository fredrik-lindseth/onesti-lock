"""Tests for lock capabilities read at setup.

Checks that the coordinator has the capability store and reader. That the
activity sensor exposes num_pin_users, max_pin_length and min_pin_length as
attributes is tested against real Home Assistant in tests_ha/test_sensor.py.
"""
from __future__ import annotations

import ast
import os

_coordinator_path = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "coordinator.py"
)


def _source() -> str:
    with open(_coordinator_path) as f:
        return f.read()


class TestLockCapabilities:
    def test_lock_capabilities_attribute_exists(self):
        """Coordinator has a lock_capabilities dict attribute."""
        assert "self.lock_capabilities" in _source()

    def test_read_lock_capabilities_method_exists(self):
        """Coordinator has an async read_lock_capabilities method."""
        tree = ast.parse(_source())
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "read_lock_capabilities":
                found = True
                break
        assert found, "read_lock_capabilities must exist as async method"

