"""Exceptions raised by the BLE protocol library.

Everything derives from BleError, so a caller can catch the library as a whole.
A response whose status byte is not SUCCESS becomes a BleOperationError
subclass, one per ResponseStatusId, through error_for_status. The app itself
has a single NimlyEkeyBleOperationException carrying the status
(exceptions/NimlyEkeyBleOperationException.java); separate classes let a caller
catch, say, BleSecurityError without inspecting a field.

No message may carry a PIN. The builders validate a PIN without quoting it, and
the messages here are built only from ids, statuses and lengths.
"""
from __future__ import annotations

from typing import ClassVar, Final

from .protocol.const import CommandId, FirmwareVersion, ResponseId, ResponseStatusId


class BleError(Exception):
    """Base class for every error the BLE library raises."""


class BleValidationError(BleError, ValueError):
    """A command argument the lock would refuse, caught before sending.

    Mirrors the app's client-side checks (VerifyExtensions): slot ranges, key
    and id lengths, PIN length and digits.
    """


class BleProtocolError(BleError):
    """Bytes from the lock that do not parse as the protocol says they should."""


class BleTimeoutError(BleError, TimeoutError):
    """The lock did not answer in time."""


class BleDisconnectedError(BleError):
    """The link dropped before the exchange finished."""


class BleFirmwareTooOldError(BleError):
    """The lock's firmware is below what an operation needs."""

    def __init__(self, firmware: FirmwareVersion, required: FirmwareVersion) -> None:
        self.firmware = firmware
        self.required = required
        super().__init__(f"Lock firmware {_version(firmware)} is below the required {_version(required)}")


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
    failure, and asking for its error is a bug in the caller.
    """
    if status == ResponseStatusId.SUCCESS:
        raise ValueError("SUCCESS is not an error status")
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
