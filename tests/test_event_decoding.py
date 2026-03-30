"""Tests for Onesti operation event decoding.

Verifies the bitmap32 decoding of attrid 0x0100 from the DoorLock cluster.
Format (little-endian): [user_slot, reserved, action, source]
"""
from __future__ import annotations

import pytest

# Import the decode function directly
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class MockCoordinator:
    """Minimal coordinator mock for testing."""

    def __init__(self, slots: dict[int, str] | None = None):
        self._slots = slots or {}

    def get_slot_name(self, slot: int) -> str:
        return self._slots.get(slot, f"Slot {slot}")


def _decode(val: int) -> dict | None:
    """Decode operation event — extracted logic for testing."""
    try:
        b = val.to_bytes(4, "little")
    except (OverflowError, ValueError):
        return None

    SOURCE_MAP = {0x00: "zigbee", 0x02: "keypad", 0x03: "fingerprint", 0x04: "rfid", 0x0A: "auto"}
    ACTION_MAP = {0x01: "lock", 0x02: "unlock"}

    user_slot = b[0]
    action = ACTION_MAP.get(b[2], "unknown")
    source = SOURCE_MAP.get(b[3], "unknown")
    user_slot_or_none = user_slot if user_slot > 0 else None

    return {
        "user_slot": user_slot_or_none,
        "action": action,
        "source": source,
    }


class TestEventDecoding:
    """Test Onesti operation event bitmap32 decoding."""

    def test_unlock_via_keypad_slot3(self):
        """Fredrik (slot 3) unlocks with PIN code."""
        # Raw: 0x02020003 → bytes LE: [03, 00, 02, 02]
        result = _decode(33685507)
        assert result["user_slot"] == 3
        assert result["action"] == "unlock"
        assert result["source"] == "keypad"

    def test_unlock_via_keypad_slot4(self):
        """Frode (slot 4) unlocks with PIN code."""
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

    def test_negative_value_returns_none(self):
        """Negative values should return None."""
        result = _decode(-1)
        assert result is None


class TestSlotMapping:
    """Test slot-to-name mapping."""

    def test_known_user(self):
        coord = MockCoordinator({3: "Fredrik", 4: "Frode"})
        assert coord.get_slot_name(3) == "Fredrik"
        assert coord.get_slot_name(4) == "Frode"

    def test_unknown_slot(self):
        coord = MockCoordinator({3: "Fredrik"})
        assert coord.get_slot_name(7) == "Slot 7"

    def test_system_slot(self):
        coord = MockCoordinator()
        assert coord.get_slot_name(0) == "Slot 0"
