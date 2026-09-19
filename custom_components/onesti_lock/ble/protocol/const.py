"""Wire constants and enums for the Onesti/Nimly BLE protocol.

Everything a frame is built from or parsed into: the MTU the framing is cut
for, the Layer 1-3 header layouts, command and response ids, status bytes, the
field lengths the builders check, slot ranges and the enums the payloads
carry. What the client needs beyond the wire (GATT UUIDs, timing, the factory
owner credential) is in client/const.py, and the cipher's own sizes are in
crypto.py.

Every value here is transcribed from the decompiled Nimly BLE app
(easyaccess.ekey.app 1.5.2, package com.nimly.ekey.ble). The Java source a
value comes from is named next to it, relative to that package, so anyone can
check it again instead of trusting this file. None of it has been confirmed
against a lock over the air.

Enum members use Python names; the app's own name is in the comment where the
two differ in more than case.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Final

# --- Link layer (connections/BleConnection.java, communication/streams/) -----

# The app asks for this MTU and never more (BleConnection.DefaultMtu).
DEFAULT_MTU: Final = 23
# ATT write header; PayloadStream.getPayloadMax subtracts it from the MTU.
ATT_OVERHEAD: Final = 3

# --- Framing (communication/packets, commands, responses, blobs) -------------

# Layer 1, Packet: [type:1][length:1][rfu:1][seq:1][payload].
PACKET_HEADER_SIZE: Final = 4
# Packet.toData refuses a payload longer than the one-byte length field.
PACKET_PAYLOAD_MAX: Final = 255
# PayloadWork numbers the packets of one outgoing payload from 1.
FIRST_SEQUENCE_NUMBER: Final = 1
# Layer 2, Command: [id:1][length:1][ref:1][rfu:1][payload].
COMMAND_HEADER_SIZE: Final = 4
# Command.serialize rejects a CommandRef outside 1-254.
COMMAND_REF_MIN: Final = 1
COMMAND_REF_MAX: Final = 254
# CommandStream.nextCommandRef: firmware below 4.7.90 gets the fixed ref 16 on
# every command; newer firmware gets a counter that runs 1-127 and wraps to 1.
COMMAND_REF_STATIC: Final = 16
COMMAND_REF_COUNTER_WRAP: Final = 128
# Layer 3, Response: [id:1][length:1][ref:1][status:1][payload].
RESPONSE_HEADER_SIZE: Final = 4
# Blob header inside a BlobStart packet: [flags:1][total length:u16 LE][rfu:1].
BLOB_HEADER_SIZE: Final = 4
# Bit 0 of the blob flags: the reassembled payload is encrypted.
BLOB_FLAG_ENCRYPTED: Final = 0x01

# --- Field lengths (settings/Constants.java) --------------------------------

# secp256r1 public key on the wire: X then Y, 32 bytes each.
PUBLIC_KEY_LENGTH: Final = 64
CHALLENGE_LENGTH: Final = 16
DEVICE_ID_LENGTH: Final = 6
DEVICE_ID_SEED_LENGTH: Final = 2
EKEY_AUTH_TOKEN_LENGTH: Final = 32
# The advertisement seed of a lock nobody has enrolled (protocol/advertisement.py).
DEFAULT_DEVICE_ID_SEED: Final = bytes(2)

# --- Strings and credentials (settings/Constants.java) -----------------------

CHARACTER_SET: Final = "ascii"
DEVICE_NAME_MAX_LENGTH: Final = 9
USER_NAME_MAX_LENGTH: Final = 12
EKEY_USER_NAME_MAX_LENGTH: Final = 12
# PinCodeSet also refuses anything but the digits 0-9.
PIN_LENGTH_MIN: Final = 4
PIN_LENGTH_MAX: Final = 8

# Slots each command class checks before it sends (VerifyExtensions.verifyRange
# in commands/*/Command*.java). These are BLE slot numbers; Zigbee numbers the
# same lock differently (docs/slot-numbering.md). CommandPincodeSet can skip the
# check (ignoreSlotNumberCheck); whether the lock accepts a PIN slot outside
# 800-899 is untested.
PIN_SLOTS: Final = range(800, 900)
FINGERPRINT_SLOTS: Final = range(150, 200)
# The Java source spells the lower bound TypedValues.Custom.TYPE_INT, an
# unrelated androidx constant that jadx inlined by value: 900.
RFID_SLOTS: Final = range(900, 1000)

# --- Firmware (settings/Constants.java, devices/) -----------------------------

type FirmwareVersion = tuple[int, int, int]

# Below this DeviceModelGet, PinCodeSet and the other admin operations report
# themselves unavailable, and command refs are static
# (MinimumRequiredDeviceModelSoftwareRevisionString).
MIN_FIRMWARE_ADMIN: Final[FirmwareVersion] = (4, 7, 90)


# --- Enums --------------------------------------------------------------------


class PacketTypeId(IntEnum):
    """Layer 1 packet type (communication/packets/PacketTypeId.java)."""

    SINGLE = 0x01
    SINGLE_ENCRYPTED = 0x02
    BLOB_START = 0x03
    BLOB_STREAM = 0x04
    BLOB_COMPLETE = 0x05
    ACK = 0x06
    NAC = 0x07
    ERROR = 0xF0


class CommandId(IntEnum):
    """Layer 2 command id (communication/commands/CommandId.java).

    Note the pairs around 0x55-0x58: RFID is 0x55 clear and 0x56 scan,
    fingerprint is 0x57 scan and 0x58 clear. The slot range each command class
    checks is what pins the pairing down.
    """

    EXCHANGE_KEY_PUB_M = 0x01
    EKEY_USER_AUTH = 0x17
    EKEY_OPERATE = 0x18
    EKEY_USER_ADD = 0x1B
    EKEY_USER_REMOVE = 0x1C
    EKEY_USERS_LIST = 0x1D
    EKEY_DEVICE_INFO_GET = 0x1F
    EKEY_DEVICE_INFO_SET = 0x20
    USER_AUTH_BEGIN = 0x22
    USER_AUTH_FINALIZE = 0x23
    USER_AUTH_UPDATE = 0x24
    DEVICE_ID_SET = 0x30
    DEVICE_ID_GET = 0x31
    DEVICE_NAME_SET = 0x32
    DEVICE_NAME_GET = 0x33
    CURRENT_TIME_GET = 0x40
    CURRENT_TIME_SET = 0x41
    SERVER_KEY_UPDATE = 0x42
    DEVICE_LOG_GET = 0x44
    PIN_CODE_SET = 0x52
    PIN_CODE_CLEAR = 0x53
    RFID_CODE_CLEAR = 0x55
    SCAN_RFID_CODE = 0x56
    FINGERPRINT_SCAN = 0x57
    FINGERPRINT_CLEAR = 0x58
    VOLUME_SET = 0x5A
    AUTO_LOCK_SET = 0x5B
    KEYPAD_ENABLE_SET = 0x5C
    BATT_INFO_GET = 0x5D
    DEVICE_MODEL_GET = 0x62
    FACTORY_RESET_MODULE = 0x70


class ResponseId(IntEnum):
    """Layer 3 response id (communication/responses/ResponseId.java).

    A response carries the id of the command it answers. LOCK_STATUS and
    USER_ADDED have no command: the lock sends them on its own.
    """

    EXCHANGE_KEY_PUB_L = 0x01
    EKEY_USER_AUTH = 0x17
    EKEY_OPERATE = 0x18
    EKEY_USER_ADD = 0x1B
    EKEY_USER_REMOVE = 0x1C
    EKEY_USERS_LIST = 0x1D
    EKEY_DEVICE_INFO_GET = 0x1F
    EKEY_DEVICE_INFO_SET = 0x20
    USER_ADDED = 0x14
    USER_AUTH_BEGIN = 0x22
    USER_AUTH_FINALIZE = 0x23
    USER_AUTH_UPDATE = 0x24
    DEVICE_ID_SET = 0x30
    DEVICE_ID_GET = 0x31
    DEVICE_NAME_SET = 0x32
    DEVICE_NAME_GET = 0x33
    CURRENT_TIME_GET = 0x40
    CURRENT_TIME_SET = 0x41
    SERVER_KEY_UPDATE = 0x42
    DEVICE_LOG_GET = 0x44
    PIN_CODE_SET = 0x52
    PIN_CODE_CLEAR = 0x53
    RFID_CODE_CLEAR = 0x55
    SCAN_RFID_CODE = 0x56
    FINGERPRINT_SCAN = 0x57
    FINGERPRINT_CLEAR = 0x58
    VOLUME_SET = 0x5A
    AUTO_LOCK_SET = 0x5B
    KEYPAD_ENABLE_SET = 0x5C
    BATT_INFO_GET = 0x5D
    LOCK_STATUS = 0x60
    DEVICE_MODEL_GET = 0x62
    FACTORY_RESET_MODULE = 0x70


class ResponseStatusId(IntEnum):
    """Status byte of a response (communication/responses/ResponseStatusId.java).

    Anything but SUCCESS fails the command; errors.error_for_status maps each
    one to its exception.
    """

    SUCCESS = 0
    FAILED = 1
    NOT_AVAILABLE = 2
    INTERNAL_ERROR = 3
    PARAMETER_ERROR = 4
    LENGTH_ERROR = 5
    NOT_FOUND_ERROR = 6
    NO_MATCH_ERROR = 7
    NOT_SUPPORTED_ERROR = 8
    NOT_VALID_ERROR = 9
    SECURITY_ERROR = 10


@dataclass(frozen=True, slots=True)
class ModelFeatures:
    """What the app lets a model do, beyond the commands every model takes."""

    fingerprint: bool
    keypad_enable: bool
    master_pin: bool


class DeviceFeature(Enum):
    """Whether the app offers an operation on a lock (operations/DeviceFeature.java).

    Every operation in admin/devices/NimlyEkeyDevice.java answers with one of
    these, and the app runs it only when the answer is available
    (NimlyEkeyBleExtensionsKt.toSuspend). protocol/features.py holds the
    rules. The app's sixth value, UnavailableConnection, is never returned by
    an operation and is left out.
    """

    AVAILABLE_ALWAYS = "available_always"
    AVAILABLE = "available"
    # The model lacks it.
    UNAVAILABLE = "unavailable"
    # The firmware is below 4.7.90.
    UNAVAILABLE_VERSION = "unavailable_version"
    # The firmware is below 4.7.90, so the model was never asked; used for
    # the model-dependent operations.
    UNAVAILABLE_UNKNOWN = "unavailable_unknown"

    @property
    def available(self) -> bool:
        return self in (DeviceFeature.AVAILABLE_ALWAYS, DeviceFeature.AVAILABLE)


class LockModelId(IntEnum):
    """DeviceModelGet answer (communication/responses/shared/LockModelId.java).

    The app reads an unknown byte as UNKNOWN rather than failing.
    """

    UNKNOWN = 0
    EASY_FINGER_TOUCH = 8
    EASY_CODE_TOUCH = 9
    NIMLY_CODE = 21
    NIMLY_TOUCH = 22
    NIMLY_PRO = 23
    NIMLY_INDOOR = 24
    NIMLY_KEYBOX = 26
    NIMLY_TWIST = 27
    NIMLY_CODE_2 = 31
    NIMLY_TOUCH_2 = 32
    NIMLY_PRO_24 = 33
    NIMLY_INDOOR_2 = 34
    NIMLY_KEYBOX_2 = 36
    NIMLY_TWIST_2 = 37

    @property
    def features(self) -> ModelFeatures:
        return _MODEL_FEATURES[self]


_NONE = ModelFeatures(fingerprint=False, keypad_enable=False, master_pin=False)
# The three booleans the Java enum constructor takes, in its order.
_MODEL_FEATURES: Final[dict[LockModelId, ModelFeatures]] = {
    LockModelId.UNKNOWN: _NONE,
    LockModelId.EASY_FINGER_TOUCH: ModelFeatures(fingerprint=True, keypad_enable=False, master_pin=False),
    LockModelId.EASY_CODE_TOUCH: _NONE,
    LockModelId.NIMLY_CODE: _NONE,
    LockModelId.NIMLY_TOUCH: _NONE,
    LockModelId.NIMLY_PRO: ModelFeatures(fingerprint=True, keypad_enable=False, master_pin=False),
    LockModelId.NIMLY_INDOOR: _NONE,
    LockModelId.NIMLY_KEYBOX: _NONE,
    LockModelId.NIMLY_TWIST: _NONE,
    LockModelId.NIMLY_CODE_2: ModelFeatures(fingerprint=False, keypad_enable=True, master_pin=True),
    LockModelId.NIMLY_TOUCH_2: ModelFeatures(fingerprint=False, keypad_enable=True, master_pin=True),
    LockModelId.NIMLY_PRO_24: ModelFeatures(fingerprint=True, keypad_enable=True, master_pin=True),
    LockModelId.NIMLY_INDOOR_2: ModelFeatures(fingerprint=False, keypad_enable=True, master_pin=True),
    LockModelId.NIMLY_KEYBOX_2: ModelFeatures(fingerprint=False, keypad_enable=True, master_pin=True),
    LockModelId.NIMLY_TWIST_2: ModelFeatures(fingerprint=False, keypad_enable=True, master_pin=True),
}


class LockStatusId(IntEnum):
    """Result of a fingerprint or RFID scan (communication/responses/shared/LockStatusId.java)."""

    OK = 0
    ERROR = 1
    UNKNOWN_COMMAND = 2
    CRC_ERROR = 3
    INVALID_DATA = 4
    NO_SPACE_LEFT = 5
    NO_MATCH = 6


class LockStateId(IntEnum):
    """Bolt state in a LockStatus notification (responses/lockstatus/LockStateId.java)."""

    LOCKED = 1
    UNLOCKED = 2


class DoorlockMethodId(IntEnum):
    """How the bolt was moved, in a LockStatus notification (responses/lockstatus/DoorlockMethodId.java)."""

    KEY = 0
    BUTTON = 1
    # The keypad.
    PANEL = 2
    FINGERPRINT = 3
    RFID = 4
    OTHER = 5


class EkeyOperationId(IntEnum):
    """EkeyOperate argument (commands/ekeyoperation/EkeyOperationId.java)."""

    UNLOCK = 1
    LOCK = 2
    INVALIDATE_TOKEN = 3


class LockVolumeId(IntEnum):
    """VolumeSet argument (commands/volumeset/LockVolumeId.java)."""

    OFF = 0
    LOW = 1
    NORMAL = 2


class UserAddedStatusId(IntEnum):
    """What a UserAdded notification reports (responses/useradded/UserAddedStatusId.java)."""

    NOT_ADDED = 0
    PIN_CODE = 1
    RFID_CODE = 2
    FINGERPRINT = 3
    SLOT_OCCUPIED = 4
