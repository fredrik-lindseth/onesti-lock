"""protocol/responses.py: typed payloads, read from the response vectors."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ...conftest import load_component_module
from .. import vectors

const = load_component_module("ble.protocol.const")
errors = load_component_module("ble.errors")
response = load_component_module("ble.protocol.response")
responses = load_component_module("ble.protocol.responses")

ResponseId = const.ResponseId


def parse(frame: bytes):
    return response.Response.from_bytes(frame)


def build(response_id, payload=b"", *, ref=1, status=0):
    return response.Response(response_id, ref, status, payload)


class TestTypedPayloads:
    def test_batt_info(self):
        info = responses.parse_batt_info(parse(vectors.BATT_INFO_GET_REF_1_RESPONSE))
        assert info == responses.BattInfo(level=5800, low_battery=False, percent=80)

    @pytest.mark.parametrize(("flag", "low"), [(0, False), (1, True), (2, False)])
    def test_low_battery_is_exactly_one(self, flag, low):
        info = responses.parse_batt_info(build(ResponseId.BATT_INFO_GET, bytes([0, 0, flag, 5])))
        assert info.low_battery is low

    def test_device_model(self):
        model = responses.parse_device_model(parse(vectors.DEVICE_MODEL_GET_NIMLY_PRO_REF_1_RESPONSE))
        assert model == responses.DeviceModel(const.LockModelId.NIMLY_PRO, 0x17)
        assert model.model.features.fingerprint

    def test_unknown_model_reads_as_unknown_and_keeps_the_byte(self):
        model = responses.parse_device_model(build(ResponseId.DEVICE_MODEL_GET, b"\x63"))
        assert model == responses.DeviceModel(const.LockModelId.UNKNOWN, 0x63)

    def test_user_auth_begin(self):
        begin = responses.parse_user_auth_begin(parse(vectors.USER_AUTH_BEGIN_REF_1_RESPONSE))
        assert begin.challenge == bytes(range(0xA0, 0xB0))

    def test_user_auth_finalize(self):
        assert responses.parse_user_auth_finalize(parse(vectors.USER_AUTH_FINALIZE_REF_2_RESPONSE)).credentials == 1

    def test_user_auth_update(self):
        update = responses.parse_user_auth_update(parse(vectors.USER_AUTH_UPDATE_REF_3_RESPONSE))
        assert update.public_key == bytes(range(0x40, 0x80))

    def test_exchange_key_pub_l(self):
        pub_l = responses.parse_exchange_key_pub_l(parse(vectors.EXCHANGE_KEY_PUB_L_REF_1_RESPONSE))
        assert pub_l.public_key == bytes(range(0x80, 0xC0))

    def test_server_key_update(self):
        update = responses.parse_server_key_update(parse(vectors.SERVER_KEY_UPDATE_REF_4_RESPONSE))
        assert update.lock_public_key == bytes(range(0xC0, 0x100))

    def test_device_log(self):
        log = responses.parse_device_log(parse(vectors.DEVICE_LOG_GET_REF_1_RESPONSE))
        assert log.log == bytes.fromhex("AA BB CC")
        assert responses.parse_device_log(build(ResponseId.DEVICE_LOG_GET, b"\x00")).log == b""

    def test_current_time(self):
        now = responses.parse_current_time(parse(vectors.CURRENT_TIME_GET_REF_5_RESPONSE))
        assert now.minutes == 691200
        assert now.moment == datetime(2024, 4, 25, tzinfo=UTC)

    def test_fingerprint_scan(self):
        scan = responses.parse_fingerprint_scan(parse(vectors.FINGERPRINT_SCAN_SLOT_150_NO_SPACE_REF_6_RESPONSE))
        assert scan == responses.ScanResult(150, const.LockStatusId.NO_SPACE_LEFT)

    def test_rfid_scan_with_an_unknown_status_keeps_the_byte(self):
        scan = responses.parse_scan_rfid_code(build(ResponseId.SCAN_RFID_CODE, bytes.fromhex("84 03 2A")))
        assert scan == responses.ScanResult(900, 0x2A)
        assert type(scan.status) is int

    def test_device_id_and_name(self):
        assert responses.parse_device_id_get(parse(vectors.DEVICE_ID_GET_REF_8_RESPONSE)).device_id == bytes(
            [1, 2, 3, 4, 5, 6]
        )
        assert responses.parse_device_name_get(parse(vectors.DEVICE_NAME_GET_DOOR_REF_7_RESPONSE)).name == "Door"

    def test_trailing_bytes_are_ignored(self):
        info = responses.parse_batt_info(build(ResponseId.BATT_INFO_GET, bytes.fromhex("A8 16 00 50 FF FF")))
        assert info.percent == 80


class TestChecks:
    def test_wrong_response(self):
        with pytest.raises(errors.BleProtocolError, match="Expected a BATT_INFO_GET response, got DEVICE_MODEL_GET"):
            responses.parse_batt_info(parse(vectors.DEVICE_MODEL_GET_NIMLY_PRO_REF_1_RESPONSE))

    def test_unknown_response(self):
        with pytest.raises(errors.BleProtocolError, match="got unknown response 0x99"):
            responses.parse_batt_info(build(0x99))

    def test_failed_status_raises_before_parsing(self):
        with pytest.raises(errors.BleSecurityError):
            responses.parse_user_auth_begin(build(ResponseId.USER_AUTH_BEGIN, status=10))

    def test_too_short(self):
        with pytest.raises(errors.BleProtocolError, match="Tried to read 16 byte"):
            responses.parse_user_auth_begin(build(ResponseId.USER_AUTH_BEGIN, bytes(15)))
        with pytest.raises(errors.BleProtocolError, match="Tried to read 3 byte"):
            responses.parse_device_log(build(ResponseId.DEVICE_LOG_GET, b"\x03ab"))


class TestStatusOnly:
    @pytest.mark.parametrize("response_id", sorted(responses.STATUS_ONLY_RESPONSES), ids=lambda r: r.name)
    def test_success(self, response_id):
        responses.check_status_only(build(response_id), response_id)

    def test_the_vectors(self):
        responses.check_status_only(parse(vectors.PIN_CODE_SET_SUCCESS_REF_1_RESPONSE), ResponseId.PIN_CODE_SET)
        with pytest.raises(errors.BleNotFoundError):
            responses.check_status_only(parse(vectors.PIN_CODE_CLEAR_NOT_FOUND_REF_1_RESPONSE), ResponseId.PIN_CODE_CLEAR)

    def test_wrong_response(self):
        with pytest.raises(errors.BleProtocolError, match="Expected a PIN_CODE_CLEAR"):
            responses.check_status_only(parse(vectors.PIN_CODE_SET_SUCCESS_REF_1_RESPONSE), ResponseId.PIN_CODE_CLEAR)

    def test_payload_responses_are_refused(self):
        with pytest.raises(ValueError, match="BATT_INFO_GET carries a payload"):
            responses.check_status_only(parse(vectors.BATT_INFO_GET_REF_1_RESPONSE), ResponseId.BATT_INFO_GET)

    def test_the_set_matches_the_app(self):
        # Every response class whose deserializeResponse reads nothing, and
        # the commands built here that expect one.
        assert {r.name for r in responses.STATUS_ONLY_RESPONSES} == {
            "EKEY_OPERATE",
            "DEVICE_ID_SET",
            "DEVICE_NAME_SET",
            "CURRENT_TIME_SET",
            "PIN_CODE_SET",
            "PIN_CODE_CLEAR",
            "RFID_CODE_CLEAR",
            "FINGERPRINT_CLEAR",
            "VOLUME_SET",
            "AUTO_LOCK_SET",
            "KEYPAD_ENABLE_SET",
            "FACTORY_RESET_MODULE",
        }


class TestEvents:
    def test_lock_status(self):
        event = responses.parse_event(parse(vectors.LOCK_STATUS_SLOT_803_UNLOCKED_PANEL_RESPONSE))
        assert event == responses.LockStatus(803, const.LockStateId.UNLOCKED, const.DoorlockMethodId.PANEL)

    def test_user_added(self):
        event = responses.parse_event(parse(vectors.USER_ADDED_SLOT_151_FINGERPRINT_RESPONSE))
        assert event == responses.UserAdded(151, const.UserAddedStatusId.FINGERPRINT)

    def test_status_byte_is_not_read(self):
        # The app never looks at an event's status.
        event = build(ResponseId.LOCK_STATUS, bytes.fromhex("23 03 01 00"), ref=128, status=1)
        assert responses.parse_lock_status(event).state is const.LockStateId.LOCKED

    def test_only_the_event_ref_counts(self):
        not_event = build(ResponseId.LOCK_STATUS, bytes.fromhex("23 03 01 00"), ref=5)
        assert responses.parse_event(not_event) is None

    def test_other_responses_under_the_event_ref_are_not_events(self):
        assert responses.parse_event(build(ResponseId.BATT_INFO_GET, bytes(4), ref=128)) is None

    @pytest.mark.parametrize(
        ("frame", "message"),
        [
            (build(ResponseId.LOCK_STATUS, bytes.fromhex("23 03 03 00"), ref=128), "Unknown LockStateId value 3"),
            (build(ResponseId.LOCK_STATUS, bytes.fromhex("23 03 01 09"), ref=128), "Unknown DoorlockMethodId value 9"),
            (build(ResponseId.USER_ADDED, bytes.fromhex("97 00 05"), ref=128), "Unknown UserAddedStatusId value 5"),
        ],
    )
    def test_unknown_required_enums_fail(self, frame, message):
        with pytest.raises(errors.BleProtocolError, match=message):
            responses.parse_event(frame)


class TestRoundTrip:
    """A parsed vector serializes back to the same bytes."""

    @pytest.mark.parametrize("name", [n for n in dir(vectors) if n.endswith("_RESPONSE")])
    def test_every_response_vector(self, name):
        frame = getattr(vectors, name)
        assert parse(frame).to_bytes() == frame
