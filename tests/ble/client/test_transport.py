"""The write type rule in ble/client/transport.py.

Android's BluetoothGattCharacteristic.initCharacteristic sets
WRITE_TYPE_NO_RESPONSE as soon as PROPERTY_WRITE_NO_RESPONSE is listed, and
the app never overrides it, so write-without-response wins over write
whenever both are offered.
"""
from __future__ import annotations

import pytest

from ...conftest import load_component_module

errors = load_component_module("ble.errors")
transport = load_component_module("ble.client.transport")


class TestWriteWithResponse:
    @pytest.mark.parametrize(
        ("properties", "expected"),
        [
            (["write-without-response", "write"], False),
            (["write", "write-without-response"], False),
            (["write-without-response"], False),
            (["write"], True),
            (["read", "write", "notify"], True),
        ],
    )
    def test_every_combination(self, properties, expected):
        assert transport.write_with_response(properties) is expected

    @pytest.mark.parametrize("properties", [[], ["read", "notify"]])
    def test_a_characteristic_that_cannot_be_written(self, properties):
        with pytest.raises(errors.BleError, match="cannot be written"):
            transport.write_with_response(properties)

    def test_the_error_lists_the_properties_it_saw(self):
        with pytest.raises(errors.BleError, match=r"\(properties: \['notify', 'read'\]\)"):
            transport.write_with_response(["read", "notify"])
