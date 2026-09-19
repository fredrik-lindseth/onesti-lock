"""Layer 1: packets on the GATT characteristic, and the link that carries them.

Every write to and notification from the communication characteristic is one
packet (communication/packets/Packet.java):

    [type:1][length:1][rfu:1][sequence:1][payload:length]

PacketStream does what the app's PayloadStream does, minus the Bluetooth I/O:
it cuts an outgoing payload into packets that fit the MTU (one Single packet,
or a BlobStart/BlobStream.../BlobComplete run), and it puts incoming packets
back together into payloads. What it does not know is what a payload means;
that is Layer 2 (command.py) and Layer 3 (response.py).

Encryption plugs in here, where the app plugs in its IEncrypter: give
PacketStream a PayloadCipher and it encrypts every outgoing payload before
framing it and decrypts every incoming one after reassembly. Nothing else in
this module changes when a cipher is set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Protocol

from ..errors import BleProtocolError
from .blob import BLOB_LENGTH_MAX, BlobAssembler, BlobHeader
from .const import (
    ATT_OVERHEAD,
    BLOB_HEADER_SIZE,
    DEFAULT_MTU,
    FIRST_SEQUENCE_NUMBER,
    PACKET_HEADER_SIZE,
    PACKET_PAYLOAD_MAX,
    PacketTypeId,
)
from .streams import ByteReader, ByteWriter

# The smallest MTU that leaves a BlobStart packet room for one byte of payload
# after the ATT, packet and blob headers.
MTU_MIN: Final = ATT_OVERHEAD + PACKET_HEADER_SIZE + BLOB_HEADER_SIZE + 1


@dataclass(frozen=True, slots=True)
class Packet:
    """One Layer 1 packet.

    The payload stays out of repr: before the key exchange a packet can carry
    a plaintext command, and PinCodeSet puts the PIN in it.
    """

    packet_type: PacketTypeId
    sequence_number: int
    payload: bytes = field(default=b"", repr=False)
    rfu: int = 0

    def to_bytes(self) -> bytes:
        if len(self.payload) > PACKET_PAYLOAD_MAX:
            raise ValueError(f"Packet payload of {len(self.payload)} bytes exceeds {PACKET_PAYLOAD_MAX}")
        return (
            ByteWriter()
            .write_uint8(self.packet_type)
            .write_uint8(len(self.payload))
            .write_uint8(self.rfu)
            .write_uint8(self.sequence_number)
            .write_bytes(self.payload)
            .to_bytes()
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> Packet:
        """Parse one notification.

        Bytes after the declared payload are ignored, as Packet.fromData
        ignores them.
        """
        reader = ByteReader(data)
        if reader.remaining < PACKET_HEADER_SIZE:
            raise BleProtocolError(f"Packet of {len(data)} byte(s) is shorter than its {PACKET_HEADER_SIZE}-byte header")
        raw_type = reader.read_uint8()
        try:
            packet_type = PacketTypeId(raw_type)
        except ValueError:
            raise BleProtocolError(f"Unknown packet type 0x{raw_type:02X}") from None
        length = reader.read_uint8()
        rfu = reader.read_uint8()
        sequence_number = reader.read_uint8()
        return cls(packet_type, sequence_number, reader.read_bytes(length), rfu)

    def __len__(self) -> int:
        return PACKET_HEADER_SIZE + len(self.payload)


def _packet_room(mtu: int) -> int:
    """Payload bytes one packet can carry (PayloadStream.getPayloadMax(4)).

    Capped at what the one-byte length field can say. The app asks for MTU 23
    and never meets the cap; it would fail on a larger MTU where this splits.
    """
    if mtu < MTU_MIN:
        raise ValueError(f"MTU {mtu} is too small; the protocol needs at least {MTU_MIN}")
    return min(mtu - ATT_OVERHEAD - PACKET_HEADER_SIZE, PACKET_PAYLOAD_MAX)


def packetize(payload: bytes, *, encrypted: bool, mtu: int = DEFAULT_MTU) -> list[Packet]:
    """Cut one Layer 2 payload into the packets that carry it.

    PayloadStream sends a payload as a single packet only when its length
    plus 4 fits one packet, so at MTU 23 anything over 12 bytes goes as a
    blob, and since an encrypted payload is padded to 16 bytes, every
    encrypted command does. The blob's first chunk shares its packet with the
    blob header; later chunks fill whole packets. Sequence numbers run from 1
    for each payload.
    """
    if not payload:
        raise ValueError("Cannot send an empty payload")
    room = _packet_room(mtu)
    sequence = FIRST_SEQUENCE_NUMBER

    if len(payload) + PACKET_HEADER_SIZE <= room:
        single = PacketTypeId.SINGLE_ENCRYPTED if encrypted else PacketTypeId.SINGLE
        return [Packet(single, sequence, payload)]

    if len(payload) > BLOB_LENGTH_MAX:
        raise ValueError(f"Payload of {len(payload)} bytes exceeds the blob limit of {BLOB_LENGTH_MAX}")
    first = room - BLOB_HEADER_SIZE
    header = BlobHeader.for_payload(len(payload), encrypted=encrypted)
    packets = [Packet(PacketTypeId.BLOB_START, sequence, header.to_bytes() + payload[:first])]
    # The first chunk never holds the whole payload: a payload that small goes
    # as a single packet above, so at least a BlobComplete follows.
    position = first
    while position < len(payload):
        sequence = (sequence + 1) & 0xFF
        chunk = payload[position : position + room]
        position += len(chunk)
        packet_type = PacketTypeId.BLOB_COMPLETE if position == len(payload) else PacketTypeId.BLOB_STREAM
        packets.append(Packet(packet_type, sequence, chunk))
    return packets


class PayloadCipher(Protocol):
    """What PacketStream needs from an encrypter (crypto/encrypters/IEncrypter.java).

    encrypt pads to the cipher's block size; decrypt returns the padded
    plaintext, which Layer 2 and 3 tolerate since they read their own length
    field. Each payload goes through the cipher exactly once, as a whole: the
    app's AES runs one CBC pass per payload from the link IV, so encrypting
    packet by packet would give different bytes.
    """

    def encrypt(self, data: bytes) -> bytes: ...

    def decrypt(self, data: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ReceivedPayload:
    """One whole payload from the lock.

    encrypted is what the packet type or blob flag said. When the stream has
    a cipher, data is decrypted whatever that flag says, as the app does.
    """

    data: bytes = field(repr=False)
    encrypted: bool


class PacketStream:
    """Framing and reassembly for one connection.

    frame() turns an outgoing payload into the bytes to write, one write per
    packet. receive() takes each notification and returns a ReceivedPayload
    once one is whole, the Packet itself for ACK/NAC/ERROR, and None while a
    blob is still arriving.

    A packet that breaks the sequence (a Single inside a blob, a blob chunk
    with no blob, a skipped sequence number, a length mismatch) raises
    BleProtocolError and drops the blob in progress, the way PayloadStream
    resets to WaitStart. The next BlobStart or Single starts clean.
    """

    def __init__(self, *, mtu: int = DEFAULT_MTU, cipher: PayloadCipher | None = None) -> None:
        _packet_room(mtu)
        self.mtu = mtu
        # Set once the key exchange has produced the link key, as the app
        # calls setEncrypter on its stream.
        self.cipher = cipher
        self._blob: BlobAssembler | None = None
        self._last_sequence = 0

    @property
    def receiving_blob(self) -> bool:
        return self._blob is not None

    def frame(self, payload: bytes) -> list[bytes]:
        """The writes that send payload, encrypted first when there is a cipher."""
        if self.cipher is not None:
            payload = self.cipher.encrypt(payload)
        return [packet.to_bytes() for packet in packetize(payload, encrypted=self.cipher is not None, mtu=self.mtu)]

    def reset(self) -> None:
        """Forget a blob in progress, as after a reconnect."""
        self._blob = None
        self._last_sequence = 0

    def receive(self, data: bytes) -> ReceivedPayload | Packet | None:
        try:
            packet = Packet.from_bytes(data)
            return self._receive(packet)
        except BleProtocolError:
            self.reset()
            raise

    def _receive(self, packet: Packet) -> ReceivedPayload | Packet | None:
        match packet.packet_type:
            case PacketTypeId.SINGLE | PacketTypeId.SINGLE_ENCRYPTED:
                self._expect_no_blob(packet)
                return self._deliver(packet.payload, encrypted=packet.packet_type is PacketTypeId.SINGLE_ENCRYPTED)
            case PacketTypeId.BLOB_START:
                self._expect_no_blob(packet)
                self._blob = BlobAssembler(packet.payload)
                self._last_sequence = packet.sequence_number
                return None
            case PacketTypeId.BLOB_STREAM:
                self._next_in_blob(packet).add(packet.payload)
                return None
            case PacketTypeId.BLOB_COMPLETE:
                blob = self._next_in_blob(packet)
                data = blob.complete(packet.payload)
                self.reset()
                return self._deliver(data, encrypted=blob.encrypted)
            case _:
                # ACK, NAC or ERROR, which carry no payload. The app hands them
                # to a status callback that nothing in it waits on, so what
                # the lock means by them is not traced.
                return packet

    def _expect_no_blob(self, packet: Packet) -> None:
        if self._blob is not None:
            raise BleProtocolError(f"{packet.packet_type.name} packet arrived in the middle of a blob")

    def _next_in_blob(self, packet: Packet) -> BlobAssembler:
        if self._blob is None:
            raise BleProtocolError(f"{packet.packet_type.name} packet arrived with no blob started")
        # Wraps with the one-byte field. The app compares without wrapping and
        # would refuse a blob of more than 255 packets; none that long is known.
        expected = (self._last_sequence + 1) & 0xFF
        if packet.sequence_number != expected:
            raise BleProtocolError(f"Expected sequence number {expected}, got {packet.sequence_number}")
        self._last_sequence = packet.sequence_number
        return self._blob

    def _deliver(self, data: bytes, *, encrypted: bool) -> ReceivedPayload:
        if self.cipher is not None:
            data = self.cipher.decrypt(data)
        return ReceivedPayload(data, encrypted)
