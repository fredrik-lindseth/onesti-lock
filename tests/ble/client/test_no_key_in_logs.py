"""No key material in a log record, checked by running the real thing.

tests/test_no_pin_exposure.py reads the source and refuses a log call that
takes an argument named like a secret. That catches the obvious line, but not
a key that travels inside something with an innocent name, and not a `repr`
on the way into a message. So this one runs a full enrollment and an owner
login against the fake lock with every logger at DEBUG, and holds every
record against the material the run produced: the factory key, the owner key
the two sides derived, the challenge, the answer, the private keys and
everything Enrollment.to_dict() keeps.

The last test is the guard's guard: it logs the owner key on purpose and
requires the check to fail.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from ...conftest import load_component_module
from ..fake_lock import (
    CHALLENGE,
    LOCK_LINK_PRIVATE_KEY,
    LOCK_SERVER_PRIVATE_KEY,
    LOCK_UPDATE_PRIVATE_KEY,
    PHONE_LINK_PRIVATE_KEY,
    PHONE_SERVER_PRIVATE_KEY,
    PHONE_UPDATE_PRIVATE_KEY,
    FakeLock,
    key_pairs,
)
from ..leaks import assert_no_material

auth = load_component_module("ble.client.auth")
client_const = load_component_module("ble.client.const")
enrollment_mod = load_component_module("ble.client.enrollment")
session_mod = load_component_module("ble.client.session")

# The logger the ble package hangs under, and the one a leak would use.
BLE_LOGGER = session_mod.__name__.rsplit(".", 2)[0]

DEVICE_ID = bytes.fromhex("5A 17 C3 09 E4 21")


def new_session(transport):
    return session_mod.Session(
        transport, command_delay=0, response_timeout=1.0, key_pair_factory=key_pairs(PHONE_LINK_PRIVATE_KEY)
    )


async def enroll_and_log_in(lock: FakeLock) -> tuple[object, bytes]:
    """The whole path a real takeover walks, in one connection each."""
    transport = lock.connect()
    async with new_session(transport) as session:
        enrollment = await enrollment_mod.enroll(
            session,
            name="Door",
            device_id=DEVICE_ID,
            server_private_key=PHONE_SERVER_PRIVATE_KEY,
            key_pair_factory=key_pairs(PHONE_UPDATE_PRIVATE_KEY),
            save=lambda _enrollment: None,
        )
    # The answer the login sends is derived material too, so it is read back
    # off the wire rather than recomputed.
    again = lock.connect()
    async with new_session(again) as session:
        credential = auth.OwnerCredential(
            user_id=enrollment.user_id, device_id=enrollment.device_id, key=enrollment.owner_key
        )
        await auth.authenticate_owner(session, credential)
    answer = again.commands[-1].payload
    return enrollment, answer


def material(enrollment, answer: bytes) -> list[bytes]:
    """Every secret the run handled, in the form a leak would carry."""
    secrets: list[bytes] = [
        client_const.DEFAULT_ENCRYPTION_KEY,
        enrollment.owner_key,
        CHALLENGE,
        answer,
        LOCK_LINK_PRIVATE_KEY,
        LOCK_UPDATE_PRIVATE_KEY,
        LOCK_SERVER_PRIVATE_KEY,
        PHONE_LINK_PRIVATE_KEY,
        PHONE_UPDATE_PRIVATE_KEY,
        PHONE_SERVER_PRIVATE_KEY,
    ]
    # Enrollment.to_dict() is the stored shape, and all of it is secret.
    for value in enrollment.to_dict().values():
        if isinstance(value, str):
            try:
                secrets.append(bytes.fromhex(value))
            except ValueError:
                continue
    return [secret for secret in secrets if len(secret) >= 8]


def text_of(records: list[logging.LogRecord]) -> str:
    """Formatted message and raw arguments, since a leak can sit in either."""
    return "\n".join(f"{record.getMessage()} {record.args!r} {record.msg!r}" for record in records)


@pytest.fixture
def run_records(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    lock = FakeLock()
    enrollment, answer = asyncio.run(enroll_and_log_in(lock))
    return enrollment, answer, caplog.records


def test_a_full_takeover_logs_no_key_material(run_records) -> None:
    enrollment, answer, records = run_records
    assert enrollment.complete, "a run that stopped early proves less than a whole one"
    assert_no_material(text_of(records), *material(enrollment, answer))


async def enroll_losing_the_device_id_answer(lock: FakeLock):
    """DeviceIdSet reaches the lock; its answer never does, so the run stops."""
    transport = lock.connect()
    transport.lost_answers.add(session_mod.CommandId.DEVICE_ID_SET)
    session = session_mod.Session(
        transport, command_delay=0, response_timeout=0.05, key_pair_factory=key_pairs(PHONE_LINK_PRIVATE_KEY)
    )
    async with session:
        try:
            await enrollment_mod.enroll(
                session,
                name="Door",
                device_id=DEVICE_ID,
                server_private_key=PHONE_SERVER_PRIVATE_KEY,
                key_pair_factory=key_pairs(PHONE_UPDATE_PRIVATE_KEY),
                save=lambda _enrollment: None,
            )
        except enrollment_mod.BleEnrollmentError as err:
            return err.enrollment
    raise AssertionError("the lost answer should have stopped the enrollment")


async def resume(lock: FakeLock, partial):
    transport = lock.connect()
    async with new_session(transport) as session:
        return await enrollment_mod.resume_enrollment(session, partial, save=lambda _enrollment: None)


def test_the_paths_that_do_log_carry_no_key_material(caplog: pytest.LogCaptureFixture) -> None:
    """The library is quiet when all goes well; the interrupted run is where it talks.

    A lost DeviceIdSet answer, then a resume: the login falls back to the
    enrolled device id, and both attempts hold the owner key.
    """
    caplog.set_level(logging.DEBUG)
    lock = FakeLock()
    partial = asyncio.run(enroll_losing_the_device_id_answer(lock))
    finished = asyncio.run(resume(lock, partial))

    ours = [record for record in caplog.records if record.name.startswith(BLE_LOGGER)]
    assert len(ours) >= 2, "the resume path stopped logging; this test then proves nothing"
    assert finished.complete
    assert_no_material(text_of(caplog.records), *material(finished, b""))


def test_the_check_sees_the_owner_key_when_it_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Without this, a run that logs nothing at all would pass as clean."""
    owner_key = bytes(range(0x30, 0x40))
    caplog.set_level(logging.DEBUG)
    logging.getLogger(BLE_LOGGER).debug("owner key %s", owner_key.hex())
    logging.getLogger(BLE_LOGGER).debug("and raw %r", owner_key)

    with pytest.raises(AssertionError):
        assert_no_material(text_of(caplog.records), owner_key)
