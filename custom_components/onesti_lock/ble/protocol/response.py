"""Layer 3: responses, the payload of the packets the lock sends.

    [response id:1][payload length:1][command ref:1][status:1][payload]

(communication/responses/Response.java). A response answers the command with
the same ref and, except for the key exchange, the same id. The lock also
sends events nobody asked for, LockStatus and UserAdded, under the ref
EVENT_COMMAND_REF. The typed payloads are parsed in responses.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from ..errors import BleProtocolError, error_for_status
from .const import RESPONSE_HEADER_SIZE, CommandId, ResponseId, ResponseStatusId
from .streams import ByteReader, ByteWriter

# NimlyEkeyDevice.responseHandler only reads LockStatus and UserAdded from a
# response whose CommandRef is 128. The command ref counter stops at 127, so
# no answer to a command collides with it; the static ref old firmware gets
# is 16.
EVENT_COMMAND_REF: Final = 0x80


def expected_response_id(command_id: CommandId) -> ResponseId:
    """The id a response to command_id carries.

    ExchangeKeyPubM (0x01) is answered by ExchangeKeyPubL under the same
    value; every other command by the response of the same name and value.
    """
    return ResponseId(command_id.value)


def _known[E: (ResponseId, ResponseStatusId)](enum: type[E], value: int) -> E | int:
    try:
        return enum(value)
    except ValueError:
        return value


@dataclass(frozen=True, slots=True)
class Response:
    """One Layer 3 response.

    response_id and status stay raw ints when they are not a known value: a
    newer firmware's answer should still parse and fail by its status, not by
    an unknown byte. The payload stays out of repr, like every other frame
    here.
    """

    response_id: ResponseId | int
    command_ref: int
    status: ResponseStatusId | int
    payload: bytes = field(default=b"", repr=False)

    @property
    def ok(self) -> bool:
        return self.status == ResponseStatusId.SUCCESS

    @property
    def is_event(self) -> bool:
        return self.command_ref == EVENT_COMMAND_REF

    def raise_for_status(self) -> None:
        """Raise the BleOperationError subclass for a failed status."""
        if not self.ok:
            raise error_for_status(self.status, self.response_id)

    def to_bytes(self) -> bytes:
        """Serialize, as the lock does; tests use it to play the lock."""
        return (
            ByteWriter()
            .write_uint8(self.response_id)
            .write_uint8(len(self.payload))
            .write_uint8(self.command_ref)
            .write_uint8(self.status)
            .write_bytes(self.payload)
            .to_bytes()
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> Response:
        """Parse a response payload from the lock.

        Bytes after the declared payload are ignored, as Response.deserialize
        ignores them; after decryption they are the cipher's zero padding.
        """
        reader = ByteReader(data)
        if reader.remaining < RESPONSE_HEADER_SIZE:
            raise BleProtocolError(
                f"Response of {len(data)} byte(s) is shorter than its {RESPONSE_HEADER_SIZE}-byte header"
            )
        response_id = _known(ResponseId, reader.read_uint8())
        length = reader.read_uint8()
        command_ref = reader.read_uint8()
        status = _known(ResponseStatusId, reader.read_uint8())
        return cls(response_id, command_ref, status, reader.read_bytes(length))
