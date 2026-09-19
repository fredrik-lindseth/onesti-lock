"""The test vectors agree with const.py and with themselves.

The builders and parsers are tested against these vectors in their own files.
This only makes sure a vector is not wrong before anything is compared with it:
header ids are the enum values, length bytes match the bytes that follow, and
the blob fragments put back together give the command they were cut from.
"""
from __future__ import annotations

import pytest

from ..conftest import load_component_module
from . import vectors

const = load_component_module("ble.const")

COMMANDS = {
    "PIN_CODE_SET_SLOT_803_PIN_8832_REF_16_COMMAND": (const.CommandId.PIN_CODE_SET, 16),
    "USER_AUTH_BEGIN_DEFAULT_REF_1_COMMAND": (const.CommandId.USER_AUTH_BEGIN, 1),
    "BATT_INFO_GET_REF_1_COMMAND": (const.CommandId.BATT_INFO_GET, 1),
    "EXCHANGE_KEY_PUB_M_REF_1_COMMAND": (const.CommandId.EXCHANGE_KEY_PUB_M, 1),
}

RESPONSES = {
    "PIN_CODE_SET_SUCCESS_REF_1_RESPONSE": (const.ResponseId.PIN_CODE_SET, const.ResponseStatusId.SUCCESS),
    "PIN_CODE_CLEAR_NOT_FOUND_REF_1_RESPONSE": (
        const.ResponseId.PIN_CODE_CLEAR,
        const.ResponseStatusId.NOT_FOUND_ERROR,
    ),
    "BATT_INFO_GET_REF_1_RESPONSE": (const.ResponseId.BATT_INFO_GET, const.ResponseStatusId.SUCCESS),
    "USER_AUTH_BEGIN_REF_1_RESPONSE": (const.ResponseId.USER_AUTH_BEGIN, const.ResponseStatusId.SUCCESS),
    "DEVICE_MODEL_GET_NIMLY_PRO_REF_1_RESPONSE": (const.ResponseId.DEVICE_MODEL_GET, const.ResponseStatusId.SUCCESS),
    "DEVICE_LOG_GET_REF_1_RESPONSE": (const.ResponseId.DEVICE_LOG_GET, const.ResponseStatusId.SUCCESS),
    "LOCK_STATUS_SLOT_803_UNLOCKED_PANEL_RESPONSE": (const.ResponseId.LOCK_STATUS, const.ResponseStatusId.SUCCESS),
    "USER_ADDED_SLOT_151_FINGERPRINT_RESPONSE": (const.ResponseId.USER_ADDED, const.ResponseStatusId.SUCCESS),
    "USER_AUTH_FINALIZE_REF_2_RESPONSE": (const.ResponseId.USER_AUTH_FINALIZE, const.ResponseStatusId.SUCCESS),
    "USER_AUTH_UPDATE_REF_3_RESPONSE": (const.ResponseId.USER_AUTH_UPDATE, const.ResponseStatusId.SUCCESS),
    "EXCHANGE_KEY_PUB_L_REF_1_RESPONSE": (const.ResponseId.EXCHANGE_KEY_PUB_L, const.ResponseStatusId.SUCCESS),
    "SERVER_KEY_UPDATE_REF_4_RESPONSE": (const.ResponseId.SERVER_KEY_UPDATE, const.ResponseStatusId.SUCCESS),
    "CURRENT_TIME_GET_REF_5_RESPONSE": (const.ResponseId.CURRENT_TIME_GET, const.ResponseStatusId.SUCCESS),
    "FINGERPRINT_SCAN_SLOT_150_NO_SPACE_REF_6_RESPONSE": (
        const.ResponseId.FINGERPRINT_SCAN,
        const.ResponseStatusId.SUCCESS,
    ),
    "DEVICE_NAME_GET_DOOR_REF_7_RESPONSE": (const.ResponseId.DEVICE_NAME_GET, const.ResponseStatusId.SUCCESS),
    "DEVICE_ID_GET_REF_8_RESPONSE": (const.ResponseId.DEVICE_ID_GET, const.ResponseStatusId.SUCCESS),
}


class TestCommandVectors:
    @pytest.mark.parametrize("name", COMMANDS)
    def test_header(self, name):
        frame = getattr(vectors, name)
        command_id, ref = COMMANDS[name]
        assert frame[0] == command_id
        assert frame[1] == len(frame) - const.COMMAND_HEADER_SIZE
        assert frame[2] == ref
        assert frame[3] == 0

    def test_documented_pin_payload_is_the_command_body(self):
        frame = vectors.PIN_CODE_SET_SLOT_803_PIN_8832_REF_16_COMMAND
        assert frame[const.COMMAND_HEADER_SIZE :] == vectors.PIN_CODE_SET_SLOT_803_PIN_8832_PAYLOAD

    def test_pin_payload_layout(self):
        payload = vectors.PIN_CODE_SET_SLOT_803_PIN_8832_PAYLOAD
        assert int.from_bytes(payload[0:2], "little") == 803
        assert payload[2] == len(payload) - 3
        assert payload[3:].decode(const.CHARACTER_SET) == "8832"

    @pytest.mark.parametrize(
        ("name", "slots"),
        [
            ("PIN_CODE_CLEAR_SLOT_803_PAYLOAD", const.PIN_SLOTS),
            ("FINGERPRINT_SCAN_SLOT_150_PAYLOAD", const.FINGERPRINT_SLOTS),
            ("FINGERPRINT_CLEAR_SLOT_199_PAYLOAD", const.FINGERPRINT_SLOTS),
            ("SCAN_RFID_CODE_SLOT_900_PAYLOAD", const.RFID_SLOTS),
            ("RFID_CODE_CLEAR_SLOT_999_PAYLOAD", const.RFID_SLOTS),
        ],
    )
    def test_slot_payloads_are_in_range(self, name, slots):
        payload = getattr(vectors, name)
        slot = int.from_bytes(payload, "little")
        assert slot in slots
        assert name.endswith(f"_{slot}_PAYLOAD")

    def test_default_user_auth_begin(self):
        payload = vectors.USER_AUTH_BEGIN_DEFAULT_PAYLOAD
        assert payload == bytes([const.DEFAULT_ADMIN_USER_ID]) + const.DEFAULT_DEVICE_ID

    def test_user_auth_update_carries_a_whole_key(self):
        assert len(vectors.USER_AUTH_UPDATE_PAYLOAD) == 2 + const.PUBLIC_KEY_LENGTH

    def test_one_byte_arguments(self):
        assert vectors.EKEY_OPERATE_UNLOCK_PAYLOAD[0] == const.EkeyOperationId.UNLOCK
        assert vectors.EKEY_OPERATE_LOCK_PAYLOAD[0] == const.EkeyOperationId.LOCK
        assert vectors.VOLUME_SET_NORMAL_PAYLOAD[0] == const.LockVolumeId.NORMAL
        assert len(vectors.DEVICE_ID_SET_PAYLOAD) == const.DEVICE_ID_LENGTH
        assert int.from_bytes(vectors.CURRENT_TIME_SET_0X12345678_PAYLOAD, "little") == 0x12345678


class TestPacketVectors:
    def test_single(self):
        packet = vectors.BATT_INFO_GET_SINGLE_PACKET
        assert packet[0] == const.PacketTypeId.SINGLE
        assert packet[1] == len(packet) - const.PACKET_HEADER_SIZE
        assert packet[3] == const.FIRST_SEQUENCE_NUMBER
        assert packet[const.PACKET_HEADER_SIZE :] == vectors.BATT_INFO_GET_REF_1_COMMAND

    def test_blob_fragments_reassemble(self):
        packets = vectors.EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23
        command = vectors.EXCHANGE_KEY_PUB_M_REF_1_COMMAND
        att_payload_max = const.DEFAULT_MTU - const.ATT_OVERHEAD

        types = [p[0] for p in packets]
        assert types == [const.PacketTypeId.BLOB_START] + [const.PacketTypeId.BLOB_STREAM] * 3 + [
            const.PacketTypeId.BLOB_COMPLETE
        ]
        assert [p[3] for p in packets] == list(range(const.FIRST_SEQUENCE_NUMBER, const.FIRST_SEQUENCE_NUMBER + 5))
        for packet in packets:
            assert len(packet) <= att_payload_max
            assert packet[1] == len(packet) - const.PACKET_HEADER_SIZE
            assert packet[2] == 0

        start = packets[0][const.PACKET_HEADER_SIZE :]
        flags, total, rfu = start[0], int.from_bytes(start[1:3], "little"), start[3]
        assert flags & const.BLOB_FLAG_ENCRYPTED == 0
        assert rfu == 0
        assert total == len(command)

        body = start[const.BLOB_HEADER_SIZE :] + b"".join(p[const.PACKET_HEADER_SIZE :] for p in packets[1:])
        assert body == command


    def test_encrypted_blob(self):
        packets = vectors.ENCRYPTED_16_BYTES_BLOB_PACKETS_MTU_23
        assert [p[0] for p in packets] == [const.PacketTypeId.BLOB_START, const.PacketTypeId.BLOB_COMPLETE]
        start = packets[0][const.PACKET_HEADER_SIZE :]
        assert start[0] & const.BLOB_FLAG_ENCRYPTED
        assert int.from_bytes(start[1:3], "little") == const.AES_BLOCK_SIZE
        body = start[const.BLOB_HEADER_SIZE :] + packets[1][const.PACKET_HEADER_SIZE :]
        assert body == vectors.ENCRYPTED_16_BYTES


class TestResponseVectors:
    @pytest.mark.parametrize("name", RESPONSES)
    def test_header(self, name):
        frame = getattr(vectors, name)
        response_id, status = RESPONSES[name]
        assert frame[0] == response_id
        assert frame[1] == len(frame) - const.RESPONSE_HEADER_SIZE
        assert frame[3] == status

    def test_payload_shapes(self):
        batt = vectors.BATT_INFO_GET_REF_1_RESPONSE[const.RESPONSE_HEADER_SIZE :]
        assert (int.from_bytes(batt[0:2], "little"), batt[2], batt[3]) == (5800, 0, 80)
        challenge = vectors.USER_AUTH_BEGIN_REF_1_RESPONSE[const.RESPONSE_HEADER_SIZE :]
        assert len(challenge) == const.CHALLENGE_LENGTH
        model = vectors.DEVICE_MODEL_GET_NIMLY_PRO_REF_1_RESPONSE[const.RESPONSE_HEADER_SIZE]
        assert model == const.LockModelId.NIMLY_PRO
        log = vectors.DEVICE_LOG_GET_REF_1_RESPONSE[const.RESPONSE_HEADER_SIZE :]
        assert log[0] == len(log) - 1
        status = vectors.LOCK_STATUS_SLOT_803_UNLOCKED_PANEL_RESPONSE[const.RESPONSE_HEADER_SIZE :]
        assert int.from_bytes(status[0:2], "little") == 803
        assert status[2] == const.LockStateId.UNLOCKED
        assert status[3] == const.DoorlockMethodId.PANEL

    def test_events_use_the_event_ref(self):
        for name in ("LOCK_STATUS_SLOT_803_UNLOCKED_PANEL_RESPONSE", "USER_ADDED_SLOT_151_FINGERPRINT_RESPONSE"):
            assert getattr(vectors, name)[2] == 0x80
