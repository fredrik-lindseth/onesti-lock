"""protocol/features.py: the app's firmware and model gates, command by command.

EXPECTED is transcribed from each operation's feature() in
admin/devices/NimlyEkeyDevice.java, one row per command the library can
build, independently of the sets in features.py: what the app answers below
firmware 4.7.90, and from 4.7.90 on a model that has the feature. A command
missing from the table fails test_every_command_id_is_covered.
"""
from __future__ import annotations

import pytest

from ...conftest import load_component_module

const = load_component_module("ble.protocol.const")
commands = load_component_module("ble.protocol.commands")
command_mod = load_component_module("ble.protocol.command")
features = load_component_module("ble.protocol.features")

CommandId = const.CommandId
Feature = const.DeviceFeature
Model = const.LockModelId

OLD = (4, 7, 89)
NEW = (4, 7, 90)
KEY = bytes(64)

ALWAYS = (Feature.AVAILABLE_ALWAYS, Feature.AVAILABLE_ALWAYS)
VERSION = (Feature.UNAVAILABLE_VERSION, Feature.AVAILABLE)
UNKNOWN = (Feature.UNAVAILABLE_UNKNOWN, Feature.AVAILABLE)


def payload(command_id, data=b""):
    return command_mod.CommandPayload(command_id, data)


# (command, (below 4.7.90, from 4.7.90 on a model with the feature), model feature or None)
EXPECTED = {
    "pin_code_set": (commands.pin_code_set(803, "8832"), VERSION, None),  # $7
    "master_pin_code_set": (commands.master_pin_code_set("8832"), VERSION, "master_pin"),  # $6
    "pin_code_clear": (commands.pin_code_clear(803), VERSION, None),  # $3
    "keypad_enable_set": (commands.keypad_enable_set(True), UNKNOWN, "keypad_enable"),  # $4
    "auto_lock_set": (commands.auto_lock_set(True), VERSION, None),  # $5
    "fingerprint_scan": (commands.fingerprint_scan(150), UNKNOWN, "fingerprint"),  # $8
    "fingerprint_clear": (commands.fingerprint_clear(150), UNKNOWN, "fingerprint"),  # $9
    "rfid_code_clear": (commands.rfid_code_clear(900), VERSION, None),  # $10
    "scan_rfid_code": (commands.scan_rfid_code(900), VERSION, None),  # $11
    "volume_set": (commands.volume_set(const.LockVolumeId.LOW), VERSION, None),  # $12
    "batt_info_get": (commands.batt_info_get(), VERSION, None),
    # NimlyEkeyDeviceBase.connect asks only from 4.7.90; not an operation.
    "device_model_get": (commands.device_model_get(), VERSION, None),
    "device_name_set": (commands.device_name_set("Door"), ALWAYS, None),
    "device_name_get": (commands.device_name_get(), ALWAYS, None),
    "device_id_set": (commands.device_id_set(bytes(range(6))), ALWAYS, None),
    "device_id_get": (commands.device_id_get(), ALWAYS, None),
    "ekey_operate": (commands.ekey_operate(const.EkeyOperationId.UNLOCK), ALWAYS, None),
    "current_time_set": (commands.current_time_set(1000), ALWAYS, None),
    "current_time_get": (commands.current_time_get(), ALWAYS, None),
    "device_log_get": (commands.device_log_get(), ALWAYS, None),
    "server_key_update": (commands.server_key_update(KEY), ALWAYS, None),
    "user_auth_begin": (commands.user_auth_begin(0, bytes(6)), ALWAYS, None),
    "user_auth_finalize": (commands.user_auth_finalize(bytes(16)), ALWAYS, None),
    "user_auth_update": (commands.user_auth_update(0, 0, KEY), ALWAYS, None),
    "exchange_key_pub_m": (commands.exchange_key_pub_m(KEY), ALWAYS, None),
    # No builders in the library; the app's operations say AvailableAlways.
    "ekey_user_auth": (payload(CommandId.EKEY_USER_AUTH), ALWAYS, None),
    "ekey_user_add": (payload(CommandId.EKEY_USER_ADD), ALWAYS, None),
    "ekey_user_remove": (payload(CommandId.EKEY_USER_REMOVE), ALWAYS, None),
    "ekey_users_list": (payload(CommandId.EKEY_USERS_LIST), ALWAYS, None),
    "ekey_device_info_get": (payload(CommandId.EKEY_DEVICE_INFO_GET), ALWAYS, None),
    "ekey_device_info_set": (payload(CommandId.EKEY_DEVICE_INFO_SET), ALWAYS, None),
    "factory_reset_module": (payload(CommandId.FACTORY_RESET_MODULE), ALWAYS, None),
}


def test_every_command_id_is_covered():
    covered = {command.command_id for command, _, _ in EXPECTED.values()}
    assert covered == set(CommandId)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_below_the_admin_firmware(name):
    command, (below, _), _ = EXPECTED[name]
    for model in (None, Model.NIMLY_PRO_24):
        assert features.availability(command, OLD, model) is below


@pytest.mark.parametrize("name", list(EXPECTED))
@pytest.mark.parametrize("model", list(Model))
def test_from_the_admin_firmware_on_every_model(name, model):
    command, (_, available), feature = EXPECTED[name]
    has_it = feature is None or getattr(model.features, feature)
    expected = available if has_it else Feature.UNAVAILABLE
    for firmware in (NEW, (5, 0, 0)):
        assert features.availability(command, firmware, model) is expected


def test_a_model_nobody_read_has_no_features():
    assert features.availability(commands.fingerprint_scan(150), NEW, None) is Feature.UNAVAILABLE
    assert features.availability(commands.pin_code_set(803, "8832"), NEW, None) is Feature.AVAILABLE


def test_master_pin_is_a_pin_code_set_to_slot_zero():
    """However it was built: the gate reads the slot the lock would read."""
    by_hand = commands.pin_code_set(0, "8832", ignore_slot_check=True)
    assert features.availability(by_hand, NEW, Model.NIMLY_PRO) is Feature.UNAVAILABLE
    assert features.availability(by_hand, NEW, Model.NIMLY_PRO_24) is Feature.AVAILABLE
    # Slot 256 has a zero low byte; only both bytes zero is slot 0.
    other = commands.pin_code_set(256, "8832", ignore_slot_check=True)
    assert features.availability(other, NEW, Model.NIMLY_PRO) is Feature.AVAILABLE


@pytest.mark.parametrize(
    ("feature", "available"),
    [
        (Feature.AVAILABLE_ALWAYS, True),
        (Feature.AVAILABLE, True),
        (Feature.UNAVAILABLE, False),
        (Feature.UNAVAILABLE_VERSION, False),
        (Feature.UNAVAILABLE_UNKNOWN, False),
    ],
)
def test_available_follows_the_app(feature, available):
    # DeviceFeature(boolean available) in operations/DeviceFeature.java.
    assert feature.available is available
