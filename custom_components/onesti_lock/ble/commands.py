"""Builders for the commands the library sends.

One function per command class in communication/commands/, each writing what
that class's serializeCommand writes and checking what it checks first, so a
value the app would refuse never reaches the lock. Slot ranges follow
VerifyExtensions.verifyRange in each class; the ranges are BLE slot numbers
(docs/slot-numbering.md). Every check raises BleValidationError.

Where the app writes a value through a Java cast that would silently truncate
(a user id above 255, a time above 2^32), the builder refuses it instead.

No message quotes a PIN. The app's own PinCodeSet error does
("Invalid pincode '%s'"); this one does not.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from .command import CommandPayload
from .const import (
    CHALLENGE_LENGTH,
    DEVICE_ID_LENGTH,
    DEVICE_NAME_MAX_LENGTH,
    FINGERPRINT_SLOTS,
    PIN_LENGTH_MAX,
    PIN_LENGTH_MIN,
    PIN_SLOTS,
    PUBLIC_KEY_LENGTH,
    RFID_SLOTS,
    CommandId,
    EkeyOperationId,
    LockVolumeId,
)
from .errors import BleValidationError
from .streams import ByteWriter

# The slot a master PIN is written to (NimlyEkeyDevice.masterPincodeSet).
MASTER_PIN_SLOT: Final = 0

# The lock counts time in whole minutes from here (TimeExtensions.DateMinimum).
LOCK_TIME_EPOCH: Final = datetime(2023, 1, 1, tzinfo=UTC)

_UINT16_SLOTS = range(0, 0x10000)


def _check_slot(slot: int, slots: range) -> None:
    # Mirrors Constants.InvalidRange. A slot number is at most five digits
    # and never a PIN, so quoting it is safe.
    if slot not in slots:
        raise BleValidationError(
            f"Invalid SlotNumber, got value {slot}, but expected a value range of {slots.start} - {slots[-1]}"
        )


def _check_length(value: bytes, name: str, length: int) -> None:
    if len(value) != length:
        raise BleValidationError(f"Invalid {name}, expected length {length}, but got length {len(value)}")


def _slot_command(command_id: CommandId, slot: int, slots: range) -> CommandPayload:
    _check_slot(slot, slots)
    return CommandPayload(command_id, ByteWriter().write_uint16(slot).to_bytes())


def _flag_command(command_id: CommandId, enabled: bool) -> CommandPayload:
    return CommandPayload(command_id, ByteWriter().write_uint8(1 if enabled else 0).to_bytes())


def _empty_command(command_id: CommandId) -> CommandPayload:
    return CommandPayload(command_id)


# --- Link and owner authentication -------------------------------------------


def exchange_key_pub_m(public_key: bytes) -> CommandPayload:
    """ExchangeKeyPubM (0x01): the phone's half of the link key exchange."""
    _check_length(public_key, "PubM", PUBLIC_KEY_LENGTH)
    return CommandPayload(CommandId.EXCHANGE_KEY_PUB_M, bytes(public_key))


def user_auth_begin(user_id: int, device_id: bytes) -> CommandPayload:
    """UserAuthBegin (0x22): userId(u8) + deviceId(6); the lock answers with a challenge."""
    _check_length(device_id, "DeviceId", DEVICE_ID_LENGTH)
    return CommandPayload(CommandId.USER_AUTH_BEGIN, ByteWriter().write_uint8(user_id).write_bytes(device_id).to_bytes())


def user_auth_finalize(challenge: bytes) -> CommandPayload:
    """UserAuthFinalize (0x23): the 16-byte answer to the challenge."""
    _check_length(challenge, "Challenge", CHALLENGE_LENGTH)
    return CommandPayload(CommandId.USER_AUTH_FINALIZE, bytes(challenge))


def user_auth_update(user_id: int, credentials: int, public_key: bytes) -> CommandPayload:
    """UserAuthUpdate (0x24): userId(u8) + credentials(u8) + publicKey(64).

    The lock answers with its own public key, and the new owner key is the
    first 16 bytes of the shared secret. AddLockFragment.finishSetup sends
    userId 0 and credentials 0; what a non-zero credentials byte would mean
    is not traced.
    """
    _check_length(public_key, "PublicKey", PUBLIC_KEY_LENGTH)
    return CommandPayload(
        CommandId.USER_AUTH_UPDATE,
        ByteWriter().write_uint8(user_id).write_uint8(credentials).write_bytes(public_key).to_bytes(),
    )


def device_id_set(device_id: bytes) -> CommandPayload:
    """DeviceIdSet (0x30): the 6-byte id the phone identifies itself by."""
    _check_length(device_id, "DeviceId", DEVICE_ID_LENGTH)
    return CommandPayload(CommandId.DEVICE_ID_SET, bytes(device_id))


def device_id_get() -> CommandPayload:
    """DeviceIdGet (0x31)."""
    return _empty_command(CommandId.DEVICE_ID_GET)


def device_name_set(name: str) -> CommandPayload:
    """DeviceNameSet (0x32): ASCII, at most 8 characters, NUL-padded to 9 bytes.

    AddLockFragment.finishSetup sends the lock's name this way during
    enrollment, cut to 8 bytes.
    """
    return CommandPayload(CommandId.DEVICE_NAME_SET, ByteWriter().write_string(name, DEVICE_NAME_MAX_LENGTH).to_bytes())


def device_name_get() -> CommandPayload:
    """DeviceNameGet (0x33)."""
    return _empty_command(CommandId.DEVICE_NAME_GET)


def server_key_update(server_public_key: bytes) -> CommandPayload:
    """ServerKeyUpdate (0x42): a 64-byte public key; the lock answers with its own."""
    _check_length(server_public_key, "ServerPublicKey", PUBLIC_KEY_LENGTH)
    return CommandPayload(CommandId.SERVER_KEY_UPDATE, bytes(server_public_key))


# --- Credentials in slots ----------------------------------------------------


def pin_code_set(slot: int, pin: str, *, ignore_slot_check: bool = False) -> CommandPayload:
    """PinCodeSet (0x52): slot(u16) + length(u8) + the PIN in ASCII.

    The PIN is 4-8 digits. The slot must be 800-899 unless ignore_slot_check
    is set, which the app does for exactly one case, the master PIN in slot
    0 (see master_pin_code_set). Whether the lock takes any other slot
    outside 800-899 is untested. Even unchecked, the slot must fit its u16.
    """
    if not PIN_LENGTH_MIN <= len(pin) <= PIN_LENGTH_MAX:
        raise BleValidationError(
            f"Invalid Pincode, expected a length of {PIN_LENGTH_MIN} - {PIN_LENGTH_MAX}, but got length {len(pin)}"
        )
    # isdigit() would pass other scripts' digits; the lock takes 0-9 only.
    if not all("0" <= char <= "9" for char in pin):
        raise BleValidationError("Invalid Pincode, only the characters 0-9 are permitted")
    _check_slot(slot, _UINT16_SLOTS if ignore_slot_check else PIN_SLOTS)
    data = ByteWriter().write_uint16(slot).write_uint8(len(pin)).write_raw_string(pin).to_bytes()
    return CommandPayload(CommandId.PIN_CODE_SET, data)


def master_pin_code_set(pin: str) -> CommandPayload:
    """PinCodeSet (0x52) for the master PIN, slot 0 with the slot check skipped.

    The app offers this only on models whose LockModelId features include
    master_pin.
    """
    return pin_code_set(MASTER_PIN_SLOT, pin, ignore_slot_check=True)


def pin_code_clear(slot: int) -> CommandPayload:
    """PinCodeClear (0x53): slot(u16), 800-899."""
    return _slot_command(CommandId.PIN_CODE_CLEAR, slot, PIN_SLOTS)


def rfid_code_clear(slot: int) -> CommandPayload:
    """RfidCodeClear (0x55): slot(u16), 900-999."""
    return _slot_command(CommandId.RFID_CODE_CLEAR, slot, RFID_SLOTS)


def scan_rfid_code(slot: int) -> CommandPayload:
    """ScanRfidCode (0x56): slot(u16), 900-999; the lock waits for a tag."""
    return _slot_command(CommandId.SCAN_RFID_CODE, slot, RFID_SLOTS)


def fingerprint_scan(slot: int) -> CommandPayload:
    """FingerprintScan (0x57): slot(u16), 150-199; the lock waits for a finger."""
    return _slot_command(CommandId.FINGERPRINT_SCAN, slot, FINGERPRINT_SLOTS)


def fingerprint_clear(slot: int) -> CommandPayload:
    """FingerprintClear (0x58): slot(u16), 150-199."""
    return _slot_command(CommandId.FINGERPRINT_CLEAR, slot, FINGERPRINT_SLOTS)


# --- Lock operation and settings ---------------------------------------------


def ekey_operate(operation: EkeyOperationId) -> CommandPayload:
    """EkeyOperate (0x18): unlock, lock or invalidate the ekey token."""
    return CommandPayload(CommandId.EKEY_OPERATE, ByteWriter().write_uint8(EkeyOperationId(operation)).to_bytes())


def volume_set(volume: LockVolumeId) -> CommandPayload:
    """VolumeSet (0x5A): the LockVolumeId byte."""
    return CommandPayload(CommandId.VOLUME_SET, ByteWriter().write_uint8(LockVolumeId(volume)).to_bytes())


def auto_lock_set(enabled: bool) -> CommandPayload:
    """AutoLockSet (0x5B): 1 or 0."""
    return _flag_command(CommandId.AUTO_LOCK_SET, enabled)


def keypad_enable_set(enabled: bool) -> CommandPayload:
    """KeypadEnableSet (0x5C): 1 or 0. The app offers it only on models with keypad_enable."""
    return _flag_command(CommandId.KEYPAD_ENABLE_SET, enabled)


def current_time_get() -> CommandPayload:
    """CurrentTimeGet (0x40); the answer is a u32."""
    return _empty_command(CommandId.CURRENT_TIME_GET)


def current_time_set(time: int) -> CommandPayload:
    """CurrentTimeSet (0x41): time as u32 LE, in lock minutes (see to_lock_time).

    AddLockFragment.finishSetup sends TimeExtensions.currentUint32Time(),
    minutes since LOCK_TIME_EPOCH, right after DeviceIdSet.
    """
    return CommandPayload(CommandId.CURRENT_TIME_SET, ByteWriter().write_uint32(time).to_bytes())


def to_lock_time(moment: datetime) -> int:
    """Whole minutes from LOCK_TIME_EPOCH to moment (TimeExtensions.dateToUint32).

    moment must be timezone-aware; the lock's clock is UTC. Like the app,
    a moment before the epoch is refused.
    """
    if moment.tzinfo is None:
        raise BleValidationError("Lock time needs a timezone-aware datetime")
    if moment < LOCK_TIME_EPOCH:
        raise BleValidationError("Lock time cannot be earlier than 2023-01-01 00:00 UTC")
    return (moment - LOCK_TIME_EPOCH) // timedelta(minutes=1)


def from_lock_time(minutes: int) -> datetime:
    """The UTC moment a lock time names (TimeExtensions.uint32ToDate)."""
    return LOCK_TIME_EPOCH + timedelta(minutes=minutes)


# --- Readouts ------------------------------------------------------------------


def batt_info_get() -> CommandPayload:
    """BattInfoGet (0x5D)."""
    return _empty_command(CommandId.BATT_INFO_GET)


def device_log_get() -> CommandPayload:
    """DeviceLogGet (0x44)."""
    return _empty_command(CommandId.DEVICE_LOG_GET)


def device_model_get() -> CommandPayload:
    """DeviceModelGet (0x62); needs firmware 4.7.90 or newer."""
    return _empty_command(CommandId.DEVICE_MODEL_GET)
