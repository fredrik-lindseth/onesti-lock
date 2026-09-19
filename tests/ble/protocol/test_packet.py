"""protocol/packet.py: Layer 1 packets, packetizing, and the stream that reassembles them.

The last tests run a frame through every layer and back, since the packet
stream is where the layers meet.
"""
from __future__ import annotations

import pytest

from ...conftest import load_component_module
from .. import vectors

const = load_component_module("ble.protocol.const")
errors = load_component_module("ble.errors")
blob = load_component_module("ble.protocol.blob")
packet = load_component_module("ble.protocol.packet")
command = load_component_module("ble.protocol.command")
response = load_component_module("ble.protocol.response")

PacketTypeId = const.PacketTypeId


class XorCipher:
    """Stands in for the AES encrypter: pads to 16 and XORs with a key byte.

    Counts calls, so a test can see each payload pass through exactly once.
    """

    def __init__(self, key: int = 0x5A) -> None:
        self.key = key
        self.encrypted = 0
        self.decrypted = 0

    def encrypt(self, data: bytes) -> bytes:
        self.encrypted += 1
        padded = data + bytes(-len(data) % 16)
        return bytes(b ^ self.key for b in padded)

    def decrypt(self, data: bytes) -> bytes:
        self.decrypted += 1
        return bytes(b ^ self.key for b in data)


class TestPacket:
    def test_single_vector_round_trip(self):
        parsed = packet.Packet.from_bytes(vectors.BATT_INFO_GET_SINGLE_PACKET)
        assert parsed.packet_type is PacketTypeId.SINGLE
        assert parsed.sequence_number == 1
        assert parsed.payload == vectors.BATT_INFO_GET_REF_1_COMMAND
        assert len(parsed) == len(vectors.BATT_INFO_GET_SINGLE_PACKET)
        assert parsed.to_bytes() == vectors.BATT_INFO_GET_SINGLE_PACKET

    def test_trailing_bytes_are_ignored_like_the_app(self):
        parsed = packet.Packet.from_bytes(vectors.BATT_INFO_GET_SINGLE_PACKET + b"\x00\x00")
        assert parsed.to_bytes() == vectors.BATT_INFO_GET_SINGLE_PACKET

    def test_status_packet_has_no_payload(self):
        assert packet.Packet(PacketTypeId.ERROR, 3).to_bytes() == bytes.fromhex("F0 00 00 03")

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            (b"\x01\x00\x00", "shorter than its 4-byte header"),
            (b"\x09\x00\x00\x01", "Unknown packet type 0x09"),
            (b"\x01\x05\x00\x01abc", "Tried to read 5 byte"),
        ],
    )
    def test_malformed(self, data, message):
        with pytest.raises(errors.BleProtocolError, match=message):
            packet.Packet.from_bytes(data)

    def test_payload_limit(self):
        packet.Packet(PacketTypeId.SINGLE, 1, bytes(255)).to_bytes()
        with pytest.raises(ValueError, match="exceeds 255"):
            packet.Packet(PacketTypeId.SINGLE, 1, bytes(256)).to_bytes()

    def test_repr_leaves_the_payload_out(self):
        pin_frame = vectors.PIN_CODE_SET_SLOT_803_PIN_8832_REF_16_COMMAND
        text = repr(packet.Packet(PacketTypeId.SINGLE, 1, pin_frame))
        assert "8832" not in text and "payload" not in text


class TestPacketize:
    def test_the_blob_vector(self):
        packets = packet.packetize(vectors.EXCHANGE_KEY_PUB_M_REF_1_COMMAND, encrypted=False)
        assert tuple(p.to_bytes() for p in packets) == vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23

    def test_the_encrypted_blob_vector(self):
        packets = packet.packetize(vectors.ENCRYPTED_16_BYTES, encrypted=True)
        assert tuple(p.to_bytes() for p in packets) == vectors.ENCRYPTED_16_BYTES_BLOB_PACKETS_MTU_23

    def test_the_single_vector(self):
        (single,) = packet.packetize(vectors.BATT_INFO_GET_REF_1_COMMAND, encrypted=False)
        assert single.to_bytes() == vectors.BATT_INFO_GET_SINGLE_PACKET

    def test_twelve_bytes_is_the_largest_single_at_mtu_23(self):
        # PayloadStream: blob when length + 4 > MTU - 3 - 4.
        (single,) = packet.packetize(bytes(12), encrypted=True)
        assert single.packet_type is PacketTypeId.SINGLE_ENCRYPTED
        start, complete = packet.packetize(bytes(13), encrypted=False)
        assert (start.packet_type, len(start.payload)) == (PacketTypeId.BLOB_START, 16)
        assert (complete.packet_type, complete.payload) == (PacketTypeId.BLOB_COMPLETE, b"\x00")

    @pytest.mark.parametrize("length", [13, 16, 28, 29, 68, 300, 4096])
    @pytest.mark.parametrize("mtu", [12, 23, 64, 247, 517])
    def test_fits_every_write_and_reassembles(self, length, mtu):
        payload = bytes(i & 0xFF for i in range(length))
        packets = packet.packetize(payload, encrypted=False, mtu=mtu)
        writes = [p.to_bytes() for p in packets]
        assert all(len(w) <= mtu - const.ATT_OVERHEAD for w in writes)
        assert [p.sequence_number for p in packets] == [(1 + i) & 0xFF for i in range(len(packets))]
        stream = packet.PacketStream(mtu=mtu)
        results = [stream.receive(w) for w in writes]
        assert results[:-1] == [None] * (len(writes) - 1)
        assert results[-1] == packet.ReceivedPayload(payload, False)

    def test_large_mtu_is_capped_at_the_length_field(self):
        packets = packet.packetize(bytes(600), encrypted=False, mtu=517)
        assert max(len(p.payload) for p in packets) == 255

    def test_limits(self):
        with pytest.raises(ValueError, match="empty"):
            packet.packetize(b"", encrypted=False)
        with pytest.raises(ValueError, match="MTU 11 is too small"):
            packet.packetize(b"x", encrypted=False, mtu=11)
        with pytest.raises(ValueError, match="blob limit"):
            packet.packetize(bytes(0x10000), encrypted=False)
        assert packet.MTU_MIN == 12


class TestPacketStream:
    def test_frame_without_cipher(self):
        stream = packet.PacketStream()
        assert stream.frame(vectors.BATT_INFO_GET_REF_1_COMMAND) == [vectors.BATT_INFO_GET_SINGLE_PACKET]
        assert stream.frame(vectors.EXCHANGE_KEY_PUB_M_REF_1_COMMAND) == list(
            vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23
        )

    def test_receive_single(self):
        stream = packet.PacketStream()
        assert stream.receive(vectors.BATT_INFO_GET_SINGLE_PACKET) == packet.ReceivedPayload(
            vectors.BATT_INFO_GET_REF_1_COMMAND, False
        )
        assert stream.receive(bytes.fromhex("02 01 00 09 AB")) == packet.ReceivedPayload(b"\xab", True)

    def test_receive_blob(self):
        stream = packet.PacketStream()
        *head, last = vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23
        for write in head:
            assert stream.receive(write) is None
            assert stream.receiving_blob
        assert stream.receive(last) == packet.ReceivedPayload(vectors.EXCHANGE_KEY_PUB_M_REF_1_COMMAND, False)
        assert not stream.receiving_blob

    def test_blob_start_sequence_is_not_checked_but_followed(self):
        # PayloadStream takes BlobStart's number as given and checks the rest
        # against it.
        stream = packet.PacketStream()
        payload = bytes(range(20))
        start, complete = packet.packetize(payload, encrypted=False)
        shifted = [
            packet.Packet(start.packet_type, 200, start.payload),
            packet.Packet(complete.packet_type, 201, complete.payload),
        ]
        assert stream.receive(shifted[0].to_bytes()) is None
        assert stream.receive(shifted[1].to_bytes()).data == payload

    def test_sequence_wraps_with_the_byte(self):
        stream = packet.PacketStream()
        start, complete = packet.packetize(bytes(20), encrypted=False)
        stream.receive(packet.Packet(start.packet_type, 255, start.payload).to_bytes())
        assert stream.receive(packet.Packet(complete.packet_type, 0, complete.payload).to_bytes()).data == bytes(20)

    def test_status_packets_pass_through(self):
        stream = packet.PacketStream()
        for packet_type in (PacketTypeId.ACK, PacketTypeId.NAC, PacketTypeId.ERROR):
            received = stream.receive(packet.Packet(packet_type, 1).to_bytes())
            assert received == packet.Packet(packet_type, 1)

    def test_status_packet_does_not_break_a_blob(self):
        stream = packet.PacketStream()
        first, *rest = vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23
        stream.receive(first)
        stream.receive(packet.Packet(PacketTypeId.ACK, 1).to_bytes())
        results = [stream.receive(write) for write in rest]
        assert results[-1].data == vectors.EXCHANGE_KEY_PUB_M_REF_1_COMMAND

    @pytest.mark.parametrize(
        ("broken", "message"),
        [
            (lambda p: p[:1] + p[2:3], "Expected sequence number 2, got 3"),
            (lambda p: p[:1] + [vectors.BATT_INFO_GET_SINGLE_PACKET], "SINGLE packet arrived in the middle of a blob"),
            (lambda p: p[:1] + [p[0]], "BLOB_START packet arrived in the middle of a blob"),
            (lambda p: p[1:2], "BLOB_STREAM packet arrived with no blob started"),
            (lambda p: p[4:5], "BLOB_COMPLETE packet arrived with no blob started"),
            (lambda p: p[:1] + [bytes.fromhex("05 01 00 02 00")], "declared 68 byte"),
            (lambda p: [bytes.fromhex("03 03 00 01 00 44 00")], "shorter than the 4-byte header"),
            (lambda p: [b"\x99\x00\x00\x01"], "Unknown packet type"),
        ],
    )
    def test_broken_sequences_raise_and_reset(self, broken, message):
        stream = packet.PacketStream()
        writes = broken(list(vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23))
        with pytest.raises(errors.BleProtocolError, match=message):
            for write in writes:
                stream.receive(write)
        assert not stream.receiving_blob
        # The stream starts clean on the next payload, as PayloadStream does
        # after resetting to WaitStart.
        results = [stream.receive(write) for write in vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23]
        assert results[-1].data == vectors.EXCHANGE_KEY_PUB_M_REF_1_COMMAND

    def test_reset_drops_a_blob(self):
        stream = packet.PacketStream()
        stream.receive(vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23[0])
        stream.reset()
        assert not stream.receiving_blob
        with pytest.raises(errors.BleProtocolError, match="no blob started"):
            stream.receive(vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23[1])

    def test_mtu_is_checked_up_front(self):
        with pytest.raises(ValueError, match="too small"):
            packet.PacketStream(mtu=7)


class TestCipherHook:
    """The seam the AES cipher plugs into, exercised with a stand-in."""

    def test_outgoing_payload_is_encrypted_then_framed_as_an_encrypted_blob(self):
        cipher = XorCipher()
        stream = packet.PacketStream(cipher=cipher)
        writes = stream.frame(vectors.BATT_INFO_GET_REF_1_COMMAND)
        assert cipher.encrypted == 1
        # Four bytes pad to 16, and 16 is past the 12 a Single takes.
        assert [w[0] for w in writes] == [PacketTypeId.BLOB_START, PacketTypeId.BLOB_COMPLETE]
        header, _ = blob.BlobHeader.split(writes[0][4:])
        assert header.encrypted and header.length == 16

    def test_incoming_payload_is_decrypted_after_reassembly(self):
        cipher = XorCipher()
        lock_side = packet.PacketStream(cipher=XorCipher())
        phone_side = packet.PacketStream(cipher=cipher)
        answer = vectors.BATT_INFO_GET_REF_1_RESPONSE
        received = [phone_side.receive(write) for write in lock_side.frame(answer)]
        assert cipher.decrypted == 1
        result = received[-1]
        assert result.encrypted
        # The zero padding stays; Layer 3 reads its own length.
        assert result.data == answer + bytes(16 - len(answer))
        assert response.Response.from_bytes(result.data).payload == answer[4:]

    def test_single_is_decrypted_whatever_its_type_says(self):
        # PayloadStream.onReceivePayload decrypts every payload once it has an
        # encrypter, even one that came as a plain Single.
        stream = packet.PacketStream(cipher=XorCipher(key=0xFF))
        result = stream.receive(bytes.fromhex("01 02 00 01 00 FF"))
        assert result == packet.ReceivedPayload(b"\xff\x00", False)

    def test_cipher_can_be_set_after_the_key_exchange(self):
        stream = packet.PacketStream()
        assert stream.frame(vectors.BATT_INFO_GET_REF_1_COMMAND)[0][0] == PacketTypeId.SINGLE
        stream.cipher = XorCipher()
        assert stream.frame(vectors.BATT_INFO_GET_REF_1_COMMAND)[0][0] == PacketTypeId.BLOB_START


class TestLayersTogether:
    def test_pin_command_through_every_layer_and_back(self):
        """Builder -> Layer 2 -> Layer 1 -> wire -> Layer 1 -> Layer 2, as the lock would read it."""
        commands = load_component_module("ble.protocol.commands")
        payload = commands.pin_code_set(803, "8832")
        frame = payload.with_ref(16).to_bytes()
        assert frame == vectors.PIN_CODE_SET_SLOT_803_PIN_8832_REF_16_COMMAND
        phone, lock = packet.PacketStream(cipher=XorCipher()), packet.PacketStream(cipher=XorCipher())
        received = [lock.receive(write) for write in phone.frame(frame)]
        assert command.Command.from_bytes(received[-1].data) == payload.with_ref(16)

    def test_key_exchange_answer_arrives_as_a_blob(self):
        lock = packet.PacketStream()
        phone = packet.PacketStream()
        writes = lock.frame(vectors.EXCHANGE_KEY_PUB_L_REF_1_RESPONSE)
        assert len(writes) == 5
        received = [phone.receive(write) for write in writes][-1]
        parsed = response.Response.from_bytes(received.data)
        assert parsed.response_id is const.ResponseId.EXCHANGE_KEY_PUB_L
        assert parsed.payload == bytes(range(0x80, 0xC0))
