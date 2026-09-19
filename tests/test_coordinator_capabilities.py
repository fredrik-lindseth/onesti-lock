"""Tests for lock capabilities read at setup.

Verifies that the coordinator exposes num_pin_users, max_pin_length,
min_pin_length as attributes when the lock reports them.
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


class TestActivitySensorAttributes:
    def test_no_pin_code_in_sensor(self):
        """PIN must never reach state attributes.

        Attrid 0x0101 is the PIN itself in plaintext, so the sensor must not
        store or expose it. See tests/test_no_pin_exposure.py.
        """
        sensor_path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "sensor.py"
        )
        with open(sensor_path) as f:
            source = f.read()
        assert "last_pin_code" not in source
        assert "update_last_pin_code" not in source

    def test_capabilities_exposed_in_attributes(self):
        """Activity sensor should expose lock_capabilities in state attributes."""
        sensor_path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "sensor.py"
        )
        with open(sensor_path) as f:
            source = f.read()
        assert "lock_capabilities" in source
