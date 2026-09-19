"""Byte vectors for the BLE protocol library tests.

Nothing here was captured from a lock. Each vector is one of two kinds, and
the comment above it says which:

- documented: an example written out in docs/nimly-ble-app/, itself read from
  the decompiled app.
- derived: assembled by hand from the app's serializer for that frame, cited by
  class. It proves our builder does what the app's code does, not what the lock
  accepts. The app classes live under
  reversing/nimly-ble-decompiled/sources/com/nimly/ekey/ble/ (gitignored,
  local only).

The values in the frames (slots, keys, battery level, challenge bytes) are
arbitrary test inputs unless the comment says otherwise. The PIN "8832" is the
docs' own example, not anyone's code.

Hardware captures replace or confirm these once a lock is on the bench.
"""
from __future__ import annotations


def _hex(text: str) -> bytes:
    return bytes.fromhex(text)


# --- Command payloads (Layer 2 payload only, what serializeCommand writes) ---

# documented: docs/nimly-ble-app/ble-protocol.md, "PIN code setting (0x52)".
# Slot 803 as uint16 LE, length 4, "8832" in ASCII. Matches
# CommandPincodeSet.serializeCommand. This is the payload, not the whole
# command: the docs example leaves out the Layer 2 header.
PIN_CODE_SET_SLOT_803_PIN_8832_PAYLOAD = _hex("23 03 04 38 38 33 32")

# derived: CommandPincodeClear.serializeCommand, writeUInt16(slot).
PIN_CODE_CLEAR_SLOT_803_PAYLOAD = _hex("23 03")

# derived: CommandFingerprintScan / CommandFingerprintClear, writeUInt16(slot),
# at both ends of the checked range 150-199.
FINGERPRINT_SCAN_SLOT_150_PAYLOAD = _hex("96 00")
FINGERPRINT_CLEAR_SLOT_199_PAYLOAD = _hex("C7 00")

# derived: CommandScanRfidCode / CommandRfidCodeClear, writeUInt16(slot), at
# both ends of the checked range 900-999.
SCAN_RFID_CODE_SLOT_900_PAYLOAD = _hex("84 03")
RFID_CODE_CLEAR_SLOT_999_PAYLOAD = _hex("E7 03")

# derived: CommandUserAuthBegin.serializeCommand, userId(u8) + deviceId(6B),
# with the default owner credential AddLockFragment uses on a fresh lock:
# userId 0, deviceId 00 x 6 (docs/nimly-ble-app/ble-auth-provisioning.md).
USER_AUTH_BEGIN_DEFAULT_PAYLOAD = _hex("00 00 00 00 00 00 00")

# derived: CommandUserAuthUpdate.serializeCommand, userId(u8) +
# credentials(u8) + publicKey(64B). userId 0, credentials 1 and the key bytes
# 0x00-0x3F are arbitrary; what the credentials byte means is not traced.
USER_AUTH_UPDATE_PAYLOAD = _hex("00 01") + bytes(range(64))

# derived: CommandEkeyOperate.serializeCommand, the EkeyOperationId byte.
EKEY_OPERATE_UNLOCK_PAYLOAD = _hex("01")
EKEY_OPERATE_LOCK_PAYLOAD = _hex("02")

# derived: CommandDeviceIdSet.serializeCommand, the 6 bytes as they are.
DEVICE_ID_SET_PAYLOAD = _hex("01 02 03 04 05 06")

# derived: CommandCurrentTimeSet.serializeCommand, writeUInt32(time) LE.
# 0x12345678 is a marker, not a meaningful time.
CURRENT_TIME_SET_0X12345678_PAYLOAD = _hex("78 56 34 12")

# derived: CommandAutoLockSet / CommandKeypadEnableSet write 1 or 0,
# CommandVolumeSet the LockVolumeId byte (NORMAL = 2).
AUTO_LOCK_SET_ENABLED_PAYLOAD = _hex("01")
KEYPAD_ENABLE_SET_DISABLED_PAYLOAD = _hex("00")
VOLUME_SET_NORMAL_PAYLOAD = _hex("02")

# --- Whole Layer 2 commands (Command.serialize) ------------------------------

# derived: Command.serialize writes id, payload length, ref, rfu 0, payload.
# Ref 16 is the static ref firmware below 4.7.90 gets on every command
# (CommandStream.nextCommandRef).
PIN_CODE_SET_SLOT_803_PIN_8832_REF_16_COMMAND = _hex("52 07 10 00") + PIN_CODE_SET_SLOT_803_PIN_8832_PAYLOAD

# derived: Command.serialize with ref 1, the first value of the counter newer
# firmware gets.
USER_AUTH_BEGIN_DEFAULT_REF_1_COMMAND = _hex("22 07 01 00") + USER_AUTH_BEGIN_DEFAULT_PAYLOAD

# derived: a command with no payload (CommandBattInfoGet writes nothing).
BATT_INFO_GET_REF_1_COMMAND = _hex("5D 00 01 00")

# derived: CommandExchangeKeyPubM with the public key bytes 0x00-0x3F, ref 1.
# 68 bytes, too long for one packet at MTU 23.
EXCHANGE_KEY_PUB_M_REF_1_COMMAND = _hex("01 40 01 00") + bytes(range(64))

# --- Layer 1 packets (Packet.toData, PayloadStream) --------------------------

# derived: PayloadStream.writeSingle, type Single, length, rfu 0, sequence 1
# (PayloadWork numbers the packets of each payload from 1). Unencrypted, so
# this only shows the framing: after the key exchange every command is
# encrypted and padded to 16 bytes.
BATT_INFO_GET_SINGLE_PACKET = _hex("01 04 00 01") + BATT_INFO_GET_REF_1_COMMAND

# derived: PayloadStream.writeBlob and writeChunk at MTU 23, splitting
# EXCHANGE_KEY_PUB_M_REF_1_COMMAND. Each write carries at most MTU - 3 = 20
# bytes. A payload goes as a blob once its length + 4 exceeds 20 - 4, so from
# 13 bytes up. BlobStart carries the 4-byte blob header (flags 0 = not
# encrypted, total length 0x0044 LE, rfu 0) and the first 12 bytes; the
# packet's length byte is 16, the whole packet payload, since Packet.toData
# writes payload.length. BlobStream packets carry 16 bytes each, and the last
# chunk goes as BlobComplete. Sequence numbers run 1-5.
EXCHANGE_KEY_PUB_M_BLOB_PACKETS_MTU_23 = (
    _hex("03 10 00 01 00 44 00 00") + EXCHANGE_KEY_PUB_M_REF_1_COMMAND[0:12],
    _hex("04 10 00 02") + EXCHANGE_KEY_PUB_M_REF_1_COMMAND[12:28],
    _hex("04 10 00 03") + EXCHANGE_KEY_PUB_M_REF_1_COMMAND[28:44],
    _hex("04 10 00 04") + EXCHANGE_KEY_PUB_M_REF_1_COMMAND[44:60],
    _hex("05 08 00 05") + EXCHANGE_KEY_PUB_M_REF_1_COMMAND[60:68],
)

# --- Layer 3 responses (Response.deserialize + the Response* payload classes)

# derived: status-only responses to ref 1. Status 0 SUCCESS, 6 NOT_FOUND_ERROR.
PIN_CODE_SET_SUCCESS_REF_1_RESPONSE = _hex("52 00 01 00")
PIN_CODE_CLEAR_NOT_FOUND_REF_1_RESPONSE = _hex("53 00 01 06")

# derived: ResponseBattInfoGet reads level(u16 LE), lowBatteryFlag(u8, 1 =
# low), percent(u8). Level 0x16A8 = 5800 in a unit the app never names; flag 0;
# 80 %.
BATT_INFO_GET_REF_1_RESPONSE = _hex("5D 04 01 00 A8 16 00 50")

# derived: ResponseUserAuthBegin reads a 16-byte challenge (here 0xA0-0xAF).
USER_AUTH_BEGIN_REF_1_RESPONSE = _hex("22 10 01 00") + bytes(range(0xA0, 0xB0))

# derived: ResponseDeviceModelGet reads one LockModelId byte; 0x17 is NimlyPro.
DEVICE_MODEL_GET_NIMLY_PRO_REF_1_RESPONSE = _hex("62 01 01 00 17")

# derived: ResponseDeviceLogGet reads length(u8) then that many bytes. The
# content of a log entry is not decoded anywhere in the app.
DEVICE_LOG_GET_REF_1_RESPONSE = _hex("44 04 01 00 03 AA BB CC")

# derived: ResponseLockStatus reads slot(u16 LE), LockStateId, DoorlockMethodId:
# slot 803 unlocked from the keypad (PANEL). The lock sends this unasked, and
# which ref it carries then is not known; 0 is a guess.
LOCK_STATUS_SLOT_803_UNLOCKED_PANEL_RESPONSE = _hex("60 04 00 00 23 03 02 02")
