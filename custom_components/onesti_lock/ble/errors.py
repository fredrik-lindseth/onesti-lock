"""Exceptions raised by the BLE protocol library.

Everything the library raises derives from BleError, so a caller can catch the
library as a whole. Below it, the class says whose fault the failure is:

- BleValidationError: an argument the caller passed, refused before anything
  is sent. A slot outside its range, a key of the wrong length, a PIN that is
  not 4-8 digits, but also a frame the length fields cannot carry or an MTU too
  small to frame anything. It is also a ValueError.
- BleSessionStateError: a Session used out of order, such as connecting twice
  or sending before connect() has finished. It is also a RuntimeError. A
  session whose link has gone raises BleDisconnectedError instead, since that
  is the radio, not the caller.
- BleProtocolError: bytes from the lock that do not parse as the protocol
  says they should.
- BleOperationError: the lock parsed the command and answered with a status
  other than SUCCESS. There is one subclass per ResponseStatusId, through
  error_for_status. The app itself has a single
  NimlyEkeyBleOperationException carrying the status
  (exceptions/NimlyEkeyBleOperationException.java); separate classes let a
  caller catch, say, BleSecurityError without inspecting a field.
- BleTimeoutError, BleDisconnectedError: the link. BleTimeoutError is also a
  TimeoutError.
- BleFirmwareTooOldError: the lock's firmware is below what the app connects to.
- BleFeatureUnavailableError: a command the app would not send to this lock,
  for its firmware or its model (protocol/features.py). Nothing was sent.

client/enrollment.py adds BleEnrollmentError, which carries the partial
enrollment and so lives next to it. An exception from the caller's own
Transport passes through unchanged; client/transport.py asks implementations
to raise BleError subclasses too.

No message may carry a PIN. The builders validate a PIN without quoting it, and
the messages here are built only from ids, statuses and lengths.
"""
from __future__ import annotations

from typing import ClassVar, Final

from .protocol.const import (
    MIN_FIRMWARE_ADMIN,
    CommandId,
    DeviceFeature,
    FirmwareVersion,
    LockModelId,
    ResponseId,
    ResponseStatusId,
)


class BleError(Exception):
    """Base class for every error the BLE library raises."""


class BleValidationError(BleError, ValueError):
    """An argument the library refuses before anything is sent.

    Mirrors the app's client-side checks (VerifyExtensions): slot ranges, key
    and id lengths, PIN length and digits. The framing's own limits land here
    too: a CommandRef outside 1-254, a payload longer than its length field,
    an MTU that leaves no room for payload.
    """


class BleSessionStateError(BleError, RuntimeError):
    """A Session used in a state that does not allow the call.

    Connecting a session twice, sending before connect() has finished, or
    asking for the firmware or link keys before the key exchange. These are
    bugs in the caller, not conditions on the link.
    """


class BleProtocolError(BleError):
    """Bytes from the lock that do not parse as the protocol says they should."""


class BleTimeoutError(BleError, TimeoutError):
    """The lock did not answer in time."""


class BleDisconnectedError(BleError):
    """The link dropped before the exchange finished."""


class BleFirmwareTooOldError(BleError):
    """The lock's firmware is below 4.6.0, the floor the app connects to.

    A command gated on a newer firmware raises BleFeatureUnavailableError.
    """

    def __init__(self, firmware: FirmwareVersion, required: FirmwareVersion) -> None:
        self.firmware = firmware
        self.required = required
        super().__init__(f"Lock firmware {_version(firmware)} is below the required {_version(required)}")


class BleFeatureUnavailableError(BleError):
    """The app would not send this command to this lock, so the session did not.

    feature is what the app's feature() answers (protocol/features.py):
    UNAVAILABLE_VERSION or UNAVAILABLE_UNKNOWN below firmware 4.7.90,
    UNAVAILABLE when the model lacks it. firmware and model are what the
    session read; model is None below 4.7.90. Session.send(...,
    skip_app_gates=True) sends the command anyway, for testing a lock.
    """

    def __init__(
        self,
        command: CommandId,
        feature: DeviceFeature,
        firmware: FirmwareVersion,
        model: LockModelId | None,
    ) -> None:
        self.command = command
        self.feature = feature
        self.firmware = firmware
        self.model = model
        if feature is DeviceFeature.UNAVAILABLE:
            why = f"the app does not offer it on model {_model_name(model)}"
        else:
            why = f"the app offers it from firmware {_version(MIN_FIRMWARE_ADMIN)}, and this lock has {_version(firmware)}"
        super().__init__(f"{_name(command, 'Command')} is not available on this lock ({feature.name}): {why}")


class BleOperationError(BleError):
    """The lock answered a command with a status other than SUCCESS.

    status is the raw byte when it is not a known ResponseStatusId, so a
    firmware with a new status still produces a readable error.
    """

    status: ResponseStatusId | int

    def __init__(self, status: ResponseStatusId | int, command: CommandId | ResponseId | int | None = None) -> None:
        self.status = status
        self.command = command
        super().__init__(f"{_name(command, 'Command')} failed with status {_name(status, 'status')}")


class BleFailedError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.FAILED


class BleNotAvailableError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.NOT_AVAILABLE


class BleInternalError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.INTERNAL_ERROR


class BleParameterError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.PARAMETER_ERROR


class BleLengthError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.LENGTH_ERROR


class BleNotFoundError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.NOT_FOUND_ERROR


class BleNoMatchError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.NO_MATCH_ERROR


class BleNotSupportedError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.NOT_SUPPORTED_ERROR


class BleNotValidError(BleOperationError):
    status_id: ClassVar = ResponseStatusId.NOT_VALID_ERROR


class BleSecurityError(BleOperationError):
    """The lock rejected the credentials, such as a wrong owner key."""

    status_id: ClassVar = ResponseStatusId.SECURITY_ERROR


STATUS_ERRORS: Final[dict[ResponseStatusId, type[BleOperationError]]] = {
    cls.status_id: cls
    for cls in (
        BleFailedError,
        BleNotAvailableError,
        BleInternalError,
        BleParameterError,
        BleLengthError,
        BleNotFoundError,
        BleNoMatchError,
        BleNotSupportedError,
        BleNotValidError,
        BleSecurityError,
    )
}


def error_for_status(status: int, command: CommandId | ResponseId | int | None = None) -> BleOperationError:
    """The exception for a failed response's status byte.

    An unknown byte gets the BleOperationError base class. SUCCESS is not a
    failure, and asking for its error raises BleValidationError.
    """
    if status == ResponseStatusId.SUCCESS:
        raise BleValidationError("SUCCESS is not an error status")
    try:
        known = ResponseStatusId(status)
    except ValueError:
        return BleOperationError(status, command)
    return STATUS_ERRORS[known](known, command)


def _name(value: object, unknown: str) -> str:
    """An enum member by name with its hex value, anything else as hex."""
    if isinstance(value, CommandId | ResponseId | ResponseStatusId):
        return f"{value.name} (0x{value.value:02X})"
    if isinstance(value, int):
        return f"{unknown} 0x{value:02X}"
    return unknown


def _version(version: FirmwareVersion) -> str:
    return ".".join(str(part) for part in version)


def _model_name(model: LockModelId | None) -> str:
    return "not read" if model is None else f"{model.name} ({model.value})"
