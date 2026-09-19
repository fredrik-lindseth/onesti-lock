"""protocol/response.py: Layer 3 responses and their status.
"""
from __future__ import annotations

import pytest

from ...conftest import load_component_module
from .. import vectors

const = load_component_module("ble.protocol.const")
errors = load_component_module("ble.errors")
response = load_component_module("ble.protocol.response")


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
