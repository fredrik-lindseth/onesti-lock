"""ble/client/const.py against the values in the decompiled app.

A second, independent transcription of settings/Constants.java and the
timing constants in devices/ and communication/streams/.
"""
from __future__ import annotations

from ...conftest import load_component_module

const = load_component_module("ble.protocol.const")
client_const = load_component_module("ble.client.const")
crypto = load_component_module("ble.crypto")


class TestGatt:
    def test_uuids(self):
        assert client_const.SERVICE_UUID == "ba4bfd00-c447-19bf-f38d-4890b3a824c8"
        assert client_const.COMMUNICATION_CHARACTERISTIC_UUID == "ba4bfd03-c447-19bf-f38d-4890b3a824c8"
        assert client_const.ADVERTISING_UUID == "0000fd00-0000-1000-8000-00805f9b34fb"
        assert client_const.CLIENT_CHARACTERISTIC_CONFIGURATION_UUID == "00002902-0000-1000-8000-00805f9b34fb"
        assert client_const.DEVICE_INFORMATION_SERVICE_UUID == "0000180a-0000-1000-8000-00805f9b34fb"
        assert client_const.SOFTWARE_REVISION_CHARACTERISTIC_UUID == "00002a28-0000-1000-8000-00805f9b34fb"


class TestTiming:
    def test_response_timeout_and_pause(self):
        assert client_const.DEFAULT_RESPONSE_TIMEOUT_S == 20.0
        assert round(client_const.COMMAND_RESPONSE_DELAY_S * 1000) == 320


class TestFirmware:
    def test_connect_floor_is_below_the_admin_floor(self):
        assert client_const.MIN_FIRMWARE_CONNECT == (4, 6, 0)
        assert client_const.MIN_FIRMWARE_CONNECT < const.MIN_FIRMWARE_ADMIN


class TestFactoryCredential:
    def test_values(self):
        assert client_const.DEFAULT_ADMIN_USER_ID == 0
        assert client_const.DEFAULT_ENCRYPTION_KEY.hex() == "11" * 16
        assert client_const.DEFAULT_ENCRYPTION_IV.hex() == "22" * 16
        assert client_const.DEFAULT_DEVICE_ID.hex() == "00" * 6

    def test_lengths_fit_their_fields(self):
        assert len(client_const.DEFAULT_ENCRYPTION_KEY) == crypto.AES_KEY_LENGTH
        assert len(client_const.DEFAULT_ENCRYPTION_IV) == crypto.AES_BLOCK_SIZE
        assert len(client_const.DEFAULT_DEVICE_ID) == const.DEVICE_ID_LENGTH
