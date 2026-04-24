"""Tests for last-used PIN code decoding (attrid 0x0101).

Onesti reports the actual PIN digits used on the keypad as ASCII bytes.
Matches Z2M's onesti.ts converter behaviour for parity.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "onesti_lock"))

# Importer fra modulen uten å trekke inn hele HA
import importlib.util
_path = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "__init__.py"
)


def _load_decode_pin_code():
    """Load _decode_pin_code by parsing the source (avoids HA imports)."""
    import ast
    with open(_path) as f:
        source = f.read()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_decode_pin_code":
            # Compile just this function in an isolated namespace
            module = ast.Module(body=[node], type_ignores=[])
            code = compile(module, _path, "exec")
            ns: dict = {}
            exec(code, ns)
            return ns["_decode_pin_code"]
    raise RuntimeError("_decode_pin_code not found")


_decode = _load_decode_pin_code()


class TestPinCodeDecodingBCD:
    """BCD (packed-nibble) format — confirmed in NimlyPRO captures."""

    def test_bcd_4_digits(self):
        # PIN "5478" → nibbles 5,4,7,8 → bytes 0x54, 0x78
        assert _decode(b"\x54\x78") == "5478"

    def test_bcd_6_digits(self):
        # PIN "141141" → nibbles 1,4,1,1,4,1 → bytes 0x14, 0x11, 0x41
        assert _decode(b"\x14\x11\x41") == "141141"

    def test_bcd_with_trailing_null(self):
        assert _decode(b"\x54\x78\x00") == "5478"

    def test_bcd_list_form(self):
        assert _decode([0x54, 0x78]) == "5478"

    def test_bcd_bytearray(self):
        assert _decode(bytearray(b"\x12\x34\x56")) == "123456"


class TestPinCodeDecodingASCII:
    """ASCII format — seen in Z2M PR #11332 on some firmware."""

    def test_ascii_digits(self):
        # All bytes in 0x30-0x39 → ASCII
        assert _decode(b"\x31\x32\x33\x34") == "1234"

    def test_ascii_6_digits(self):
        assert _decode(b"141141") == "141141"

    def test_ascii_with_trailing_null(self):
        assert _decode(b"5478\x00") == "5478"

    def test_ascii_bytearray(self):
        assert _decode(bytearray(b"987654")) == "987654"


class TestPinCodeDecodingEdgeCases:
    def test_string_passthrough(self):
        assert _decode("1234") == "1234"

    def test_string_with_whitespace(self):
        assert _decode("  5478  ") == "5478"

    def test_none_returns_none(self):
        assert _decode(None) is None

    def test_empty_bytes_returns_none(self):
        assert _decode(b"") is None

    def test_only_null_padding_returns_none(self):
        assert _decode(b"\x00\x00\x00") is None

    def test_empty_string_returns_none(self):
        assert _decode("") is None

    def test_whitespace_only_returns_none(self):
        assert _decode("   ") is None

    def test_invalid_bcd_nibble_returns_none(self):
        # 0xAB has high nibble 0xA which is > 9 — not valid BCD
        assert _decode(b"\xab") is None


class TestLastPinCodeConstants:
    """Verify the attribute ID matches Z2M."""

    def test_attr_last_pin_code_is_0x0101(self):
        with open(_path) as f:
            source = f.read()
        assert "ATTR_LAST_PIN_CODE = 0x0101" in source
