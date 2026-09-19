"""ble/protocol/const.py against the values in the decompiled app.

The expected tables below are a second, independent transcription of the Java
enums (communication/**/*Id.java, settings/Constants.java). A typo in const.py
has to be repeated here to slip through.
"""
from __future__ import annotations

from enum import IntEnum

import pytest

from ...conftest import load_component_module

const = load_component_module("ble.protocol.const")


class TestEnumValues:
    def test_packet_types(self):
        assert {m.name: m.value for m in const.PacketTypeId} == {
            "SINGLE": 1,
            "SINGLE_ENCRYPTED": 2,
            "BLOB_START": 3,
            "BLOB_STREAM": 4,
            "BLOB_COMPLETE": 5,
            "ACK": 6,
            "NAC": 7,
            "ERROR": 240,
        }

    def test_command_ids(self):
        # CommandId.java in its own order, decimal as jadx printed it.
        assert {m.name: m.value for m in const.CommandId} == {
            "EXCHANGE_KEY_PUB_M": 1,
            "EKEY_OPERATE": 24,
            "USER_AUTH_BEGIN": 34,
            "USER_AUTH_FINALIZE": 35,
            "USER_AUTH_UPDATE": 36,
            "EKEY_USER_ADD": 27,
            "EKEY_USERS_LIST": 29,
            "EKEY_USER_REMOVE": 28,
            "EKEY_USER_AUTH": 23,
            "CURRENT_TIME_GET": 64,
            "CURRENT_TIME_SET": 65,
            "SERVER_KEY_UPDATE": 66,
            "DEVICE_LOG_GET": 68,
            "EKEY_DEVICE_INFO_GET": 31,
            "EKEY_DEVICE_INFO_SET": 32,
            "DEVICE_ID_SET": 48,
            "DEVICE_ID_GET": 49,
            "DEVICE_NAME_SET": 50,
            "DEVICE_NAME_GET": 51,
            "FACTORY_RESET_MODULE": 112,
            "PIN_CODE_SET": 82,
            "PIN_CODE_CLEAR": 83,
            "AUTO_LOCK_SET": 91,
            "KEYPAD_ENABLE_SET": 92,
            "BATT_INFO_GET": 93,
            "VOLUME_SET": 90,
            "SCAN_RFID_CODE": 86,
            "RFID_CODE_CLEAR": 85,
            "FINGERPRINT_SCAN": 87,
            "FINGERPRINT_CLEAR": 88,
            "DEVICE_MODEL_GET": 98,
        }

    def test_every_command_is_answered_under_the_same_id(self):
        for command in const.CommandId:
            if command is const.CommandId.EXCHANGE_KEY_PUB_M:
                assert const.ResponseId(command.value) is const.ResponseId.EXCHANGE_KEY_PUB_L
            else:
                assert const.ResponseId[command.name].value == command.value

    def test_responses_without_a_command(self):
        unsolicited = {m.name for m in const.ResponseId} - {m.name for m in const.CommandId} - {"EXCHANGE_KEY_PUB_L"}
        assert unsolicited == {"LOCK_STATUS", "USER_ADDED"}
        assert const.ResponseId.LOCK_STATUS == 96
        assert const.ResponseId.USER_ADDED == 20

    def test_response_statuses(self):
        assert [m.name for m in const.ResponseStatusId] == [
            "SUCCESS",
            "FAILED",
            "NOT_AVAILABLE",
            "INTERNAL_ERROR",
            "PARAMETER_ERROR",
            "LENGTH_ERROR",
            "NOT_FOUND_ERROR",
            "NO_MATCH_ERROR",
            "NOT_SUPPORTED_ERROR",
            "NOT_VALID_ERROR",
            "SECURITY_ERROR",
        ]
        assert [m.value for m in const.ResponseStatusId] == list(range(11))

    def test_lock_state_and_method(self):
        assert {m.name: m.value for m in const.LockStateId} == {"LOCKED": 1, "UNLOCKED": 2}
        assert [m.name for m in const.DoorlockMethodId] == ["KEY", "BUTTON", "PANEL", "FINGERPRINT", "RFID", "OTHER"]
        assert [m.value for m in const.DoorlockMethodId] == list(range(6))

    def test_scan_status(self):
        assert [m.value for m in const.LockStatusId] == list(range(7))
        assert const.LockStatusId.NO_MATCH == 6

    def test_small_argument_enums(self):
        assert {m.name: m.value for m in const.EkeyOperationId} == {"UNLOCK": 1, "LOCK": 2, "INVALIDATE_TOKEN": 3}
        assert {m.name: m.value for m in const.LockVolumeId} == {"OFF": 0, "LOW": 1, "NORMAL": 2}
        assert [m.value for m in const.UserAddedStatusId] == list(range(5))
        assert const.UserAddedStatusId.SLOT_OCCUPIED == 4

    @pytest.mark.parametrize(
        "enum",
        [
            "PacketTypeId",
            "CommandId",
            "ResponseId",
            "ResponseStatusId",
            "LockModelId",
            "LockStatusId",
            "LockStateId",
            "DoorlockMethodId",
            "EkeyOperationId",
            "LockVolumeId",
            "UserAddedStatusId",
        ],
    )
    def test_every_enum_fits_a_byte_without_aliases(self, enum):
        # An IntEnum silently turns a repeated value into an alias, which would
        # hide a transcription slip. Every id travels as one byte.
        cls = getattr(const, enum)
        assert issubclass(cls, IntEnum)
        assert len(cls.__members__) == len(list(cls))
        assert all(0 <= member <= 0xFF for member in cls)


class TestLockModels:
    # (value, fingerprint, keypad enable, master PIN) from LockModelId.java.
    EXPECTED = {
        "UNKNOWN": (0, False, False, False),
        "EASY_FINGER_TOUCH": (8, True, False, False),
        "EASY_CODE_TOUCH": (9, False, False, False),
        "NIMLY_CODE": (21, False, False, False),
        "NIMLY_TOUCH": (22, False, False, False),
        "NIMLY_PRO": (23, True, False, False),
        "NIMLY_INDOOR": (24, False, False, False),
        "NIMLY_KEYBOX": (26, False, False, False),
        "NIMLY_TWIST": (27, False, False, False),
        "NIMLY_CODE_2": (31, False, True, True),
        "NIMLY_TOUCH_2": (32, False, True, True),
        "NIMLY_PRO_24": (33, True, True, True),
        "NIMLY_INDOOR_2": (34, False, True, True),
        "NIMLY_KEYBOX_2": (36, False, True, True),
        "NIMLY_TWIST_2": (37, False, True, True),
    }

    def test_values_and_features(self):
        actual = {
            m.name: (m.value, m.features.fingerprint, m.features.keypad_enable, m.features.master_pin)
            for m in const.LockModelId
        }
        assert actual == self.EXPECTED

    def test_features_are_immutable(self):
        features = const.LockModelId.NIMLY_PRO.features
        with pytest.raises(AttributeError):
            features.fingerprint = False


class TestConstants:
    def test_field_lengths(self):
        assert const.CHALLENGE_LENGTH == 16
        assert const.PUBLIC_KEY_LENGTH == 64
        assert const.DEVICE_ID_LENGTH == 6
        assert const.EKEY_AUTH_TOKEN_LENGTH == 32

    def test_unenrolled_advertisement_seed(self):
        assert const.DEFAULT_DEVICE_ID_SEED.hex() == "00" * 2
        assert len(const.DEFAULT_DEVICE_ID_SEED) == const.DEVICE_ID_SEED_LENGTH

    def test_slot_ranges(self):
        assert (const.PIN_SLOTS.start, const.PIN_SLOTS[-1]) == (800, 899)
        assert (const.FINGERPRINT_SLOTS.start, const.FINGERPRINT_SLOTS[-1]) == (150, 199)
        assert (const.RFID_SLOTS.start, const.RFID_SLOTS[-1]) == (900, 999)
        ranges = [set(const.PIN_SLOTS), set(const.FINGERPRINT_SLOTS), set(const.RFID_SLOTS)]
        assert not ranges[0] & ranges[1] and not ranges[0] & ranges[2] and not ranges[1] & ranges[2]
        # Every BLE slot still fits the uint16 the commands write.
        assert const.RFID_SLOTS[-1] <= 0xFFFF

    def test_pin_length(self):
        assert (const.PIN_LENGTH_MIN, const.PIN_LENGTH_MAX) == (4, 8)

    def test_pin_floor_agrees_with_the_zigbee_side(self):
        # redact.py masks digit runs from pin_rules.PIN_LENGTH_SANE_MIN up. A
        # BLE PIN shorter than that could reach a log in clear text.
        pin_rules = load_component_module("pin_rules")
        assert const.PIN_LENGTH_MIN >= pin_rules.PIN_LENGTH_SANE_MIN

    def test_admin_firmware_floor(self):
        assert const.MIN_FIRMWARE_ADMIN == (4, 7, 90)

    def test_framing(self):
        assert const.PACKET_HEADER_SIZE == const.COMMAND_HEADER_SIZE == const.RESPONSE_HEADER_SIZE == 4
        assert const.BLOB_HEADER_SIZE == 4
        assert const.PACKET_PAYLOAD_MAX == 255
        assert (const.COMMAND_REF_MIN, const.COMMAND_REF_MAX) == (1, 254)
        assert const.COMMAND_REF_MIN <= const.COMMAND_REF_STATIC <= const.COMMAND_REF_MAX
        assert const.COMMAND_REF_COUNTER_WRAP - 1 <= const.COMMAND_REF_MAX
        assert const.FIRST_SEQUENCE_NUMBER == 1
        assert const.BLOB_FLAG_ENCRYPTED == 0x01

    def test_link_layer(self):
        assert const.DEFAULT_MTU == 23
        assert const.ATT_OVERHEAD == 3

