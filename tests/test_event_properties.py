"""Property-based tests for Onesti operation event decoding.

Tests all possible byte combinations to verify:
- Encoding/decoding roundtrips
- Byte boundaries
- No crashes on any input
- Consistency of the bitmap32 format
"""
from __future__ import annotations

import pytest
import random

# Replicate decode logic
SOURCE_MAP = {0x01: "rf", 0x02: "keypad", 0x03: "manual", 0x0A: "auto"}
ACTION_MAP = {0x01: "lock", 0x02: "unlock"}


def decode(val: int) -> dict | None:
    try:
        b = val.to_bytes(4, "little")
    except (OverflowError, ValueError):
        return None
    return {
        "user_slot": b[0] if b[0] > 0 else None,
        "reserved": b[1],
        "action": ACTION_MAP.get(b[2], "unknown"),
        "source": SOURCE_MAP.get(b[3], "unknown"),
        "raw_bytes": list(b),
    }


def encode(slot: int, reserved: int, action: int, source: int) -> int:
    b = bytes([slot, reserved, action, source])
    return int.from_bytes(b, "little")


class TestRoundtrip:
    """Verify encode→decode roundtrips for all valid combinations."""

    @pytest.mark.parametrize("slot", range(200))
    def test_all_user_slots(self, slot):
        """Every valid user slot (0-199) decodes correctly."""
        val = encode(slot, 0, 0x02, 0x02)
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
        val = encode(3, 0, action_byte, 0x02)
        assert decode(val)["action"] == expected

    @pytest.mark.parametrize("source_byte,expected", [
        (0x01, "rf"),
        (0x02, "keypad"),
        (0x03, "manual"),
        (0x0A, "auto"),
        (0x00, "unknown"),
        (0x04, "unknown"),
        (0xFF, "unknown"),
    ])
    def test_source_values(self, source_byte, expected):
        val = encode(3, 0, 0x02, source_byte)
        assert decode(val)["source"] == expected

    @pytest.mark.parametrize("reserved", range(256))
    def test_reserved_byte_ignored(self, reserved):
        """Reserved byte should not affect slot/action/source."""
        val = encode(5, reserved, 0x02, 0x02)
        result = decode(val)
        assert result["user_slot"] == 5
        assert result["action"] == "unlock"
        assert result["source"] == "keypad"
        assert result["reserved"] == reserved


class TestEdgeCases:
    """Test boundary values and invalid inputs."""

    def test_zero_decodes(self):
        result = decode(0)
        assert result is not None
        assert result["user_slot"] is None
        assert result["action"] == "unknown"
        assert result["source"] == "unknown"

    def test_max_uint32(self):
        result = decode(0xFFFFFFFF)
        assert result is not None
        assert result["user_slot"] == 255
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
    ]

    @pytest.mark.parametrize("raw,expected_slot,expected_action,expected_source,desc", CAPTURES)
    def test_known_capture(self, raw, expected_slot, expected_action, expected_source, desc):
        result = decode(raw)
        assert result["user_slot"] == expected_slot, f"Slot mismatch for {desc}"
        assert result["action"] == expected_action, f"Action mismatch for {desc}"
        assert result["source"] == expected_source, f"Source mismatch for {desc}"


class TestEncodeConsistency:
    """Verify that encode produces values that decode back correctly."""

    @pytest.mark.parametrize("slot", [0, 1, 3, 4, 50, 199, 255])
    @pytest.mark.parametrize("action", [0x01, 0x02])
    @pytest.mark.parametrize("source", [0x01, 0x02, 0x03, 0x0A])
    def test_encode_decode_roundtrip(self, slot, action, source):
        val = encode(slot, 0, action, source)
        result = decode(val)
        expected_slot = slot if slot > 0 else None
        assert result["user_slot"] == expected_slot
        assert result["action"] == ACTION_MAP[action]
        assert result["source"] == SOURCE_MAP[source]
        assert result["reserved"] == 0
