"""Blob framing: one payload spread over several Layer 1 packets.

A payload too long for one packet goes as a blob (communication/blobs/Blob.java,
PayloadStream.writeBlob). The BlobStart packet carries a 4-byte header and the
first chunk, BlobStream packets carry the middle chunks, and BlobComplete the
last one:

    BlobStart payload: [flags:1][total length:u16 LE][rfu:1][first chunk]

Bit 0 of flags says the reassembled payload is encrypted; the app sets nothing
else, and nothing here reads the other bits or rfu. The receiver refuses the
blob unless the chunks add up to exactly the declared length, as
Blob.fromBlobComplete does.

This module works on packet payloads, not packets; packet.py decides which
packet type carries which chunk.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..errors import BleProtocolError
from .const import BLOB_FLAG_ENCRYPTED, BLOB_HEADER_SIZE
from .streams import ByteReader, ByteWriter

# The header's length field is a uint16.
BLOB_LENGTH_MAX: Final = 0xFFFF


@dataclass(frozen=True, slots=True)
class BlobHeader:
    """The 4 bytes at the front of a BlobStart packet's payload."""

    length: int
    flags: int = 0
    rfu: int = 0

    @classmethod
    def for_payload(cls, length: int, *, encrypted: bool) -> BlobHeader:
        return cls(length=length, flags=BLOB_FLAG_ENCRYPTED if encrypted else 0)

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & BLOB_FLAG_ENCRYPTED)

    def to_bytes(self) -> bytes:
        return ByteWriter().write_uint8(self.flags).write_uint16(self.length).write_uint8(self.rfu).to_bytes()

    @classmethod
    def split(cls, start_payload: bytes) -> tuple[BlobHeader, bytes]:
        """The header of a BlobStart packet's payload, and the chunk after it."""
        if len(start_payload) < BLOB_HEADER_SIZE:
            raise BleProtocolError(
                f"BlobStart payload is {len(start_payload)} byte(s), shorter than the {BLOB_HEADER_SIZE}-byte header"
            )
        reader = ByteReader(start_payload)
        flags = reader.read_uint8()
        length = reader.read_uint16()
        rfu = reader.read_uint8()
        return cls(length=length, flags=flags, rfu=rfu), reader.read_rest()


class BlobAssembler:
    """Collects the chunks of one incoming blob.

    Created from the BlobStart packet's payload; add() takes each BlobStream
    chunk and complete() the BlobComplete chunk, returning the whole payload.
    A blob that grows past its declared length fails at once instead of at
    complete(), which is where the app notices; the outcome is the same.
    """

    def __init__(self, start_payload: bytes) -> None:
        self.header, first_chunk = BlobHeader.split(start_payload)
        self._buffer = bytearray()
        self._complete = False
        self._append(first_chunk)

    @property
    def encrypted(self) -> bool:
        return self.header.encrypted

    @property
    def received(self) -> int:
        return len(self._buffer)

    def _append(self, chunk: bytes) -> None:
        if self._complete:
            raise BleProtocolError("Blob already completed")
        if len(self._buffer) + len(chunk) > self.header.length:
            raise BleProtocolError(
                f"Blob overflows its declared length of {self.header.length} byte(s) "
                f"({len(self._buffer) + len(chunk)} received)"
            )
        self._buffer += chunk

    def add(self, chunk: bytes) -> None:
        self._append(chunk)

    def complete(self, chunk: bytes) -> bytes:
        self._append(chunk)
        if len(self._buffer) != self.header.length:
            raise BleProtocolError(
                f"Blob declared {self.header.length} byte(s) but carried {len(self._buffer)}"
            )
        self._complete = True
        return bytes(self._buffer)
