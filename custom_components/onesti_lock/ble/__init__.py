"""The Onesti/Nimly BLE protocol, in pure Python.

This is the public API. Nothing in the package imports Home Assistant, and
nothing reaches outside it. The integration imports it as .ble. Anything
outside Home Assistant, such as a command line tool, cannot import it as
custom_components.onesti_lock.ble, because that runs the component's own
__init__.py, which imports Home Assistant. It puts custom_components/onesti_lock
on sys.path and does import ble instead (docs/nimly-ble-app/ble-library.md).
The protocol is described in docs/nimly-ble-app/, and every constant was read
out of the decompiled Nimly BLE app, not guessed.

    async with Session(transport) as session:
        enrollment = await enroll(session, name="Door")   # a factory-reset lock
    # store enrollment.to_dict(); on a new connection:
    async with Session(transport) as session:
        await authenticate_owner(session, enrollment.owner_credential)
        await session.send(commands.pin_code_set(803, pin))

The caller supplies the Transport: one connected lock on some Bluetooth
stack, found by ADVERTISING_UUID and reached through the GATT UUIDs below.
commands builds every command, responses parses every answer, and every
exception derives from BleError.

The package is layered, each layer importing only those below it:

    protocol/   frames, ids and payloads; no crypto, no I/O
    crypto.py   the key exchange and AES, as the app does them
    client/     transport seam, session, owner login, enrollment

errors.py serves all three. It imports only protocol/const.py, so protocol/
can raise its errors without an import cycle.
"""
from __future__ import annotations

from .client.auth import DEFAULT_OWNER_CREDENTIAL, OwnerCredential, authenticate_owner
from .client.const import (
    ADVERTISING_UUID,
    COMMUNICATION_CHARACTERISTIC_UUID,
    SERVICE_UUID,
    SOFTWARE_REVISION_CHARACTERISTIC_UUID,
)
from .client.enrollment import (
    BleEnrollmentError,
    Enrollment,
    EnrollmentStep,
    enroll,
    new_device_id,
    resume_enrollment,
)
from .client.session import EventListener, LockEvent, Session
from .client.transport import DisconnectCallback, NotificationCallback, Transport
from .errors import (
    BleDisconnectedError,
    BleError,
    BleFailedError,
    BleFeatureUnavailableError,
    BleFirmwareTooOldError,
    BleInternalError,
    BleLengthError,
    BleNoMatchError,
    BleNotAvailableError,
    BleNotFoundError,
    BleNotSupportedError,
    BleNotValidError,
    BleOperationError,
    BleParameterError,
    BleProtocolError,
    BleSecurityError,
    BleSessionStateError,
    BleTimeoutError,
    BleValidationError,
)
from .protocol import commands, responses
from .protocol.advertisement import Advertisement, parse_advertisement
from .protocol.const import (
    FINGERPRINT_SLOTS,
    PIN_SLOTS,
    RFID_SLOTS,
    DeviceFeature,
    DoorlockMethodId,
    EkeyOperationId,
    FirmwareVersion,
    LockModelId,
    LockStateId,
    LockStatusId,
    LockVolumeId,
    ModelFeatures,
    ResponseStatusId,
    UserAddedStatusId,
)
from .protocol.responses import LockStatus, UserAdded

__all__ = [
    "ADVERTISING_UUID",
    "COMMUNICATION_CHARACTERISTIC_UUID",
    "DEFAULT_OWNER_CREDENTIAL",
    "FINGERPRINT_SLOTS",
    "PIN_SLOTS",
    "RFID_SLOTS",
    "SERVICE_UUID",
    "SOFTWARE_REVISION_CHARACTERISTIC_UUID",
    "Advertisement",
    "BleDisconnectedError",
    "BleEnrollmentError",
    "BleError",
    "BleFailedError",
    "BleFeatureUnavailableError",
    "BleFirmwareTooOldError",
    "BleInternalError",
    "BleLengthError",
    "BleNoMatchError",
    "BleNotAvailableError",
    "BleNotFoundError",
    "BleNotSupportedError",
    "BleNotValidError",
    "BleOperationError",
    "BleParameterError",
    "BleProtocolError",
    "BleSecurityError",
    "BleSessionStateError",
    "BleTimeoutError",
    "BleValidationError",
    "DeviceFeature",
    "DisconnectCallback",
    "DoorlockMethodId",
    "EkeyOperationId",
    "Enrollment",
    "EnrollmentStep",
    "EventListener",
    "FirmwareVersion",
    "LockEvent",
    "LockModelId",
    "LockStateId",
    "LockStatus",
    "LockStatusId",
    "LockVolumeId",
    "ModelFeatures",
    "NotificationCallback",
    "OwnerCredential",
    "ResponseStatusId",
    "Session",
    "Transport",
    "UserAdded",
    "UserAddedStatusId",
    "authenticate_owner",
    "commands",
    "enroll",
    "new_device_id",
    "parse_advertisement",
    "responses",
    "resume_enrollment",
]
