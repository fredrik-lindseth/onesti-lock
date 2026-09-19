"""Enrolling a factory-reset lock without the cloud.

Enrollment takes over a factory-reset lock the way AddLockFragment.finishSetup
does, with our own values where the app fetches the cloud's. The steps, in the
app's order (read from the smali, where the Kotlin line table puts them on
source lines 197, 201, 202, 203 and 206):

1. Owner authentication (auth.py) with the factory credential: user 0,
   device id 00 x 6, key 11 x 16.
2. UserAuthUpdate (user 0, credentials 0) with a fresh public key. The lock
   answers with its own, and the new owner key is the first 16 bytes of the
   reversed ECDH secret. From here on the factory key presumably no longer
   opens the lock, so everything later is kept even when a step fails.
3. DeviceIdSet with a device id we pick. The cloud picks it in the app. The
   lock advertises a hash of it (protocol/advertisement.py), and the app
   sends it in UserAuthBegin on every later connection (ConnectLockFragment).
4. CurrentTimeSet, the lock's clock in minutes since 2023-01-01 UTC.
5. ServerKeyUpdate with the public half of a server key pair we generate and
   keep, where the app sends the cloud's key. The lock answers with a public
   key of its own, which the app uploads as the lock's devicePublicKey.
6. DeviceNameSet, at most 8 ASCII characters.

Why step 5 stays in: the app sends it on every enrollment, in the same
session, and nothing in the app says the lock treats setup as complete
without it; only the firmware knows. What the key is for is inferred, not
traced: the pair (our server private key, the lock's answer) gives the same
ECDH secret on both ends, which is what the cloud would need to sign or
encrypt what the app relays to the lock on every connection
(EkeyDeviceInfoGet to the cloud, EkeyDeviceInfoSet back). Holding the
private key ourselves means no one else's server key stays trusted by the
lock, and would let us act as that server. Nothing in the library uses it.

The guest ekey path (EkeyUserAuth 0x17 with a cloud token) is out of scope.
"""
from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from ..crypto import (
    AES_KEY_LENGTH,
    KeyPair,
    derive_owner_key,
    generate_key_pair,
    key_pair_from_private_key,
)
from ..errors import BleError, BleValidationError
from ..protocol.commands import (
    current_time_set,
    device_id_set,
    device_name_set,
    server_key_update,
    to_lock_time,
    user_auth_update,
)
from ..protocol.const import DEVICE_ID_LENGTH, PUBLIC_KEY_LENGTH
from ..protocol.responses import parse_server_key_update, parse_user_auth_update
from .auth import DEFAULT_OWNER_CREDENTIAL, OwnerCredential, authenticate_owner
from .const import DEFAULT_ADMIN_USER_ID, DEFAULT_DEVICE_ID
from .session import Session

# AddLockFragment.finishSetup sends ParamUserAuthUpdate(0, 0). What another
# credentials value would grant is not traced.
OWNER_CREDENTIALS: Final = 0

# Bumped when the stored shape of Enrollment.to_dict changes.
ENROLLMENT_FORMAT: Final = 1


class EnrollmentStep(StrEnum):
    """The steps after the factory-credential login, in the order they run."""

    OWNER_KEY = "owner_key"
    DEVICE_ID = "device_id"
    CLOCK = "clock"
    SERVER_KEY = "server_key"
    NAME = "name"


@dataclass(frozen=True)
class Enrollment:
    """Everything needed to talk to an enrolled lock again. Store all of it.

    owner_key and server_private_key are secrets and stay out of repr.
    completed says which steps the lock confirmed; an Enrollment always has
    the owner key, since before that step there is nothing worth keeping.
    lock_server_public_key is the lock's answer to ServerKeyUpdate, None
    until that step is done.
    """

    device_id: bytes
    owner_key: bytes = field(repr=False)
    server_private_key: bytes = field(repr=False)
    name: str
    lock_server_public_key: bytes | None = None
    completed: frozenset[EnrollmentStep] = frozenset({EnrollmentStep.OWNER_KEY})
    user_id: int = DEFAULT_ADMIN_USER_ID

    def __post_init__(self) -> None:
        _check_device_id(self.device_id)
        if len(self.owner_key) != AES_KEY_LENGTH:
            raise BleValidationError(f"Owner key must be {AES_KEY_LENGTH} bytes, got {len(self.owner_key)}")
        # Validates the scalar; the public half is derived when needed.
        key_pair_from_private_key(self.server_private_key)
        device_name_set(self.name)
        if EnrollmentStep.OWNER_KEY not in self.completed:
            raise BleValidationError("An enrollment always has its owner key step completed")
        has_server_key = EnrollmentStep.SERVER_KEY in self.completed
        if has_server_key != (self.lock_server_public_key is not None):
            raise BleValidationError("The lock's server public key is there exactly when the server key step is done")
        if self.lock_server_public_key is not None and len(self.lock_server_public_key) != PUBLIC_KEY_LENGTH:
            raise BleValidationError(
                f"Lock server public key must be {PUBLIC_KEY_LENGTH} bytes, got {len(self.lock_server_public_key)}"
            )
        # The credential validates the user id.
        OwnerCredential(self.user_id, self.device_id, self.owner_key)

    @property
    def complete(self) -> bool:
        return self.completed.issuperset(EnrollmentStep)

    @property
    def remaining(self) -> tuple[EnrollmentStep, ...]:
        return tuple(step for step in EnrollmentStep if step not in self.completed)

    @property
    def owner_credential(self) -> OwnerCredential:
        """What UserAuthBegin sends from now on.

        Until DeviceIdSet has gone through, the lock still has the factory
        device id, so that is what a resumed enrollment logs in with. That the
        lock checks the device id at all is read from the app, not tested.
        """
        device_id = self.device_id if EnrollmentStep.DEVICE_ID in self.completed else DEFAULT_DEVICE_ID
        return OwnerCredential(self.user_id, device_id, self.owner_key)

    @property
    def server_public_key(self) -> bytes:
        """The public half of server_private_key, as ServerKeyUpdate sends it."""
        return key_pair_from_private_key(self.server_private_key).public_key

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe form for storage, bytes as hex. Holds the secrets: store it as one."""
        return {
            "format": ENROLLMENT_FORMAT,
            "user_id": self.user_id,
            "device_id": self.device_id.hex(),
            "owner_key": self.owner_key.hex(),
            "server_private_key": self.server_private_key.hex(),
            "lock_server_public_key": None if self.lock_server_public_key is None else self.lock_server_public_key.hex(),
            "name": self.name,
            "completed": [step.value for step in EnrollmentStep if step in self.completed],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Enrollment:
        """Read what to_dict wrote. Errors name the field, never its value."""
        if data.get("format") != ENROLLMENT_FORMAT:
            raise BleValidationError(f"Unsupported enrollment format, expected {ENROLLMENT_FORMAT}")
        lock_key = data.get("lock_server_public_key")
        completed = data.get("completed")
        if not isinstance(completed, list):
            raise BleValidationError("Enrollment field completed is not a list")
        try:
            steps = frozenset(EnrollmentStep(step) for step in completed)
        except ValueError:
            raise BleValidationError("Enrollment field completed names an unknown step") from None
        name = data.get("name")
        user_id = data.get("user_id")
        if not isinstance(name, str):
            raise BleValidationError("Enrollment field name is not a string")
        if not isinstance(user_id, int):
            raise BleValidationError("Enrollment field user_id is not an integer")
        return cls(
            device_id=_hex_field(data, "device_id"),
            owner_key=_hex_field(data, "owner_key"),
            server_private_key=_hex_field(data, "server_private_key"),
            name=name,
            lock_server_public_key=None if lock_key is None else _hex_field(data, "lock_server_public_key"),
            completed=steps,
            user_id=user_id,
        )


class BleEnrollmentError(BleError):
    """Enrollment stopped partway.

    enrollment is what the lock has accepted so far. Store it: once the owner
    key step is done the factory key no longer works, and resume_enrollment
    finishes the job on a new session. enrollment is None when the owner key
    step itself failed. The lock then usually still has its factory key, but
    if it took the new key and only its answer was lost, nothing but a
    factory reset recovers it.
    """

    def __init__(self, step: EnrollmentStep, enrollment: Enrollment | None) -> None:
        self.step = step
        self.enrollment = enrollment
        if enrollment is None:
            detail = "no owner key was saved"
        else:
            detail = "the owner key is set; store the enrollment and resume it"
        super().__init__(f"Enrollment stopped at step {step.value}: {detail}")


def new_device_id() -> bytes:
    """A random device id. All zero is the factory id, so it is never returned."""
    while True:
        candidate = secrets.token_bytes(DEVICE_ID_LENGTH)
        if candidate != DEFAULT_DEVICE_ID:
            return candidate


async def enroll(
    session: Session,
    *,
    name: str,
    device_id: bytes | None = None,
    server_private_key: bytes | None = None,
    now: datetime | None = None,
    key_pair_factory: Callable[[], KeyPair] = generate_key_pair,
) -> Enrollment:
    """Take over a factory-reset lock on a connected session, and return what to store.

    name is what DeviceNameSet writes, at most 8 ASCII characters.
    device_id defaults to new_device_id(); server_private_key to a fresh
    key; now, for the lock's clock, to the current time. key_pair_factory
    makes the UserAuthUpdate key pair, and exists so tests can fix it.

    Raises BleEnrollmentError when a step after the factory login fails, with
    the partial Enrollment on it. A failed factory login raises the session's
    own error: the lock is not factory-reset, or not in the state this
    expects, and nothing has changed on it.
    """
    device_name_set(name)
    device_id = new_device_id() if device_id is None else device_id
    _check_device_id(device_id)
    server_private_key = key_pair_factory().private_key if server_private_key is None else server_private_key
    key_pair_from_private_key(server_private_key)

    await authenticate_owner(session, DEFAULT_OWNER_CREDENTIAL)

    update_key = key_pair_factory()
    try:
        answer = await session.request(
            user_auth_update(DEFAULT_ADMIN_USER_ID, OWNER_CREDENTIALS, update_key.public_key), parse_user_auth_update
        )
        owner_key = derive_owner_key(update_key.private_key, answer.public_key)
    except BleError as err:
        raise BleEnrollmentError(EnrollmentStep.OWNER_KEY, None) from err

    enrollment = Enrollment(
        device_id=device_id,
        owner_key=owner_key,
        server_private_key=server_private_key,
        name=name,
    )
    return await _run_remaining(session, enrollment, now)


async def resume_enrollment(session: Session, enrollment: Enrollment, *, now: datetime | None = None) -> Enrollment:
    """Finish an enrollment a BleEnrollmentError left partway, on a new connected session.

    Logs in with enrollment.owner_credential first. Returns the enrollment
    unchanged, without touching the lock, when it is already complete.
    """
    if enrollment.complete:
        return enrollment
    await authenticate_owner(session, enrollment.owner_credential)
    return await _run_remaining(session, enrollment, now)


async def _run_remaining(session: Session, enrollment: Enrollment, now: datetime | None) -> Enrollment:
    for step in enrollment.remaining:
        try:
            enrollment = await _run_step(session, enrollment, step, now)
        except BleError as err:
            raise BleEnrollmentError(step, enrollment) from err
    return enrollment


async def _run_step(session: Session, enrollment: Enrollment, step: EnrollmentStep, now: datetime | None) -> Enrollment:
    completed = enrollment.completed | {step}
    if step is EnrollmentStep.DEVICE_ID:
        await session.send(device_id_set(enrollment.device_id))
    elif step is EnrollmentStep.CLOCK:
        await session.send(current_time_set(to_lock_time(now or datetime.now(UTC))))
    elif step is EnrollmentStep.SERVER_KEY:
        answer = await session.request(server_key_update(enrollment.server_public_key), parse_server_key_update)
        return replace(enrollment, lock_server_public_key=answer.lock_public_key, completed=completed)
    else:
        # NAME: OWNER_KEY is never remaining, since every Enrollment has it.
        await session.send(device_name_set(enrollment.name))
    return replace(enrollment, completed=completed)


def _check_device_id(device_id: bytes) -> None:
    if len(device_id) != DEVICE_ID_LENGTH:
        raise BleValidationError(f"Device id must be {DEVICE_ID_LENGTH} bytes, got {len(device_id)}")
    if device_id == DEFAULT_DEVICE_ID:
        raise BleValidationError("Device id must not be all zero, the id of a factory-reset lock")


def _hex_field(data: dict[str, Any], key: str) -> bytes:
    value = data.get(key)
    if not isinstance(value, str):
        raise BleValidationError(f"Enrollment field {key} is not a hex string")
    try:
        return bytes.fromhex(value)
    except ValueError:
        raise BleValidationError(f"Enrollment field {key} is not a hex string") from None
