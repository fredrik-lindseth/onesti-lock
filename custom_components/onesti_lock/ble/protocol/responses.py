"""Typed readings of Layer 3 response payloads.

One parser per response class in communication/responses/ that carries data,
each reading what that class's deserializeResponse reads. A parser first
checks that the response is the one it parses, as Response.getResponsePayload
does, then raises the mapped BleOperationError when the status is not
SUCCESS, as CommandStream does before anyone reads the payload. The two
events, LockStatus and UserAdded, skip the status check: the app never looks
at their status byte.

Bytes after the fields are ignored, as the app ignores them. A payload too
short for its fields raises BleProtocolError.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from ..errors import BleProtocolError
from .commands import from_lock_time
from .const import (
    CHALLENGE_LENGTH,
    DEVICE_ID_LENGTH,
    DEVICE_NAME_MAX_LENGTH,
    PUBLIC_KEY_LENGTH,
    DoorlockMethodId,
    LockModelId,
    LockStateId,
    LockStatusId,
    ResponseId,
    UserAddedStatusId,
)
from .response import Response
from .streams import ByteReader

# Responses whose payload is empty in the app (their deserializeResponse
# reads nothing): only the status says anything.
STATUS_ONLY_RESPONSES: Final = frozenset(
    {
        ResponseId.EKEY_OPERATE,
        ResponseId.DEVICE_ID_SET,
        ResponseId.DEVICE_NAME_SET,
        ResponseId.CURRENT_TIME_SET,
        ResponseId.PIN_CODE_SET,
        ResponseId.PIN_CODE_CLEAR,
        ResponseId.RFID_CODE_CLEAR,
        ResponseId.FINGERPRINT_CLEAR,
        ResponseId.VOLUME_SET,
        ResponseId.AUTO_LOCK_SET,
        ResponseId.KEYPAD_ENABLE_SET,
        ResponseId.FACTORY_RESET_MODULE,
    }
)


def _reader(response: Response, expected: ResponseId, *, check_status: bool = True) -> ByteReader:
    if response.response_id != expected:
        raise BleProtocolError(f"Expected a {expected.name} response, got {_name(response.response_id)}")
    if check_status:
        response.raise_for_status()
    return ByteReader(response.payload)


def _name(response_id: ResponseId | int) -> str:
    if isinstance(response_id, ResponseId):
        return response_id.name
    return f"unknown response 0x{response_id:02X}"


def _required[E: (LockStateId, DoorlockMethodId, UserAddedStatusId)](enum: type[E], value: int) -> E:
    # readRequiredUInt8Enum: an unknown value fails the whole response.
    try:
        return enum(value)
    except ValueError:
        raise BleProtocolError(f"Unknown {enum.__name__} value {value}") from None


def check_status_only(response: Response, expected: ResponseId) -> None:
    """Accept a response that carries nothing but its status.

    Raises BleProtocolError for the wrong response and the mapped
    BleOperationError for a failed status.
    """
    if expected not in STATUS_ONLY_RESPONSES:
        raise ValueError(f"{expected.name} carries a payload; use its parser")
    _reader(response, expected)


# --- Link and owner authentication -------------------------------------------


@dataclass(frozen=True, slots=True)
class ExchangeKeyPubL:
    """The lock's half of the link key exchange."""

    public_key: bytes


def parse_exchange_key_pub_l(response: Response) -> ExchangeKeyPubL:
    return ExchangeKeyPubL(_reader(response, ResponseId.EXCHANGE_KEY_PUB_L).read_bytes(PUBLIC_KEY_LENGTH))


@dataclass(frozen=True, slots=True)
class UserAuthBegin:
    """The challenge the owner key has to answer."""

    challenge: bytes


def parse_user_auth_begin(response: Response) -> UserAuthBegin:
    return UserAuthBegin(_reader(response, ResponseId.USER_AUTH_BEGIN).read_bytes(CHALLENGE_LENGTH))


@dataclass(frozen=True, slots=True)
class UserAuthFinalize:
    """What the lock grants after a correct answer. The value is not traced."""

    credentials: int


def parse_user_auth_finalize(response: Response) -> UserAuthFinalize:
    return UserAuthFinalize(_reader(response, ResponseId.USER_AUTH_FINALIZE).read_uint8())


@dataclass(frozen=True, slots=True)
class UserAuthUpdate:
    """The lock's public key; ECDH with it gives the new owner key."""

    public_key: bytes


def parse_user_auth_update(response: Response) -> UserAuthUpdate:
    return UserAuthUpdate(_reader(response, ResponseId.USER_AUTH_UPDATE).read_bytes(PUBLIC_KEY_LENGTH))


@dataclass(frozen=True, slots=True)
class ServerKeyUpdate:
    """The lock's public key, sent back for the server key it was given."""

    lock_public_key: bytes


def parse_server_key_update(response: Response) -> ServerKeyUpdate:
    return ServerKeyUpdate(_reader(response, ResponseId.SERVER_KEY_UPDATE).read_bytes(PUBLIC_KEY_LENGTH))


@dataclass(frozen=True, slots=True)
class DeviceId:
    device_id: bytes


def parse_device_id_get(response: Response) -> DeviceId:
    return DeviceId(_reader(response, ResponseId.DEVICE_ID_GET).read_bytes(DEVICE_ID_LENGTH))


@dataclass(frozen=True, slots=True)
class DeviceName:
    name: str


def parse_device_name_get(response: Response) -> DeviceName:
    return DeviceName(_reader(response, ResponseId.DEVICE_NAME_GET).read_string(DEVICE_NAME_MAX_LENGTH))


# --- Readouts ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BattInfo:
    """BattInfoGet. level is raw; nothing in the app names its unit."""

    level: int
    low_battery: bool
    percent: int


def parse_batt_info(response: Response) -> BattInfo:
    reader = _reader(response, ResponseId.BATT_INFO_GET)
    level = reader.read_uint16()
    # Only exactly 1 counts as low, as in the app.
    low_battery = reader.read_uint8() == 1
    return BattInfo(level, low_battery, reader.read_uint8())


@dataclass(frozen=True, slots=True)
class DeviceModel:
    """DeviceModelGet. An unknown byte reads as UNKNOWN, as in the app; raw keeps it."""

    model: LockModelId
    raw: int


def parse_device_model(response: Response) -> DeviceModel:
    raw = _reader(response, ResponseId.DEVICE_MODEL_GET).read_uint8()
    try:
        model = LockModelId(raw)
    except ValueError:
        model = LockModelId.UNKNOWN
    return DeviceModel(model, raw)


@dataclass(frozen=True, slots=True)
class DeviceLog:
    """DeviceLogGet: a length byte and that many bytes. Nothing in the app decodes them."""

    log: bytes


def parse_device_log(response: Response) -> DeviceLog:
    reader = _reader(response, ResponseId.DEVICE_LOG_GET)
    return DeviceLog(reader.read_bytes(reader.read_uint8()))


@dataclass(frozen=True, slots=True)
class CurrentTime:
    """CurrentTimeGet, in minutes since 2023-01-01 UTC."""

    minutes: int

    @property
    def moment(self) -> datetime:
        return from_lock_time(self.minutes)


def parse_current_time(response: Response) -> CurrentTime:
    return CurrentTime(_reader(response, ResponseId.CURRENT_TIME_GET).read_uint32())


@dataclass(frozen=True, slots=True)
class ScanResult:
    """FingerprintScan or ScanRfidCode: the slot and how the scan went.

    status stays a raw int for a value LockStatusId does not know; the app
    reads it as null rather than failing.
    """

    slot: int
    status: LockStatusId | int


def _parse_scan(response: Response, expected: ResponseId) -> ScanResult:
    reader = _reader(response, expected)
    slot = reader.read_uint16()
    raw = reader.read_uint8()
    try:
        return ScanResult(slot, LockStatusId(raw))
    except ValueError:
        return ScanResult(slot, raw)


def parse_fingerprint_scan(response: Response) -> ScanResult:
    return _parse_scan(response, ResponseId.FINGERPRINT_SCAN)


def parse_scan_rfid_code(response: Response) -> ScanResult:
    return _parse_scan(response, ResponseId.SCAN_RFID_CODE)


# --- Events --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LockStatus:
    """The bolt moved: which slot, which way, by what means."""

    slot: int
    state: LockStateId
    method: DoorlockMethodId


def parse_lock_status(response: Response) -> LockStatus:
    reader = _reader(response, ResponseId.LOCK_STATUS, check_status=False)
    slot = reader.read_uint16()
    state = _required(LockStateId, reader.read_uint8())
    return LockStatus(slot, state, _required(DoorlockMethodId, reader.read_uint8()))


@dataclass(frozen=True, slots=True)
class UserAdded:
    """The lock reports a user added to a slot, and what kind (UserAddedStatusId)."""

    slot: int
    status: UserAddedStatusId


def parse_user_added(response: Response) -> UserAdded:
    reader = _reader(response, ResponseId.USER_ADDED, check_status=False)
    slot = reader.read_uint16()
    return UserAdded(slot, _required(UserAddedStatusId, reader.read_uint8()))


def parse_event(response: Response) -> LockStatus | UserAdded | None:
    """The event in an unsolicited response, or None for anything else.

    Like NimlyEkeyDevice.responseHandler, only a response under
    EVENT_COMMAND_REF counts, and only LockStatus and UserAdded are read.
    """
    if not response.is_event:
        return None
    if response.response_id == ResponseId.LOCK_STATUS:
        return parse_lock_status(response)
    if response.response_id == ResponseId.USER_ADDED:
        return parse_user_added(response)
    return None
