"""Property-based tests for Onesti operation event decoding.

Exercises the bitmap32 fields of attrid 0x0100 to verify:
- Encoding/decoding roundtrips across the full 16-bit slot range
- Field boundaries between slot, action and source
- No crashes on any input
- Consistency of the bitmap32 format

The decoder is loaded from the real source via test_event_decoding, so these
tests fail when production decoding changes.
"""
from __future__ import annotations

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_event_decoding import MockCoordinator, _load_decode_operation_event

SOURCE_MAP = {
    0x00: "zigbee",
    0x02: "keypad",
    0x03: "fingerprint",
    0x04: "rfid",
    0x05: "unattributed",
    0x0A: "auto",
}
ACTION_MAP = {0x01: "lock", 0x02: "unlock"}

_real_decode = _load_decode_operation_event()


def decode(val: int) -> dict | None:
    return _real_decode(MockCoordinator(), val)


def encode(slot: int, action: int, source: int) -> int:
    """Test-side inverse of the decoder; slot occupies bits 0-15."""
    return (source << 24) | (action << 16) | slot


class TestRoundtrip:
    """Verify encode→decode roundtrips for all valid combinations."""

    @pytest.mark.parametrize("slot", range(1000))
    def test_all_user_slots(self, slot):
        """Every valid user slot (0-999) decodes correctly."""
        val = encode(slot, 0x02, 0x02)
        result = decode(val)
        expected_slot = slot if slot > 0 else None
        assert result["user_slot"] == expected_slot
        assert result["action"] == "unlock"
        assert result["source"] == "keypad"

    @pytest.mark.parametrize("action_byte,expected", [
        (0x01, "lock"),
        (0x02, "unlock"),
        (0x00, "unknown"),
        (0x03, "unknown"),
        (0xFF, "unknown"),
    ])
    def test_action_values(self, action_byte, expected):
        val = encode(3, action_byte, 0x02)
        assert decode(val)["action"] == expected

    @pytest.mark.parametrize("source_byte,expected", [
        (0x00, "zigbee"),
        (0x02, "keypad"),
        (0x03, "fingerprint"),
        (0x04, "rfid"),
        (0x05, "unattributed"),
        (0x0A, "auto"),
        (0x01, "unknown"),
        (0xFF, "unknown"),
    ])
    def test_source_values(self, source_byte, expected):
        val = encode(3, 0x02, source_byte)
        assert decode(val)["source"] == expected

    @pytest.mark.parametrize("slot", [256, 300, 511, 512, 800, 999])
    def test_slot_over_255_roundtrip(self, slot):
        """Byte 1 is the high slot byte, not reserved (issues-4c287z)."""
        val = encode(slot, 0x02, 0x02)
        result = decode(val)
        assert result["user_slot"] == slot
        assert result["action"] == "unlock"
        assert result["source"] == "keypad"


class TestEdgeCases:
    """Test boundary values and invalid inputs."""

    def test_zero_decodes(self):
        result = decode(0)
        assert result is not None
        assert result["user_slot"] is None
        assert result["action"] == "unknown"
        assert result["source"] == "zigbee"  # 0x00 = zigbee

    def test_max_uint32(self):
        result = decode(0xFFFFFFFF)
        assert result is not None
        assert result["user_slot"] == 0xFFFF
        assert result["action"] == "unknown"
        assert result["source"] == "unknown"

    def test_negative_returns_none(self):
        assert decode(-1) is None

    def test_overflow_returns_none(self):
        assert decode(0x1FFFFFFFF) is None

    @pytest.mark.parametrize("val", [
        random.randint(0, 0xFFFFFFFF) for _ in range(100)
    ])
    def test_never_crashes(self, val):
        """Decode should never crash on any uint32 value."""
        result = decode(val)
        assert result is not None
        assert "user_slot" in result
        assert "action" in result
        assert "source" in result


class TestKnownValues:
    """Verify against real Zigbee captures from Nimly PRO."""

    CAPTURES = [
        (0x02020003, 3, "unlock", "keypad", "Ola slot 3 unlock via keypad — hytta"),
        (0x02020004, 4, "unlock", "keypad", "Kari slot 4 unlock via keypad — hytta"),
        (0x0A010000, None, "lock", "auto", "Auto-lock — hytta"),
        (0x02020000, None, "unlock", "keypad", "Master slot 0 unlock via keypad — hjemme"),
        (0x05010000, None, "lock", "unattributed", "NimlyCodePRO zigbee/auto/interior lock — supersej"),
    ]

    @pytest.mark.parametrize("raw,expected_slot,expected_action,expected_source,desc", CAPTURES)
    def test_known_capture(self, raw, expected_slot, expected_action, expected_source, desc):
        result = decode(raw)
        assert result["user_slot"] == expected_slot, f"Slot mismatch for {desc}"
        assert result["action"] == expected_action, f"Action mismatch for {desc}"
        assert result["source"] == expected_source, f"Source mismatch for {desc}"


class TestEncodeConsistency:
    """Verify that encode produces values that decode back correctly."""

    @pytest.mark.parametrize("slot", [0, 1, 3, 4, 50, 199, 255, 256, 300, 999])
    @pytest.mark.parametrize("action", [0x01, 0x02])
    @pytest.mark.parametrize("source", [0x00, 0x02, 0x03, 0x04, 0x0A])
    def test_encode_decode_roundtrip(self, slot, action, source):
        val = encode(slot, action, source)
        result = decode(val)
        expected_slot = slot if slot > 0 else None
        assert result["user_slot"] == expected_slot
        assert result["action"] == ACTION_MAP[action]
        assert result["source"] == SOURCE_MAP[source]
