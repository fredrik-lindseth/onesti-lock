"""protocol/command.py: Layer 2 commands and the CommandRef counter.

Built frames are compared with the vectors in vectors.py, and parsed frames
are built again, so the layer is checked in both directions.
"""
from __future__ import annotations

import pytest

from ...conftest import load_component_module
from .. import vectors

const = load_component_module("ble.protocol.const")
errors = load_component_module("ble.errors")
command = load_component_module("ble.protocol.command")
response = load_component_module("ble.protocol.response")


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
        with pytest.raises(errors.BleValidationError, match="CommandRef"):
            command.Command(const.CommandId.BATT_INFO_GET, ref).to_bytes()

    def test_ref_bounds_are_accepted(self):
        assert command.Command(const.CommandId.BATT_INFO_GET, 1).to_bytes()[2] == 1
        assert command.Command(const.CommandId.BATT_INFO_GET, 254).to_bytes()[2] == 254

    def test_payload_limit(self):
        with pytest.raises(errors.BleValidationError, match="exceeds 255"):
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
