"""Layer 2: commands, the payload of the packets the phone writes.

    [command id:1][payload length:1][command ref:1][rfu:1][payload]

(communication/commands/Command.java). The builders in commands.py produce a
CommandPayload, the id and body without a ref; the session gives it a ref from
a CommandRefCounter and serializes the Command.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import BleProtocolError, BleValidationError
from .const import (
    COMMAND_HEADER_SIZE,
    COMMAND_REF_COUNTER_WRAP,
    COMMAND_REF_MAX,
    COMMAND_REF_MIN,
    COMMAND_REF_STATIC,
    MIN_FIRMWARE_ADMIN,
    PACKET_PAYLOAD_MAX,
    CommandId,
    FirmwareVersion,
)
from .streams import ByteReader, ByteWriter


@dataclass(frozen=True, slots=True)
class CommandPayload:
    """What a command says, before it is given a ref.

    data is what the app's serializeCommand writes. It stays out of repr
    because PinCodeSet puts the PIN in it.
    """

    command_id: CommandId
    data: bytes = field(default=b"", repr=False)

    def with_ref(self, command_ref: int) -> Command:
        return Command(self.command_id, command_ref, self.data)


@dataclass(frozen=True, slots=True)
class Command:
    """One Layer 2 command. The payload stays out of repr, as in CommandPayload."""

    command_id: CommandId
    command_ref: int
    payload: bytes = field(default=b"", repr=False)
    rfu: int = 0

    def to_bytes(self) -> bytes:
        if not COMMAND_REF_MIN <= self.command_ref <= COMMAND_REF_MAX:
            raise BleValidationError(
                f"CommandRef {self.command_ref} is outside {COMMAND_REF_MIN}-{COMMAND_REF_MAX}"
            )
        if len(self.payload) > PACKET_PAYLOAD_MAX:
            raise BleValidationError(f"Command payload of {len(self.payload)} bytes exceeds {PACKET_PAYLOAD_MAX}")
        return (
            ByteWriter()
            .write_uint8(self.command_id)
            .write_uint8(len(self.payload))
            .write_uint8(self.command_ref)
            .write_uint8(self.rfu)
            .write_bytes(self.payload)
            .to_bytes()
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> Command:
        """Parse a command, as the lock does; tests use it to play the lock.

        Bytes after the declared payload are ignored, so a decrypted command
        with its zero padding parses.
        """
        reader = ByteReader(data)
        if reader.remaining < COMMAND_HEADER_SIZE:
            raise BleProtocolError(
                f"Command of {len(data)} byte(s) is shorter than its {COMMAND_HEADER_SIZE}-byte header"
            )
        raw_id = reader.read_uint8()
        try:
            command_id = CommandId(raw_id)
        except ValueError:
            raise BleProtocolError(f"Unknown command id 0x{raw_id:02X}") from None
        length = reader.read_uint8()
        command_ref = reader.read_uint8()
        rfu = reader.read_uint8()
        return cls(command_id, command_ref, reader.read_bytes(length), rfu)


class CommandRefCounter:
    """Hands out the CommandRef for each command (CommandStream.nextCommandRef).

    Firmware below 4.7.90 gets the static ref 16 on every command. Newer
    firmware gets a counter that starts at 1 and wraps from 127 back to 1. The
    lock tags its unsolicited events with 128 (see response.EVENT_COMMAND_REF),
    which the counter never reaches.
    """

    def __init__(self, *, static: bool) -> None:
        self.static = static
        self._next = COMMAND_REF_MIN

    @classmethod
    def for_firmware(cls, firmware: FirmwareVersion) -> CommandRefCounter:
        return cls(static=firmware < MIN_FIRMWARE_ADMIN)

    def next(self) -> int:
        if self.static:
            return COMMAND_REF_STATIC
        ref = self._next
        self._next = ref + 1 if ref + 1 < COMMAND_REF_COUNTER_WRAP else COMMAND_REF_MIN
        return ref
