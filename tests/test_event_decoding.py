"""Tests for Onesti operation event decoding.

Verifies the bitmap32 decoding of attrid 0x0100 from the DoorLock cluster.
Format (little-endian): bits 0-15 user_slot, bits 16-23 action, bits 24-31 source.
"""
from __future__ import annotations

import ast
import importlib.util
import os

import pytest

_PKG = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock"
)
_INIT_PATH = os.path.join(_PKG, "__init__.py")
_CONST_PATH = os.path.join(_PKG, "const.py")


class MockCoordinator:
    """Minimal coordinator mock for testing."""

    def __init__(self, slots: dict[int, str] | None = None):
        self._slots = slots or {}

    def get_slot_name(self, slot: int) -> str:
        return self._slots.get(slot, f"Slot {slot}")


def _load_decode_operation_event():
    """Load the real decoder from source (avoids HA imports).

    Same ast-extraction pattern as test_pin_code_decoding.py. Tests used to
    replicate the decode logic instead, which let an 8-bit slot bug pass a
    fully green suite. Never replicate; always load from source.
    """
    spec = importlib.util.spec_from_file_location("onesti_const", _CONST_PATH)
    const = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(const)
    ns = dict(vars(const))

    with open(_INIT_PATH) as f:
        tree = ast.parse(f.read())
    wanted: list[ast.stmt] = []
    for node in tree.body:
        is_map = isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) in ("_SOURCE_MAP", "_ACTION_MAP")
            for t in node.targets
        )
        is_decoder = (
            isinstance(node, ast.FunctionDef) and node.name == "_decode_operation_event"
        )
        if is_map or is_decoder:
            wanted.append(node)
    module = ast.Module(body=wanted, type_ignores=[])
    exec(compile(module, _INIT_PATH, "exec"), ns)
    return ns["_decode_operation_event"]


_real_decode = _load_decode_operation_event()


def _decode(val: int, coordinator: MockCoordinator | None = None) -> dict | None:
    return _real_decode(coordinator or MockCoordinator(), val)


class TestEventDecoding:
    """Test Onesti operation event bitmap32 decoding."""

    def test_unlock_via_keypad_slot3(self):
        """Ola (slot 3) unlocks with PIN code."""
        # Raw: 0x02020003 → bytes LE: [03, 00, 02, 02]
        result = _decode(33685507)
        assert result["user_slot"] == 3
        assert result["action"] == "unlock"
        assert result["source"] == "keypad"

    def test_unlock_via_keypad_slot4(self):
        """Kari (slot 4) unlocks with PIN code."""
        # Raw: 0x02020004 → bytes LE: [04, 00, 02, 02]
        result = _decode(0x02020004)
        assert result["user_slot"] == 4
        assert result["action"] == "unlock"
        assert result["source"] == "keypad"

    def test_auto_lock(self):
        """Auto-lock after timeout — no user."""
        # Raw: 0x0A010000 → bytes LE: [00, 00, 01, 0A]
        result = _decode(167837696)
        assert result["user_slot"] is None
        assert result["action"] == "lock"
        assert result["source"] == "auto"

    def test_fingerprint_unlock(self):
        """Unlock via fingerprint sensor."""
        # bytes LE: [05, 00, 02, 03] — slot 5, unlock, fingerprint
        result = _decode(0x03020005)
        assert result["user_slot"] == 5
        assert result["action"] == "unlock"
        assert result["source"] == "fingerprint"

    def test_rfid_unlock(self):
        """Unlock via RFID/NFC tag."""
        # bytes LE: [06, 00, 02, 04] — slot 6, unlock, rfid
        result = _decode(0x04020006)
        assert result["user_slot"] == 6
        assert result["action"] == "unlock"
        assert result["source"] == "rfid"

    def test_zigbee_lock(self):
        """Lock via Zigbee command (from HA)."""
        # bytes LE: [00, 00, 01, 00]
        result = _decode(0x00010000)
        assert result["user_slot"] is None
        assert result["action"] == "lock"
        assert result["source"] == "zigbee"

    def test_unattributed_lock_codepro(self):
        """NimlyCodePRO fw 4.8: zigbee/auto-relock/interior keypad all report 0x05."""
        # bytes LE: [00, 00, 01, 05]
        result = _decode(0x05010000)
        assert result["user_slot"] is None
        assert result["action"] == "lock"
        assert result["source"] == "unattributed"

    def test_unknown_action(self):
        """Unknown action byte."""
        # bytes LE: [03, 00, 05, 02] — action 5 is unknown
        result = _decode(0x02050003)
        assert result["user_slot"] == 3
        assert result["action"] == "unknown"
        assert result["source"] == "keypad"

    def test_unknown_source(self):
        """Unknown source byte."""
        # bytes LE: [03, 00, 02, 07] — source 7 is unknown
        result = _decode(0x07020003)
        assert result["user_slot"] == 3
        assert result["action"] == "unlock"
        assert result["source"] == "unknown"

    def test_zero_value(self):
        """All zeros — zigbee command with no user."""
        result = _decode(0)
        assert result["user_slot"] is None
        assert result["action"] == "unknown"
        assert result["source"] == "zigbee"  # 0x00 = zigbee per Z2M

    def test_high_slot_number(self):
        """User slot 199 (max)."""
        # bytes LE: [C7, 00, 02, 02] — slot 199
        result = _decode(0x020200C7)
        assert result["user_slot"] == 199
        assert result["action"] == "unlock"
        assert result["source"] == "keypad"

    def test_slot_300_keypad_unlock(self):
        """Regression issues-4c287z: byte-0 read decoded slot 300 as 44."""
        # bytes LE: [2C, 01, 02, 02] — slot 300, unlock, keypad
        result = _decode(0x0202012C)
        assert result["user_slot"] == 300
        assert result["action"] == "unlock"
        assert result["source"] == "keypad"

    def test_slot_256_boundary(self):
        """Slot 256 has byte 0 == 0x00; byte-0 read decoded it as system."""
        # bytes LE: [00, 01, 02, 02] — slot 256, unlock, keypad
        result = _decode(0x02020100)
        assert result["user_slot"] == 256

    def test_slot_255_boundary(self):
        """Slot 255 decodes identically before and after the 16-bit fix."""
        # bytes LE: [FF, 00, 02, 02] — slot 255, unlock, keypad
        result = _decode(0x020200FF)
        assert result["user_slot"] == 255

    def test_slot_999_max(self):
        """Max slot per the Nimly manual (MAX_SLOTS - 1)."""
        # bytes LE: [E7, 03, 02, 02] — slot 999, unlock, keypad
        result = _decode(0x020203E7)
        assert result["user_slot"] == 999

    def test_high_slot_name_attribution(self):
        """A named high slot attributes the event to the right user."""
        coord = MockCoordinator({300: "Bjarte"})
        result = _decode(0x0202012C, coord)
        assert result["user_name"] == "Bjarte"

    def test_overflow_returns_none(self):
        """Values above uint32 are rejected by the explicit range guard."""
        assert _decode(0x1FFFFFFFF) is None

    def test_negative_value_returns_none(self):
        """Negative values should return None."""
        result = _decode(-1)
        assert result is None


class TestSlotMapping:
    """Test slot-to-name mapping."""

    def test_known_user(self):
        coord = MockCoordinator({3: "Ola", 4: "Kari"})
        assert coord.get_slot_name(3) == "Ola"
        assert coord.get_slot_name(4) == "Kari"

    def test_unknown_slot(self):
        coord = MockCoordinator({3: "Ola"})
        assert coord.get_slot_name(7) == "Slot 7"

    def test_system_slot(self):
        coord = MockCoordinator()
        assert coord.get_slot_name(0) == "Slot 0"
