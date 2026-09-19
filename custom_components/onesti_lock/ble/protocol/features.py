"""Which commands the app sends to which lock: its firmware and model gates.

The app wraps every admin command in an operation whose feature() says
whether this lock has it (admin/devices/NimlyEkeyDevice.java), and refuses to
run one that is not available (NimlyEkeyBleExtensionsKt.toSuspend throws
"Feature is unavailable"). availability() gives the same answer for a built
command, so Session.send can refuse what the app would refuse.

The rules, read from each operation's feature():

- From firmware 4.7.90 only (UNAVAILABLE_VERSION below): PinCodeSet,
  PinCodeClear, AutoLockSet, RfidCodeClear, ScanRfidCode, VolumeSet,
  BattInfoGet. DeviceModelGet too, which the app sends only from that
  version, in NimlyEkeyDeviceBase.connect, never as an operation.
- From 4.7.90 and only on a model with the feature: FingerprintScan and
  FingerprintClear (fingerprint) and KeypadEnableSet (keypad_enable), which
  answer UNAVAILABLE_UNKNOWN below 4.7.90; the master PIN, a PinCodeSet to
  slot 0 (master_pin), which answers UNAVAILABLE_VERSION there. A model
  without the feature is UNAVAILABLE.
- Everything else is AVAILABLE_ALWAYS: login, enrollment, EkeyOperate, the
  clock, name, device id, log, the ekey user commands and FactoryResetModule.

The master PIN is told apart the way the lock itself would see it: a
PinCodeSet whose slot is 0. The app builds it only through masterPincodeSet.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Final

from .command import CommandPayload
from .const import MIN_FIRMWARE_ADMIN, CommandId, DeviceFeature, FirmwareVersion, LockModelId, ModelFeatures

# Needs firmware 4.7.90, whatever the model.
_FIRMWARE_GATED: Final = frozenset(
    {
        CommandId.PIN_CODE_SET,
        CommandId.PIN_CODE_CLEAR,
        CommandId.AUTO_LOCK_SET,
        CommandId.RFID_CODE_CLEAR,
        CommandId.SCAN_RFID_CODE,
        CommandId.VOLUME_SET,
        CommandId.BATT_INFO_GET,
        CommandId.DEVICE_MODEL_GET,
    }
)


def _is_master_pin(command: CommandPayload) -> bool:
    # PinCodeSet starts with the slot as u16 LE; commands.MASTER_PIN_SLOT is 0.
    return command.command_id is CommandId.PIN_CODE_SET and command.data[:2] == bytes(2)


def availability(command: CommandPayload, firmware: FirmwareVersion, model: LockModelId | None) -> DeviceFeature:
    """What the app's feature() answers for this command on this lock.

    model is what DeviceModelGet said, None below 4.7.90 where nobody asks.
    """
    admin_firmware = firmware >= MIN_FIRMWARE_ADMIN
    command_id = command.command_id
    if command_id in (CommandId.FINGERPRINT_SCAN, CommandId.FINGERPRINT_CLEAR):
        return _model_gated(admin_firmware, model, lambda features: features.fingerprint, DeviceFeature.UNAVAILABLE_UNKNOWN)
    if command_id is CommandId.KEYPAD_ENABLE_SET:
        return _model_gated(admin_firmware, model, lambda features: features.keypad_enable, DeviceFeature.UNAVAILABLE_UNKNOWN)
    if _is_master_pin(command):
        return _model_gated(admin_firmware, model, lambda features: features.master_pin, DeviceFeature.UNAVAILABLE_VERSION)
    if command_id in _FIRMWARE_GATED:
        return DeviceFeature.AVAILABLE if admin_firmware else DeviceFeature.UNAVAILABLE_VERSION
    return DeviceFeature.AVAILABLE_ALWAYS


def _model_gated(
    admin_firmware: bool,
    model: LockModelId | None,
    has: Callable[[ModelFeatures], bool],
    below_firmware: DeviceFeature,
) -> DeviceFeature:
    if not admin_firmware:
        return below_firmware
    # From 4.7.90 the session has read the model. The app reads a byte it
    # does not know as UNKNOWN, which has no features; a model nobody read is
    # taken the same way.
    features = (LockModelId.UNKNOWN if model is None else model).features
    return DeviceFeature.AVAILABLE if has(features) else DeviceFeature.UNAVAILABLE
