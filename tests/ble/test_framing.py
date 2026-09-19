"""Layers 1-3: byte streams, packets, blobs, commands and responses.

Built frames are compared with the vectors in vectors.py, and parsed frames
are built again, so each layer is checked in both directions.
"""
from __future__ import annotations

import pytest

from ..conftest import load_component_module
from . import vectors

const = load_component_module("ble.const")
errors = load_component_module("ble.errors")
streams = load_component_module("ble.streams")
blob = load_component_module("ble.blob")
packet = load_component_module("ble.packet")
command = load_component_module("ble.command")
response = load_component_module("ble.response")

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


# --- streams.py ---------------------------------------------------------------


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
        with pytest.raises(ValueError):
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


# --- blob.py ------------------------------------------------------------------


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


# --- packet.py: Packet and packetize -----------------------------------------


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


# --- packet.py: PacketStream --------------------------------------------------


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
    """The seam Task B's AES encrypter plugs into, exercised with a stand-in."""

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


# --- command.py ---------------------------------------------------------------


class TestCommand:
    def test_documented_pin_payload_in_a_whole_command(self):
        payload = command.CommandPayload(const.CommandId.PIN_CODE_SET, vectors.PIN_CODE_SET_SLOT_803_PIN_8832_PAYLOAD)
        built = payload.with_ref(16).to_bytes()
        assert built == vectors.PIN_CODE_SET_SLOT_803_PIN_8832_REF_16_COMMAND
        assert built.hex(" ") == "52 07 10 00 23 03 04 38 38 33 32"

    @pytest.mark.parametrize(
        "name",
        ["USER_AUTH_BEGIN_DEFAULT_REF_1_COMMAND", "BATT_INFO_GET_REF_1_COMMAND", "EXCHANGE_KEY_PUB_M_REF_1_COMMAND"],
    )
    def test_round_trip(self, name):
        frame = getattr(vectors, name)
        parsed = command.Command.from_bytes(frame)
        assert parsed.to_bytes() == frame

    def test_parse_ignores_padding(self):
        padded = vectors.PIN_CODE_SET_SLOT_803_PIN_8832_REF_16_COMMAND + bytes(5)
        parsed = command.Command.from_bytes(padded)
        assert (parsed.command_id, parsed.command_ref) == (const.CommandId.PIN_CODE_SET, 16)
        assert parsed.payload == vectors.PIN_CODE_SET_SLOT_803_PIN_8832_PAYLOAD

    @pytest.mark.parametrize("ref", [0, 255, -1])
    def test_ref_range(self, ref):
        with pytest.raises(ValueError, match="CommandRef"):
            command.Command(const.CommandId.BATT_INFO_GET, ref).to_bytes()

    def test_ref_bounds_are_accepted(self):
        assert command.Command(const.CommandId.BATT_INFO_GET, 1).to_bytes()[2] == 1
        assert command.Command(const.CommandId.BATT_INFO_GET, 254).to_bytes()[2] == 254

    def test_payload_limit(self):
        with pytest.raises(ValueError, match="exceeds 255"):
            command.Command(const.CommandId.EXCHANGE_KEY_PUB_M, 1, bytes(256)).to_bytes()

    @pytest.mark.parametrize(
        ("data", "message"),
        [(b"\x52\x00\x01", "shorter than its 4-byte header"), (b"\x99\x00\x01\x00", "Unknown command id 0x99")],
    )
    def test_malformed(self, data, message):
        with pytest.raises(errors.BleProtocolError, match=message):
            command.Command.from_bytes(data)

    def test_reprs_leave_the_payload_out(self):
        payload = command.CommandPayload(const.CommandId.PIN_CODE_SET, vectors.PIN_CODE_SET_SLOT_803_PIN_8832_PAYLOAD)
        for obj in (payload, payload.with_ref(1)):
            text = repr(obj)
            assert "8832" not in text and "88" not in text
            assert "PIN_CODE_SET" in text


class TestCommandRefCounter:
    def test_counter_runs_1_to_127_and_wraps(self):
        counter = command.CommandRefCounter(static=False)
        refs = [counter.next() for _ in range(130)]
        assert refs[:3] == [1, 2, 3]
        assert refs[126] == 127
        assert refs[127:] == [1, 2, 3]
        assert response.EVENT_COMMAND_REF not in refs

    def test_static_ref(self):
        counter = command.CommandRefCounter(static=True)
        assert {counter.next() for _ in range(5)} == {16}

    @pytest.mark.parametrize(
        ("firmware", "static"),
        [((4, 6, 0), True), ((4, 7, 89), True), ((4, 7, 90), False), ((5, 0, 0), False)],
    )
    def test_for_firmware(self, firmware, static):
        assert command.CommandRefCounter.for_firmware(firmware).static is static


# --- response.py --------------------------------------------------------------


class TestResponse:
    def test_parse(self):
        parsed = response.Response.from_bytes(vectors.BATT_INFO_GET_REF_1_RESPONSE)
        assert parsed.response_id is const.ResponseId.BATT_INFO_GET
        assert parsed.command_ref == 1
        assert parsed.status is const.ResponseStatusId.SUCCESS
        assert parsed.payload == bytes.fromhex("A8 16 00 50")
        assert parsed.ok and not parsed.is_event
        parsed.raise_for_status()
        assert parsed.to_bytes() == vectors.BATT_INFO_GET_REF_1_RESPONSE

    def test_padding_after_the_payload_is_ignored(self):
        padded = vectors.PIN_CODE_SET_SUCCESS_REF_1_RESPONSE + bytes(12)
        assert response.Response.from_bytes(padded).to_bytes() == vectors.PIN_CODE_SET_SUCCESS_REF_1_RESPONSE

    def test_failed_status_raises_the_mapped_error(self):
        parsed = response.Response.from_bytes(vectors.PIN_CODE_CLEAR_NOT_FOUND_REF_1_RESPONSE)
        assert not parsed.ok
        with pytest.raises(errors.BleNotFoundError) as info:
            parsed.raise_for_status()
        assert info.value.command is const.ResponseId.PIN_CODE_CLEAR

    def test_unknown_id_and_status_stay_raw(self):
        parsed = response.Response.from_bytes(bytes.fromhex("99 00 05 42"))
        assert (parsed.response_id, parsed.status) == (0x99, 0x42)
        assert type(parsed.response_id) is int and type(parsed.status) is int
        with pytest.raises(errors.BleOperationError, match="0x42"):
            parsed.raise_for_status()
        assert parsed.to_bytes() == bytes.fromhex("99 00 05 42")

    def test_event_ref(self):
        assert response.EVENT_COMMAND_REF == 128
        assert response.Response.from_bytes(vectors.LOCK_STATUS_SLOT_803_UNLOCKED_PANEL_RESPONSE).is_event

    @pytest.mark.parametrize(
        ("data", "message"),
        [(b"\x5d\x04\x01", "shorter than its 4-byte header"), (b"\x5d\x04\x01\x00\xa8", "Tried to read 4 byte")],
    )
    def test_malformed(self, data, message):
        with pytest.raises(errors.BleProtocolError, match=message):
            response.Response.from_bytes(data)

    def test_expected_response_id(self):
        assert response.expected_response_id(const.CommandId.EXCHANGE_KEY_PUB_M) is const.ResponseId.EXCHANGE_KEY_PUB_L
        for command_id in const.CommandId:
            assert response.expected_response_id(command_id).value == command_id.value


class TestLayersTogether:
    def test_pin_command_through_every_layer_and_back(self):
        """Builder -> Layer 2 -> Layer 1 -> wire -> Layer 1 -> Layer 2, as the lock would read it."""
        commands = load_component_module("ble.commands")
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
