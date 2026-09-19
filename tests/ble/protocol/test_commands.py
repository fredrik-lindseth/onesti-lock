"""protocol/commands.py: every builder against its vector and the app's checks."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ...conftest import load_component_module
from .. import vectors

const = load_component_module("ble.protocol.const")
client_const = load_component_module("ble.client.const")
errors = load_component_module("ble.errors")
commands = load_component_module("ble.protocol.commands")
redact = load_component_module("redact")

CommandId = const.CommandId
KEY = bytes(range(64))


class TestPayloads:
    @pytest.mark.parametrize(
        ("built", "command_id", "expected"),
        [
            (lambda: commands.pin_code_set(803, "8832"), CommandId.PIN_CODE_SET, "PIN_CODE_SET_SLOT_803_PIN_8832_PAYLOAD"),
            (lambda: commands.master_pin_code_set("8832"), CommandId.PIN_CODE_SET, "MASTER_PIN_CODE_SET_PIN_8832_PAYLOAD"),
            (lambda: commands.pin_code_clear(803), CommandId.PIN_CODE_CLEAR, "PIN_CODE_CLEAR_SLOT_803_PAYLOAD"),
            (lambda: commands.fingerprint_scan(150), CommandId.FINGERPRINT_SCAN, "FINGERPRINT_SCAN_SLOT_150_PAYLOAD"),
            (lambda: commands.fingerprint_clear(199), CommandId.FINGERPRINT_CLEAR, "FINGERPRINT_CLEAR_SLOT_199_PAYLOAD"),
            (lambda: commands.scan_rfid_code(900), CommandId.SCAN_RFID_CODE, "SCAN_RFID_CODE_SLOT_900_PAYLOAD"),
            (lambda: commands.rfid_code_clear(999), CommandId.RFID_CODE_CLEAR, "RFID_CODE_CLEAR_SLOT_999_PAYLOAD"),
            (
                lambda: commands.user_auth_begin(client_const.DEFAULT_ADMIN_USER_ID, client_const.DEFAULT_DEVICE_ID),
                CommandId.USER_AUTH_BEGIN,
                "USER_AUTH_BEGIN_DEFAULT_PAYLOAD",
            ),
            (lambda: commands.user_auth_update(0, 1, KEY), CommandId.USER_AUTH_UPDATE, "USER_AUTH_UPDATE_PAYLOAD"),
            (
                lambda: commands.ekey_operate(const.EkeyOperationId.UNLOCK),
                CommandId.EKEY_OPERATE,
                "EKEY_OPERATE_UNLOCK_PAYLOAD",
            ),
            (lambda: commands.ekey_operate(const.EkeyOperationId.LOCK), CommandId.EKEY_OPERATE, "EKEY_OPERATE_LOCK_PAYLOAD"),
            (
                lambda: commands.device_id_set(bytes([1, 2, 3, 4, 5, 6])),
                CommandId.DEVICE_ID_SET,
                "DEVICE_ID_SET_PAYLOAD",
            ),
            (lambda: commands.device_name_set("Door"), CommandId.DEVICE_NAME_SET, "DEVICE_NAME_SET_DOOR_PAYLOAD"),
            (
                lambda: commands.current_time_set(0x12345678),
                CommandId.CURRENT_TIME_SET,
                "CURRENT_TIME_SET_0X12345678_PAYLOAD",
            ),
            (lambda: commands.auto_lock_set(True), CommandId.AUTO_LOCK_SET, "AUTO_LOCK_SET_ENABLED_PAYLOAD"),
            (
                lambda: commands.keypad_enable_set(False),
                CommandId.KEYPAD_ENABLE_SET,
                "KEYPAD_ENABLE_SET_DISABLED_PAYLOAD",
            ),
            (lambda: commands.volume_set(const.LockVolumeId.NORMAL), CommandId.VOLUME_SET, "VOLUME_SET_NORMAL_PAYLOAD"),
        ],
    )
    def test_matches_the_vector(self, built, command_id, expected):
        payload = built()
        assert payload.command_id is command_id
        assert payload.data == getattr(vectors, expected)

    def test_documented_pin_example_as_a_whole_command(self):
        frame = commands.pin_code_set(803, "8832").with_ref(const.COMMAND_REF_STATIC).to_bytes()
        assert frame == vectors.PIN_CODE_SET_SLOT_803_PIN_8832_REF_16_COMMAND

    def test_whole_command_vectors(self):
        begin = commands.user_auth_begin(0, client_const.DEFAULT_DEVICE_ID).with_ref(1).to_bytes()
        assert begin == vectors.USER_AUTH_BEGIN_DEFAULT_REF_1_COMMAND
        assert commands.batt_info_get().with_ref(1).to_bytes() == vectors.BATT_INFO_GET_REF_1_COMMAND
        assert commands.exchange_key_pub_m(KEY).with_ref(1).to_bytes() == vectors.EXCHANGE_KEY_PUB_M_REF_1_COMMAND

    def test_flags_and_other_values(self):
        assert commands.auto_lock_set(False).data == b"\x00"
        assert commands.keypad_enable_set(True).data == b"\x01"
        assert commands.volume_set(const.LockVolumeId.OFF).data == b"\x00"
        assert commands.ekey_operate(const.EkeyOperationId.INVALIDATE_TOKEN).data == b"\x03"
        assert commands.pin_code_set(899, "12345678").data == bytes.fromhex("83 03 08") + b"12345678"

    @pytest.mark.parametrize(
        ("built", "command_id"),
        [
            (commands.batt_info_get, CommandId.BATT_INFO_GET),
            (commands.device_log_get, CommandId.DEVICE_LOG_GET),
            (commands.device_model_get, CommandId.DEVICE_MODEL_GET),
            (commands.current_time_get, CommandId.CURRENT_TIME_GET),
            (commands.device_id_get, CommandId.DEVICE_ID_GET),
            (commands.device_name_get, CommandId.DEVICE_NAME_GET),
        ],
    )
    def test_commands_without_a_payload(self, built, command_id):
        payload = built()
        assert (payload.command_id, payload.data) == (command_id, b"")

    @pytest.mark.parametrize(
        ("built", "command_id"),
        [
            (commands.exchange_key_pub_m, CommandId.EXCHANGE_KEY_PUB_M),
            (commands.server_key_update, CommandId.SERVER_KEY_UPDATE),
        ],
    )
    def test_key_commands_carry_the_key_as_is(self, built, command_id):
        payload = built(KEY)
        assert (payload.command_id, payload.data) == (command_id, KEY)

    def test_user_auth_finalize(self):
        payload = commands.user_auth_finalize(bytes(range(16)))
        assert (payload.command_id, payload.data) == (CommandId.USER_AUTH_FINALIZE, bytes(range(16)))

    def test_enrollment_values(self):
        # AddLockFragment.finishSetup sends UserAuthUpdate(0, 0).
        assert commands.user_auth_update(0, 0, KEY).data == b"\x00\x00" + KEY


class TestSlotRanges:
    """verifyRange in each command class; both ends in, one past each end out."""

    @pytest.mark.parametrize(
        ("builder", "first", "last"),
        [
            (commands.pin_code_clear, 800, 899),
            (commands.rfid_code_clear, 900, 999),
            (commands.scan_rfid_code, 900, 999),
            (commands.fingerprint_scan, 150, 199),
            (commands.fingerprint_clear, 150, 199),
            (lambda slot: commands.pin_code_set(slot, "8832"), 800, 899),
        ],
    )
    def test_range(self, builder, first, last):
        builder(first)
        builder(last)
        for outside in (first - 1, last + 1):
            with pytest.raises(errors.BleValidationError) as info:
                builder(outside)
            assert str(info.value) == (
                f"Invalid SlotNumber, got value {outside}, but expected a value range of {first} - {last}"
            )

    def test_rfid_and_fingerprint_are_not_swapped(self):
        # The app pairs 0x55/0x56 with RFID and 0x57/0x58 with fingerprints.
        assert commands.rfid_code_clear(900).command_id == 0x55
        assert commands.scan_rfid_code(900).command_id == 0x56
        assert commands.fingerprint_scan(150).command_id == 0x57
        assert commands.fingerprint_clear(150).command_id == 0x58
        with pytest.raises(ValueError):
            commands.fingerprint_scan(900)
        with pytest.raises(ValueError):
            commands.scan_rfid_code(150)

    def test_ignore_slot_check(self):
        payload = commands.pin_code_set(3, "8832", ignore_slot_check=True)
        assert payload.data[:2] == b"\x03\x00"
        commands.pin_code_set(0xFFFF, "8832", ignore_slot_check=True)
        # Unchecked is not unbounded: the slot still has to fit its uint16.
        for slot in (-1, 0x10000):
            with pytest.raises(errors.BleValidationError, match="0 - 65535"):
                commands.pin_code_set(slot, "8832", ignore_slot_check=True)

    def test_master_pin_slot(self):
        assert commands.MASTER_PIN_SLOT == 0
        assert commands.master_pin_code_set("12345").data[:3] == bytes.fromhex("00 00 05")


class TestPinValidation:
    @pytest.mark.parametrize("pin", ["1234", "12345678"])
    def test_length_bounds(self, pin):
        assert commands.pin_code_set(800, pin).data[2] == len(pin)

    @pytest.mark.parametrize("pin", ["", "123", "123456789"])
    def test_wrong_length(self, pin):
        with pytest.raises(errors.BleValidationError, match="expected a length of 4 - 8"):
            commands.pin_code_set(800, pin)

    @pytest.mark.parametrize("pin", ["12a4", "12 45", "１２３４", "١٢٣٤", "12.4", "-123"])
    def test_only_ascii_digits(self, pin):
        with pytest.raises(errors.BleValidationError, match="only the characters 0-9"):
            commands.pin_code_set(800, pin)

    @pytest.mark.parametrize(
        "call",
        [
            lambda: commands.pin_code_set(800, "8832x"),
            lambda: commands.pin_code_set(800, "883291234"),
            lambda: commands.pin_code_set(799, "88329123"),
            lambda: commands.master_pin_code_set("8832x"),
            lambda: commands.master_pin_code_set("8832912345"),
        ],
    )
    def test_no_error_carries_the_pin(self, call):
        with pytest.raises(errors.BleValidationError) as info:
            call()
        message = str(info.value)
        assert "8832" not in message
        # redact.py masks runs of four digits or more; nothing may be left for it.
        assert redact.redact_digits(message) == message
        assert info.value.__context__ is None and info.value.__cause__ is None


class TestLengthChecks:
    @pytest.mark.parametrize(
        ("call", "name", "length"),
        [
            (lambda value: commands.exchange_key_pub_m(value), "PubM", 64),
            (lambda value: commands.user_auth_begin(0, value), "DeviceId", 6),
            (lambda value: commands.user_auth_finalize(value), "Challenge", 16),
            (lambda value: commands.user_auth_update(0, 0, value), "PublicKey", 64),
            (lambda value: commands.device_id_set(value), "DeviceId", 6),
            (lambda value: commands.server_key_update(value), "ServerPublicKey", 64),
        ],
    )
    def test_exact_length(self, call, name, length):
        call(bytes(length))
        for wrong in (length - 1, length + 1):
            with pytest.raises(errors.BleValidationError) as info:
                call(bytes(wrong))
            assert str(info.value) == f"Invalid {name}, expected length {length}, but got length {wrong}"

    def test_device_name(self):
        assert commands.device_name_set("12345678").data == b"12345678\x00"
        with pytest.raises(ValueError):
            commands.device_name_set("123456789")

    @pytest.mark.parametrize(
        "call",
        [
            lambda: commands.user_auth_begin(256, client_const.DEFAULT_DEVICE_ID),
            lambda: commands.user_auth_update(0, 256, KEY),
            lambda: commands.user_auth_update(-1, 0, KEY),
            lambda: commands.current_time_set(1 << 32),
            lambda: commands.current_time_set(-1),
        ],
    )
    def test_values_java_would_truncate_are_refused(self, call):
        with pytest.raises(errors.BleValidationError, match="does not fit"):
            call()

    def test_enum_arguments_must_be_members(self):
        with pytest.raises(ValueError):
            commands.ekey_operate(9)
        with pytest.raises(ValueError):
            commands.volume_set(3)


class TestLockTime:
    def test_epoch(self):
        assert commands.LOCK_TIME_EPOCH.isoformat() == "2023-01-01T00:00:00+00:00"
        assert commands.to_lock_time(commands.LOCK_TIME_EPOCH) == 0

    def test_whole_minutes(self):
        moment = datetime(2024, 4, 25, 0, 0, 59, tzinfo=UTC)
        assert commands.to_lock_time(moment) == 691200
        assert commands.from_lock_time(691200) == datetime(2024, 4, 25, tzinfo=UTC)

    def test_other_zones_are_converted(self):
        oslo_summer = timezone(timedelta(hours=2))
        assert commands.to_lock_time(datetime(2023, 1, 1, 2, 1, tzinfo=oslo_summer)) == 1

    def test_refuses_naive_and_early(self):
        with pytest.raises(errors.BleValidationError, match="timezone-aware"):
            commands.to_lock_time(datetime(2024, 1, 1))
        with pytest.raises(errors.BleValidationError, match="earlier than 2023"):
            commands.to_lock_time(datetime(2022, 12, 31, 23, 59, tzinfo=UTC))

    def test_round_trip_through_the_command(self):
        minutes = commands.to_lock_time(datetime(2026, 9, 19, 12, 0, tzinfo=UTC))
        data = commands.current_time_set(minutes).data
        assert commands.from_lock_time(int.from_bytes(data, "little")) == datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


class TestEveryCommandIdIsCovered:
    """The builders cover every command the plan asked for, and no id twice."""

    ASKED_FOR = {0x01, 0x18, 0x22, 0x23, 0x24, 0x30, 0x40, 0x41, 0x42, 0x44, 0x52, 0x53, 0x55, 0x56, 0x57, 0x58}
    ASKED_FOR |= {0x5A, 0x5B, 0x5C, 0x5D, 0x62}

    def test_asked_for(self):
        built = {
            commands.exchange_key_pub_m(KEY),
            commands.ekey_operate(const.EkeyOperationId.LOCK),
            commands.user_auth_begin(0, client_const.DEFAULT_DEVICE_ID),
            commands.user_auth_finalize(bytes(16)),
            commands.user_auth_update(0, 0, KEY),
            commands.device_id_set(bytes(6)),
            commands.current_time_get(),
            commands.current_time_set(0),
            commands.server_key_update(KEY),
            commands.device_log_get(),
            commands.pin_code_set(800, "1234"),
            commands.pin_code_clear(800),
            commands.rfid_code_clear(900),
            commands.scan_rfid_code(900),
            commands.fingerprint_scan(150),
            commands.fingerprint_clear(150),
            commands.volume_set(const.LockVolumeId.LOW),
            commands.auto_lock_set(True),
            commands.keypad_enable_set(True),
            commands.batt_info_get(),
            commands.device_model_get(),
        }
        assert {payload.command_id.value for payload in built} == self.ASKED_FOR
