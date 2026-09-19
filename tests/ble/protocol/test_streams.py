"""protocol/streams.py: the little-endian field reader and writer.
"""
from __future__ import annotations

import pytest

from ...conftest import load_component_module
from .. import vectors

errors = load_component_module("ble.errors")
streams = load_component_module("ble.protocol.streams")


class TestByteReader:
    def test_reads_little_endian(self):
        reader = streams.ByteReader(bytes.fromhex("01 34 12 78 56 34 12 AA BB CC"))
        assert reader.read_uint8() == 0x01
        assert reader.read_uint16() == 0x1234
        assert reader.read_uint32() == 0x12345678
        assert reader.remaining == 3
        assert reader.read_bytes(2) == b"\xaa\xbb"
        assert reader.read_rest() == b"\xcc"
        assert reader.remaining == 0
        assert reader.read_bytes(0) == b""

    def test_reading_past_the_end(self):
        reader = streams.ByteReader(b"\x01")
        with pytest.raises(errors.BleProtocolError, match="Tried to read 2 byte"):
            reader.read_uint16()

    def test_negative_count_is_a_bug(self):
        with pytest.raises(errors.BleValidationError):
            streams.ByteReader(b"\x01").read_bytes(-1)

    def test_string_field(self):
        reader = streams.ByteReader(b"Door\x00\x00\x00\x00\x00rest")
        assert reader.read_string(9) == "Door"
        assert reader.read_rest() == b"rest"

    def test_string_field_needs_a_terminator(self):
        with pytest.raises(errors.BleProtocolError, match="NUL"):
            streams.ByteReader(b"ABCD").read_string(4)

    def test_string_field_replaces_non_ascii_like_java(self):
        assert streams.ByteReader(b"A\xffB\x00").read_string(4) == "A�B"


class TestByteWriter:
    def test_writes_little_endian(self):
        writer = streams.ByteWriter().write_uint8(1).write_uint16(0x1234).write_uint32(0x12345678)
        writer.write_bytes(b"\xaa").write_raw_string("88")
        assert writer.to_bytes() == bytes.fromhex("01 34 12 78 56 34 12 AA 38 38")
        assert len(writer) == 10

    @pytest.mark.parametrize(
        ("method", "value"),
        [("write_uint8", 256), ("write_uint8", -1), ("write_uint16", 0x10000), ("write_uint32", 1 << 32)],
    )
    def test_refuses_what_java_would_truncate(self, method, value):
        with pytest.raises(errors.BleValidationError, match="does not fit"):
            getattr(streams.ByteWriter(), method)(value)

    def test_raw_string_must_be_ascii_and_is_not_quoted(self):
        with pytest.raises(errors.BleValidationError) as info:
            streams.ByteWriter().write_raw_string("88٣2")
        assert "88" not in str(info.value)
        # Checked up front, so no UnicodeEncodeError holding the text rides along.
        assert info.value.__context__ is None

    def test_fixed_string(self):
        assert streams.ByteWriter().write_string("Door", 9).to_bytes() == vectors.DEVICE_NAME_SET_DOOR_PAYLOAD
        assert streams.ByteWriter().write_string("", 2).to_bytes() == b"\x00\x00"

    def test_fixed_string_keeps_room_for_the_terminator(self):
        streams.ByteWriter().write_string("12345678", 9)
        with pytest.raises(errors.BleValidationError, match="does not fit"):
            streams.ByteWriter().write_string("123456789", 9)
        with pytest.raises(errors.BleValidationError, match="ASCII"):
            streams.ByteWriter().write_string("Dør", 9)
