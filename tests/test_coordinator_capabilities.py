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

    def test_reads_standard_zcl_capability_attributes(self):
        """Must read 0x0012, 0x0017, 0x0018 (standard ZCL DoorLock attributes)."""
        source = _source()
        # Standard ZCL: NumberOfPINUsersSupported, MaxPINCodeLength, MinPINCodeLength
        assert "0x0012" in source
        assert "0x0017" in source
        assert "0x0018" in source

    def test_attribute_mapping_matches_zcl_spec(self):
        """Attribute IDs must map to the correct names per zigpy.

        Verified against live NimlyPRO: 0x0012=50 (num users), 0x0017=8 (max len),
        0x0018=4 (min len). Source: zigpy.zcl.clusters.closures.DoorLock.
        """
        source = _source()
        # 0x0017 must be max_pin_length (not min)
        assert '0x0017: "max_pin_length"' in source
        # 0x0018 must be min_pin_length (not max)
        assert '0x0018: "min_pin_length"' in source

    def test_handles_missing_capabilities_silently(self):
        """Must not crash if lock doesn't expose capabilities — some variants don't."""
        source = _source()
        # Find read_lock_capabilities and verify it has try/except
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "read_lock_capabilities":
                has_try = any(isinstance(n, ast.Try) for n in ast.walk(node))
                assert has_try, "read_lock_capabilities must handle errors gracefully"
                return
        raise AssertionError("read_lock_capabilities not found")


class TestActivitySensorAttributes:
    def test_last_pin_code_in_sensor(self):
        """Activity sensor should handle last_pin_code updates."""
        sensor_path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "sensor.py"
        )
        with open(sensor_path) as f:
            source = f.read()
        assert "update_last_pin_code" in source
        assert "last_pin_code" in source

    def test_capabilities_exposed_in_attributes(self):
        """Activity sensor should expose lock_capabilities in state attributes."""
        sensor_path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "sensor.py"
        )
        with open(sensor_path) as f:
            source = f.read()
        assert "lock_capabilities" in source
