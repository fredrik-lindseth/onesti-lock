"""Offline implementation of the Onesti/Nimly BLE protocol.

Pure Python with no Home Assistant imports, and nothing in the integration
imports it yet: the transport that connects it to a lock comes later. The
protocol is described in docs/nimly-ble-app/, and every value in const.py was
read out of the decompiled Nimly BLE app, not guessed.

The pieces a caller needs are exported here:

    async with Session(transport) as session:
        enrollment = await enroll(session, name="Door")   # a factory-reset lock
    # store enrollment.to_dict(); later, on a new connection:
    async with Session(transport) as session:
        await authenticate_owner(session, enrollment.owner_credential)
        await session.send(commands.pin_code_set(803, pin))

A Transport is the caller's: it wraps one connected lock (transport.py).
commands builds every command, responses parses every answer, and errors
holds the exception hierarchy under BleError.
"""
from __future__ import annotations

from . import commands, responses
from .advertisement import Advertisement, parse_advertisement
from .auth import (
    BleEnrollmentError,
    Enrollment,
    EnrollmentStep,
    authenticate_owner,
    enroll,
    new_device_id,
    resume_enrollment,
)
from .crypto import DEFAULT_OWNER_CREDENTIAL, OwnerCredential
from .errors import (
    BleDisconnectedError,
    BleError,
    BleFirmwareTooOldError,
    BleOperationError,
    BleProtocolError,
    BleSecurityError,
    BleTimeoutError,
    BleValidationError,
)
from .session import LockEvent, Session
from .transport import Transport

__all__ = [
    "DEFAULT_OWNER_CREDENTIAL",
    "Advertisement",
    "BleDisconnectedError",
    "BleEnrollmentError",
    "BleError",
    "BleFirmwareTooOldError",
    "BleOperationError",
    "BleProtocolError",
    "BleSecurityError",
    "BleTimeoutError",
    "BleValidationError",
    "Enrollment",
    "EnrollmentStep",
    "LockEvent",
    "OwnerCredential",
    "Session",
    "Transport",
    "authenticate_owner",
    "commands",
    "enroll",
    "new_device_id",
    "parse_advertisement",
    "responses",
    "resume_enrollment",
]
