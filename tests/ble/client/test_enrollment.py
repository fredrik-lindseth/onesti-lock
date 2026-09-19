"""Cloud-free enrollment of a factory-reset lock, end to end against the fake lock.

The expected command sequence is AddLockFragment.finishSetup's, confirmed in
the smali (source lines 197, 201, 202, 203, 206), preceded by the connect
sequence and the factory login. Every key is fixed, so every payload is
known in advance.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from ...conftest import load_component_module
from ..fake_lock import (
    LOCK_SERVER_PRIVATE_KEY,
    LOCK_UPDATE_PRIVATE_KEY,
    PHONE_LINK_PRIVATE_KEY,
    PHONE_SERVER_PRIVATE_KEY,
    PHONE_UPDATE_PRIVATE_KEY,
    FakeLock,
    ecdh_reversed,
    key_pairs,
    public_key,
)

const = load_component_module("ble.protocol.const")
client_const = load_component_module("ble.client.const")
enrollment_mod = load_component_module("ble.client.enrollment")
auth = load_component_module("ble.client.auth")
commands = load_component_module("ble.protocol.commands")
crypto = load_component_module("ble.crypto")
errors = load_component_module("ble.errors")
session_mod = load_component_module("ble.client.session")

CommandId = const.CommandId
Step = enrollment_mod.EnrollmentStep

DEVICE_ID = bytes.fromhex("5A 17 C3 09 E4 21")
# 2026-09-19 12:00 UTC is 1357 days and 12 hours after 2023-01-01 00:00 UTC.
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
NOW_LOCK_MINUTES = 1357 * 24 * 60 + 12 * 60


def run(coro):
    return asyncio.run(coro)


def new_session(transport, *private_keys):
    keys = private_keys or (PHONE_LINK_PRIVATE_KEY,)
    return session_mod.Session(transport, command_delay=0, response_timeout=1.0, key_pair_factory=key_pairs(*keys))


async def enroll_fixed(lock, **kwargs):
    kwargs.setdefault("name", "Door")
    kwargs.setdefault("device_id", DEVICE_ID)
    kwargs.setdefault("server_private_key", PHONE_SERVER_PRIVATE_KEY)
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("key_pair_factory", key_pairs(PHONE_UPDATE_PRIVATE_KEY))
    transport = lock.connect()
    async with new_session(transport) as session:
        return await enrollment_mod.enroll(session, **kwargs), transport


async def resume(lock, enrollment):
    transport = lock.connect()
    async with new_session(transport) as session:
        return await enrollment_mod.resume_enrollment(session, enrollment, now=NOW), transport


async def log_in(lock, credential):
    transport = lock.connect()
    async with new_session(transport) as session:
        await auth.authenticate_owner(session, credential)
    return transport


EXPECTED_OWNER_KEY = ecdh_reversed(PHONE_UPDATE_PRIVATE_KEY, public_key(LOCK_UPDATE_PRIVATE_KEY))[:16]


class TestFullEnrollment:
    def test_reproduces_the_app_sequence(self):
        lock = FakeLock()
        enrollment, transport = run(enroll_fixed(lock))

        sent = [(c.command_id, c.command_ref, c.payload) for c in transport.commands]
        answer = sent[3][2]
        assert sent == [
            (CommandId.EXCHANGE_KEY_PUB_M, 1, public_key(PHONE_LINK_PRIVATE_KEY)),
            (CommandId.DEVICE_MODEL_GET, 2, b""),
            (CommandId.USER_AUTH_BEGIN, 3, bytes(7)),
            (CommandId.USER_AUTH_FINALIZE, 4, answer),
            (CommandId.USER_AUTH_UPDATE, 5, b"\x00\x00" + public_key(PHONE_UPDATE_PRIVATE_KEY)),
            (CommandId.DEVICE_ID_SET, 6, DEVICE_ID),
            (CommandId.CURRENT_TIME_SET, 7, NOW_LOCK_MINUTES.to_bytes(4, "little")),
            (CommandId.SERVER_KEY_UPDATE, 8, public_key(PHONE_SERVER_PRIVATE_KEY)),
            (CommandId.DEVICE_NAME_SET, 9, b"Door" + bytes(5)),
        ]
        assert len(answer) == 16

        # What the lock now holds.
        assert lock.owner_key == EXPECTED_OWNER_KEY
        assert lock.device_id == DEVICE_ID
        assert lock.clock == NOW_LOCK_MINUTES
        assert lock.server_public_key == public_key(PHONE_SERVER_PRIVATE_KEY)
        assert lock.name == "Door"

        # What we keep.
        assert enrollment.complete
        assert enrollment.remaining == ()
        assert enrollment.device_id == DEVICE_ID
        assert enrollment.owner_key == EXPECTED_OWNER_KEY
        assert enrollment.server_private_key == PHONE_SERVER_PRIVATE_KEY
        assert enrollment.server_public_key == public_key(PHONE_SERVER_PRIVATE_KEY)
        assert enrollment.lock_server_public_key == public_key(LOCK_SERVER_PRIVATE_KEY)
        assert enrollment.name == "Door"
        assert enrollment.user_id == 0

    def test_both_ends_share_the_server_secret(self):
        """The stored server key and the lock's answer give the lock's own ECDH secret."""
        lock = FakeLock()
        enrollment, _ = run(enroll_fixed(lock))
        ours = crypto.compute_shared_secret(enrollment.server_private_key, enrollment.lock_server_public_key)
        assert ours == ecdh_reversed(LOCK_SERVER_PRIVATE_KEY, lock.server_public_key)

    def test_a_new_session_logs_in_with_the_stored_enrollment(self):
        lock = FakeLock()
        enrollment, _ = run(enroll_fixed(lock))
        stored = enrollment_mod.Enrollment.from_dict(enrollment.to_dict())
        assert stored == enrollment

        transport = run(log_in(lock, stored.owner_credential))
        assert transport.authenticated
        assert transport.commands[2].payload == b"\x00" + DEVICE_ID

    def test_the_factory_credential_no_longer_works(self):
        lock = FakeLock()
        run(enroll_fixed(lock))
        with pytest.raises(errors.BleSecurityError):
            run(log_in(lock, auth.DEFAULT_OWNER_CREDENTIAL))

    def test_an_enrolled_lock_refuses_a_second_enrollment_untouched(self):
        lock = FakeLock()
        run(enroll_fixed(lock))
        with pytest.raises(errors.BleSecurityError) as caught:
            run(enroll_fixed(lock, device_id=bytes.fromhex("010101010101")))
        assert not isinstance(caught.value, enrollment_mod.BleEnrollmentError)
        assert lock.device_id == DEVICE_ID

    def test_random_defaults(self):
        """device_id, server key, clock and every key pair left to the library."""
        lock = FakeLock()

        async def scenario():
            transport = lock.connect()
            async with session_mod.Session(transport, command_delay=0) as session:
                return await enrollment_mod.enroll(session, name="Hall")

        enrollment = run(scenario())
        assert enrollment.complete
        assert len(enrollment.device_id) == 6
        assert enrollment.device_id != client_const.DEFAULT_DEVICE_ID
        assert lock.device_id == enrollment.device_id
        assert lock.owner_key == enrollment.owner_key
        assert lock.server_public_key == enrollment.server_public_key
        assert abs(lock.clock - commands.to_lock_time(datetime.now(UTC))) <= 1

    def test_server_key_comes_from_the_factory_first(self):
        lock = FakeLock()
        enrollment, _ = run(
            enroll_fixed(
                lock,
                server_private_key=None,
                key_pair_factory=key_pairs(PHONE_SERVER_PRIVATE_KEY, PHONE_UPDATE_PRIVATE_KEY),
            )
        )
        assert enrollment.server_private_key == PHONE_SERVER_PRIVATE_KEY
        assert enrollment.owner_key == EXPECTED_OWNER_KEY


class TestEnrollmentStopsPartway:
    STEP_COMMANDS = {
        Step.DEVICE_ID: CommandId.DEVICE_ID_SET,
        Step.CLOCK: CommandId.CURRENT_TIME_SET,
        Step.SERVER_KEY: CommandId.SERVER_KEY_UPDATE,
        Step.NAME: CommandId.DEVICE_NAME_SET,
    }

    @pytest.mark.parametrize("failed_step", list(STEP_COMMANDS))
    def test_keeps_what_the_lock_accepted_and_resumes(self, failed_step):
        lock = FakeLock()
        failing = self.STEP_COMMANDS[failed_step]

        async def first_attempt():
            transport = lock.connect()
            transport.status_overrides[failing] = const.ResponseStatusId.FAILED
            async with new_session(transport) as session:
                return await enrollment_mod.enroll(
                    session,
                    name="Door",
                    device_id=DEVICE_ID,
                    server_private_key=PHONE_SERVER_PRIVATE_KEY,
                    now=NOW,
                    key_pair_factory=key_pairs(PHONE_UPDATE_PRIVATE_KEY),
                )

        with pytest.raises(enrollment_mod.BleEnrollmentError) as caught:
            run(first_attempt())
        partial = caught.value.enrollment
        assert caught.value.step is failed_step
        assert isinstance(caught.value.__cause__, errors.BleFailedError)
        assert "resume" in str(caught.value)
        assert partial.owner_key == lock.owner_key == EXPECTED_OWNER_KEY
        steps = list(Step)
        assert partial.completed == frozenset(steps[: steps.index(failed_step)])
        assert partial.remaining[0] is failed_step

        # The stored partial enrollment finishes on a new connection.
        stored = enrollment_mod.Enrollment.from_dict(partial.to_dict())
        finished, transport = run(resume(lock, stored))
        assert finished.complete
        expected_login_id = DEVICE_ID if Step.DEVICE_ID in partial.completed else client_const.DEFAULT_DEVICE_ID
        assert transport.commands[2].payload == b"\x00" + expected_login_id
        assert [c.command_id for c in transport.commands[4:]] == [self.STEP_COMMANDS[s] for s in partial.remaining]
        assert lock.device_id == DEVICE_ID
        assert lock.name == "Door"
        assert lock.server_public_key == public_key(PHONE_SERVER_PRIVATE_KEY)
        assert finished.lock_server_public_key == public_key(LOCK_SERVER_PRIVATE_KEY)

    def test_owner_key_step_failing_leaves_nothing_to_keep(self):
        lock = FakeLock()

        async def scenario():
            transport = lock.connect()
            transport.status_overrides[CommandId.USER_AUTH_UPDATE] = const.ResponseStatusId.FAILED
            async with new_session(transport) as session:
                await enrollment_mod.enroll(session, name="Door", key_pair_factory=key_pairs(PHONE_SERVER_PRIVATE_KEY, PHONE_UPDATE_PRIVATE_KEY))

        with pytest.raises(enrollment_mod.BleEnrollmentError) as caught:
            run(scenario())
        assert caught.value.step is Step.OWNER_KEY
        assert caught.value.enrollment is None
        assert "no owner key was saved" in str(caught.value)
        assert lock.owner_key == client_const.DEFAULT_ENCRYPTION_KEY

    def test_owner_key_answer_off_the_curve(self):
        async def scenario():
            transport = FakeLock().connect()
            transport.payload_overrides[CommandId.USER_AUTH_UPDATE] = bytes(64)
            async with new_session(transport) as session:
                await enrollment_mod.enroll(session, name="Door", key_pair_factory=key_pairs(PHONE_SERVER_PRIVATE_KEY, PHONE_UPDATE_PRIVATE_KEY))

        with pytest.raises(enrollment_mod.BleEnrollmentError) as caught:
            run(scenario())
        assert caught.value.enrollment is None
        assert isinstance(caught.value.__cause__, errors.BleProtocolError)

    def test_resuming_a_complete_enrollment_sends_nothing(self):
        lock = FakeLock()
        enrollment, _ = run(enroll_fixed(lock))
        again, transport = run(resume(lock, enrollment))
        assert again is enrollment
        assert [c.command_id for c in transport.commands] == [CommandId.EXCHANGE_KEY_PUB_M, CommandId.DEVICE_MODEL_GET]


class TestInputChecks:
    def _refused_before_login(self, **kwargs):
        lock = FakeLock()
        with pytest.raises(errors.BleValidationError) as caught:
            run(enroll_fixed(lock, **kwargs))
        assert CommandId.USER_AUTH_BEGIN not in [c.command_id for c in lock.commands]
        return caught.value

    def test_name_too_long(self):
        self._refused_before_login(name="Front door")

    def test_name_not_ascii(self):
        self._refused_before_login(name="Dør")

    def test_device_id_all_zero(self):
        assert "all zero" in str(self._refused_before_login(device_id=bytes(6)))

    def test_device_id_wrong_length(self):
        self._refused_before_login(device_id=b"\x01\x02")

    def test_server_key_not_a_scalar(self):
        self._refused_before_login(server_private_key=b"\xff" * 32)

    def test_new_device_id_never_returns_the_factory_id(self, monkeypatch):
        draws = iter([bytes(6), bytes(6), b"\x00\x00\x00\x00\x00\x01"])
        monkeypatch.setattr(enrollment_mod.secrets, "token_bytes", lambda n: next(draws))
        assert enrollment_mod.new_device_id() == b"\x00\x00\x00\x00\x00\x01"


# --- The stored value ---------------------------------------------------------------


def enrollment(**overrides):
    values = {
        "device_id": DEVICE_ID,
        "owner_key": EXPECTED_OWNER_KEY,
        "server_private_key": PHONE_SERVER_PRIVATE_KEY,
        "name": "Door",
        "lock_server_public_key": public_key(LOCK_SERVER_PRIVATE_KEY),
        "completed": frozenset(Step),
    }
    values.update(overrides)
    return enrollment_mod.Enrollment(**values)


class TestEnrollmentValue:
    def test_repr_and_errors_hold_no_secret(self):
        value = enrollment()
        text = repr(value)
        for secret in (value.owner_key, value.server_private_key):
            assert secret.hex() not in text
            assert secret.hex().upper() not in text
        assert "owner_key=" not in text
        assert "server_private_key=" not in text
        assert DEVICE_ID.hex() in text or repr(DEVICE_ID) in text

    def test_owner_credential_follows_the_device_id_step(self):
        full = enrollment()
        assert full.owner_credential == auth.OwnerCredential(0, DEVICE_ID, EXPECTED_OWNER_KEY)
        early = enrollment(completed=frozenset({Step.OWNER_KEY}), lock_server_public_key=None)
        assert early.owner_credential.device_id == client_const.DEFAULT_DEVICE_ID
        assert early.remaining == (Step.DEVICE_ID, Step.CLOCK, Step.SERVER_KEY, Step.NAME)
        assert not early.complete

    def test_round_trip(self):
        for value in (enrollment(), enrollment(completed=frozenset({Step.OWNER_KEY}), lock_server_public_key=None)):
            data = value.to_dict()
            assert data["format"] == enrollment_mod.ENROLLMENT_FORMAT
            assert enrollment_mod.Enrollment.from_dict(data) == value

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"owner_key": b"\x01" * 15}, "Owner key must be 16 bytes"),
            ({"completed": frozenset({Step.DEVICE_ID})}, "owner key step"),
            ({"lock_server_public_key": None}, "server key step"),
            ({"completed": frozenset({Step.OWNER_KEY})}, "server key step"),
            ({"lock_server_public_key": b"\x01" * 63}, "must be 64 bytes"),
            ({"user_id": 300}, "User id must be 0-255"),
            ({"device_id": bytes(6)}, "all zero"),
            ({"name": "Much too long"}, "does not fit"),
        ],
    )
    def test_invalid_values(self, overrides, message):
        with pytest.raises(errors.BleValidationError, match=message) as caught:
            enrollment(**overrides)
        assert EXPECTED_OWNER_KEY.hex() not in str(caught.value)

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"format": 2}, "Unsupported enrollment format"),
            ({"completed": "all"}, "completed is not a list"),
            ({"completed": ["owner_key", "dance"]}, "unknown step"),
            ({"name": 7}, "name is not a string"),
            ({"user_id": "0"}, "user_id is not an integer"),
            ({"owner_key": 12}, "owner_key is not a hex string"),
            ({"owner_key": "zz" * 16}, "owner_key is not a hex string"),
            ({"lock_server_public_key": "nope"}, "lock_server_public_key is not a hex string"),
        ],
    )
    def test_from_dict_names_the_field_not_the_value(self, change, message):
        data = enrollment().to_dict() | change
        with pytest.raises(errors.BleValidationError, match=message) as caught:
            enrollment_mod.Enrollment.from_dict(data)
        assert data["server_private_key"] not in str(caught.value)
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__ or caught.value.__context__ is None
