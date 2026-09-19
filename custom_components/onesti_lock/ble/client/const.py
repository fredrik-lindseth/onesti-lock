"""What the client needs beyond the wire format: GATT, timing and the factory login.

A Transport addresses the lock through the GATT UUIDs here, a scanner finds it
by ADVERTISING_UUID, Session paces itself by the timing values and refuses
firmware below MIN_FIRMWARE_CONNECT, and a factory-reset lock is logged into
with the DEFAULT_* credential. The frame layouts and ids are in
protocol/const.py.

Transcribed from the decompiled Nimly BLE app like protocol/const.py, with the
Java source named next to each value, relative to package com.nimly.ekey.ble.
"""
from __future__ import annotations

from typing import Final

from ..protocol.const import FirmwareVersion

# --- GATT (settings/Constants.java) -----------------------------------------

SERVICE_UUID: Final = "ba4bfd00-c447-19bf-f38d-4890b3a824c8"
# The one characteristic every command, response and notification uses.
COMMUNICATION_CHARACTERISTIC_UUID: Final = "ba4bfd03-c447-19bf-f38d-4890b3a824c8"
# 16-bit service UUID 0xFD00, carried as service data in the advertisement
# (protocol/advertisement.py reads it).
ADVERTISING_UUID: Final = "0000fd00-0000-1000-8000-00805f9b34fb"
CLIENT_CHARACTERISTIC_CONFIGURATION_UUID: Final = "00002902-0000-1000-8000-00805f9b34fb"
DEVICE_INFORMATION_SERVICE_UUID: Final = "0000180a-0000-1000-8000-00805f9b34fb"
# Read before anything else: the firmware floors are checked against it.
SOFTWARE_REVISION_CHARACTERISTIC_UUID: Final = "00002a28-0000-1000-8000-00805f9b34fb"

# --- Timing (devices/NimlyEkeyDeviceBase.java, communication/streams/) -------

# How long the app waits for a response (NimlyEkeyDeviceBase.DefaultTimeout).
DEFAULT_RESPONSE_TIMEOUT_S: Final = 20.0
# Pause after a matched response before the next command is released
# (CommandStream.CommandResponseDelay, 320 ms).
COMMAND_RESPONSE_DELAY_S: Final = 0.32
# Ours, not the app's: after a timeout under the static CommandRef (firmware
# below 4.7.90), how long the next command holds back, so an answer that was
# only late is dropped instead of completing that command. The app sends the
# next command at once. Set to the response timeout: an answer later than
# twice the app's own timeout is beyond anything the app can cope with either.
LATE_ANSWER_GRACE_S: Final = DEFAULT_RESPONSE_TIMEOUT_S

# --- Firmware (settings/Constants.java) ---------------------------------------

# Below this the app refuses to connect (MinimumRequiredSoftwareRevisionString).
# The floor for admin commands is protocol/const.py's MIN_FIRMWARE_ADMIN.
MIN_FIRMWARE_CONNECT: Final[FirmwareVersion] = (4, 6, 0)

# --- Factory owner credential (settings/Constants.java) ----------------------

# The owner credential a factory-reset lock accepts. AddLockFragment
# authenticates a fresh lock with ParamUserAuth(DefaultAdminUserId,
# DefaultDeviceId, DefaultEncryptionKey); see
# docs/nimly-ble-app/ble-auth-provisioning.md.
DEFAULT_ADMIN_USER_ID: Final = 0
DEFAULT_ENCRYPTION_KEY: Final = bytes([0x11] * 16)
DEFAULT_DEVICE_ID: Final = bytes(6)
# Defined next to the key in Constants.java, but nothing in the app reads it:
# owner auth uses the link IV from the key exchange. Kept so nobody mistakes
# its absence for an oversight.
DEFAULT_ENCRYPTION_IV: Final = bytes([0x22] * 16)
