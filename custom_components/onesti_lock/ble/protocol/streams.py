"""Little-endian byte reader and writer for every frame in the protocol.

The app serializes and parses everything through LittleEndianStreamWriter and
LittleEndianStreamReader (communication/streams/). These are the same
operations, with two differences on purpose: the writer refuses a value that
does not fit its field instead of masking it the way Java casts do, and the
reader raises BleProtocolError, not a bare Exception.

Error messages carry sizes and positions only, never the bytes, since a
payload can hold a PIN.
"""
from __future__ import annotations

from ..errors import BleProtocolError, BleValidationError
from .const import CHARACTER_SET


class ByteReader:
    """Reads fields from the front of a byte string.

    A read past the end raises BleProtocolError. Bytes left over at the end are
    not an error by themselves: the app ignores them too, and a decrypted
    payload always ends in zero padding.
    """

    def __init__(self, data: bytes) -> None:
        self._data = bytes(data)
        self._pos = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    def _take(self, count: int) -> bytes:
        if count < 0:
            raise BleValidationError("Cannot read a negative number of bytes")
        if count > self.remaining:
            raise BleProtocolError(f"Tried to read {count} byte(s), but only {self.remaining} remain")
        start = self._pos
        self._pos += count
        return self._data[start : self._pos]

    def read_uint8(self) -> int:
        return self._take(1)[0]

    def read_uint16(self) -> int:
        return int.from_bytes(self._take(2), "little")

    def read_uint32(self) -> int:
        return int.from_bytes(self._take(4), "little")

    def read_bytes(self, count: int) -> bytes:
        return self._take(count)

    def read_rest(self) -> bytes:
        return self._take(self.remaining)

    def read_string(self, size: int) -> str:
        """A fixed-size field holding a NUL-terminated ASCII string.

        Like readString, a field with no NUL in it is an error. A byte outside
        ASCII becomes U+FFFD, as Java's decoder replaces it.
        """
        raw = self._take(size)
        end = raw.find(0)
        if end < 0:
            raise BleProtocolError(f"String field of {size} byte(s) has no NUL terminator")
        return raw[:end].decode(CHARACTER_SET, errors="replace")


class ByteWriter:
    """Builds a frame field by field."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def _write_uint(self, value: int, size: int) -> ByteWriter:
        if not 0 <= value < 1 << (8 * size):
            raise BleValidationError(f"Value {value} does not fit an unsigned {8 * size}-bit field")
        self._buffer += value.to_bytes(size, "little")
        return self

    def write_uint8(self, value: int) -> ByteWriter:
        return self._write_uint(value, 1)

    def write_uint16(self, value: int) -> ByteWriter:
        return self._write_uint(value, 2)

    def write_uint32(self, value: int) -> ByteWriter:
        return self._write_uint(value, 4)

    def write_bytes(self, data: bytes) -> ByteWriter:
        self._buffer += data
        return self

    def write_raw_string(self, text: str) -> ByteWriter:
        """The ASCII bytes of text, with no length prefix and no terminator.

        The error does not quote text: PinCodeSet writes the PIN this way. It
        is checked up front rather than by catching UnicodeEncodeError, which
        would keep the string in the new exception's __context__.
        """
        if not text.isascii():
            raise BleValidationError("String is not plain ASCII")
        return self.write_bytes(text.encode(CHARACTER_SET))

    def write_string(self, text: str, size: int) -> ByteWriter:
        """text in a fixed-size field, NUL-padded, leaving room for at least one NUL.

        writeString refuses anything that does not leave that room.
        """
        if not text.isascii():
            raise BleValidationError("String is not plain ASCII")
        if len(text) >= size:
            raise BleValidationError(f"String of {len(text)} characters does not fit a {size}-byte field")
        return self.write_bytes(text.encode(CHARACTER_SET).ljust(size, b"\0"))

    def to_bytes(self) -> bytes:
        return bytes(self._buffer)

    def __len__(self) -> int:
        return len(self._buffer)
