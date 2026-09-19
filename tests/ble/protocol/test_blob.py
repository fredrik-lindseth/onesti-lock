"""protocol/blob.py: the blob header and reassembly of incoming blobs.
"""
from __future__ import annotations

import pytest

from ...conftest import load_component_module
from .. import vectors

errors = load_component_module("ble.errors")
blob = load_component_module("ble.protocol.blob")


class TestBlobHeader:
    def test_round_trip(self):
        header = blob.BlobHeader.for_payload(0x44, encrypted=True)
        assert header.to_bytes() == bytes.fromhex("01 44 00 00")
        assert blob.BlobHeader.split(header.to_bytes() + b"xyz") == (header, b"xyz")
        assert header.encrypted
        assert not blob.BlobHeader.for_payload(1, encrypted=False).encrypted

    def test_other_flag_bits_and_rfu_are_kept_but_not_read(self):
        header, chunk = blob.BlobHeader.split(bytes.fromhex("FE 02 00 7F AB"))
        assert (header.flags, header.length, header.rfu, chunk) == (0xFE, 2, 0x7F, b"\xab")
        assert not header.encrypted

    def test_short_header(self):
        with pytest.raises(errors.BleProtocolError, match="shorter than the 4-byte header"):
            blob.BlobHeader.split(b"\x00\x10\x00")


class TestBlobAssembler:
    def test_reassembles_the_vector(self):
        packets = vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23
        assembler = blob.BlobAssembler(packets[0][4:])
        assert not assembler.encrypted
        for middle in packets[1:-1]:
            assembler.add(middle[4:])
        assert assembler.received == 60
        assert assembler.complete(packets[-1][4:]) == vectors.EXCHANGE_KEY_PUB_M_REF_1_COMMAND

    def test_short_blob_fails_at_complete(self):
        assembler = blob.BlobAssembler(bytes.fromhex("00 05 00 00") + b"ab")
        with pytest.raises(errors.BleProtocolError, match="declared 5 byte.*carried 4"):
            assembler.complete(b"cd")

    def test_overflow_fails_at_once(self):
        assembler = blob.BlobAssembler(bytes.fromhex("00 03 00 00") + b"ab")
        with pytest.raises(errors.BleProtocolError, match="overflows"):
            assembler.add(b"cd")

    def test_first_chunk_can_overflow(self):
        with pytest.raises(errors.BleProtocolError, match="overflows"):
            blob.BlobAssembler(bytes.fromhex("00 01 00 00") + b"ab")

    def test_nothing_after_complete(self):
        assembler = blob.BlobAssembler(bytes.fromhex("00 02 00 00") + b"a")
        assert assembler.complete(b"b") == b"ab"
        with pytest.raises(errors.BleProtocolError, match="already completed"):
            assembler.add(b"")
