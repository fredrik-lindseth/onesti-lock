"""ble/errors.py: the exception tree and the status byte mapping."""
from __future__ import annotations

import pytest

from ..conftest import load_component_module

const = load_component_module("ble.protocol.const")
errors = load_component_module("ble.errors")

FAILURES = [status for status in const.ResponseStatusId if status is not const.ResponseStatusId.SUCCESS]


class TestHierarchy:
    @pytest.mark.parametrize(
        "cls",
        [
            "BleValidationError",
            "BleSessionStateError",
            "BleProtocolError",
            "BleTimeoutError",
            "BleDisconnectedError",
            "BleFirmwareTooOldError",
            "BleOperationError",
        ],
    )
    def test_everything_is_a_ble_error(self, cls):
        assert issubclass(getattr(errors, cls), errors.BleError)

    def test_validation_is_a_value_error(self):
        # Callers that already catch ValueError for bad input keep working.
        assert issubclass(errors.BleValidationError, ValueError)

    def test_session_state_is_a_runtime_error(self):
        # Misuse of a Session is a bug in the caller, like any RuntimeError.
        assert issubclass(errors.BleSessionStateError, RuntimeError)
        assert not issubclass(errors.BleSessionStateError, errors.BleDisconnectedError)

    def test_timeout_is_a_timeout_error(self):
        # asyncio.timeout raises TimeoutError; one except clause catches both.
        assert issubclass(errors.BleTimeoutError, TimeoutError)

    def test_every_status_error_is_an_operation_error(self):
        for cls in errors.STATUS_ERRORS.values():
            assert issubclass(cls, errors.BleOperationError)


class TestStatusMapping:
    def test_every_failure_status_has_its_own_class(self):
        assert set(errors.STATUS_ERRORS) == set(FAILURES)
        assert len(set(errors.STATUS_ERRORS.values())) == len(FAILURES)

    @pytest.mark.parametrize("status", FAILURES, ids=lambda s: s.name)
    def test_error_for_status(self, status):
        error = errors.error_for_status(status.value, const.CommandId.PIN_CODE_SET)
        assert type(error) is errors.STATUS_ERRORS[status]
        assert error.status is status
        assert error.command is const.CommandId.PIN_CODE_SET

    def test_security_error_is_catchable_by_name(self):
        with pytest.raises(errors.BleSecurityError):
            raise errors.error_for_status(10, const.CommandId.USER_AUTH_FINALIZE)

    def test_unknown_status_keeps_the_raw_byte(self):
        error = errors.error_for_status(0x42)
        assert type(error) is errors.BleOperationError
        assert error.status == 0x42
        assert "0x42" in str(error)

    def test_success_is_not_an_error(self):
        with pytest.raises(errors.BleValidationError, match="SUCCESS"):
            errors.error_for_status(0)


class TestMessages:
    def test_names_command_and_status(self):
        error = errors.error_for_status(6, const.CommandId.PIN_CODE_CLEAR)
        assert str(error) == "PIN_CODE_CLEAR (0x53) failed with status NOT_FOUND_ERROR (0x06)"

    def test_response_id_and_raw_command(self):
        assert "LOCK_STATUS (0x60)" in str(errors.error_for_status(1, const.ResponseId.LOCK_STATUS))
        assert str(errors.error_for_status(1, 0x99)).startswith("Command 0x99 failed")

    def test_without_a_command(self):
        assert str(errors.error_for_status(4)) == "Command failed with status PARAMETER_ERROR (0x04)"

    def test_firmware_too_old(self):
        error = errors.BleFirmwareTooOldError((4, 6, 3), const.MIN_FIRMWARE_ADMIN)
        assert str(error) == "Lock firmware 4.6.3 is below the required 4.7.90"
        assert error.firmware == (4, 6, 3)
        assert error.required == (4, 7, 90)

    @pytest.mark.parametrize("status", FAILURES, ids=lambda s: s.name)
    def test_no_digit_run_a_pin_could_hide_in(self, status):
        # Messages are built from ids and statuses only. redact.py would mask
        # a run of four digits or more, so none may appear at all.
        redact = load_component_module("redact")
        message = str(errors.error_for_status(status, const.CommandId.PIN_CODE_SET))
        assert redact.redact_digits(message) == message
