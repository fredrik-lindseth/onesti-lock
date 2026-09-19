"""Owner authentication: proving to the lock that we hold the owner key.

It is a challenge and an answer (NimlyEkeyDevice class $27): UserAuthBegin
names the user and device id, the lock sends a 16-byte challenge, and
UserAuthFinalize returns it decrypted with the owner key and the link IV,
every bit flipped, and encrypted again. The lock answers a wrong key with a
failed status, which the session raises as its BleOperationError.

A factory-reset lock takes DEFAULT_OWNER_CREDENTIAL. Enrollment
(enrollment.py) replaces it with an owner key of our own, and every later
connection logs in with the credential the Enrollment gives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from ..crypto import AES_KEY_LENGTH, answer_owner_challenge
from ..errors import BleValidationError
from ..protocol.commands import user_auth_begin, user_auth_finalize
from ..protocol.const import DEVICE_ID_LENGTH
from ..protocol.responses import parse_user_auth_begin
from .const import DEFAULT_ADMIN_USER_ID, DEFAULT_DEVICE_ID, DEFAULT_ENCRYPTION_KEY
from .session import Session


@dataclass(frozen=True)
class OwnerCredential:
    """Who UserAuthBegin claims to be, and the key that answers the challenge (ParamUserAuth)."""

    user_id: int
    device_id: bytes
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        # UserAuthBegin writes the user id as one unsigned byte.
        if not 0 <= self.user_id <= 0xFF:
            raise BleValidationError(f"User id must be 0-255, got {self.user_id}")
        if len(self.device_id) != DEVICE_ID_LENGTH:
            raise BleValidationError(f"Device id must be {DEVICE_ID_LENGTH} bytes, got {len(self.device_id)}")
        if len(self.key) != AES_KEY_LENGTH:
            raise BleValidationError(f"Owner key must be {AES_KEY_LENGTH} bytes, got {len(self.key)}")


# What AddLockFragment authenticates a freshly scanned lock with:
# ParamUserAuth(0, Constants.DefaultDeviceId, Constants.DefaultEncryptionKey).
DEFAULT_OWNER_CREDENTIAL: Final = OwnerCredential(
    user_id=DEFAULT_ADMIN_USER_ID,
    device_id=DEFAULT_DEVICE_ID,
    key=DEFAULT_ENCRYPTION_KEY,
)


async def authenticate_owner(session: Session, credential: OwnerCredential) -> None:
    """Prove to the lock that we hold the owner key, on a connected session.

    Raises the session's BleOperationError (BleSecurityError, as far as
    anyone can tell without a lock) when the lock refuses the answer.
    UserAuthFinalize's answer carries a credentials byte, which the app never
    reads, so neither does this.
    """
    begin = await session.request(user_auth_begin(credential.user_id, credential.device_id), parse_user_auth_begin)
    answer = answer_owner_challenge(begin.challenge, credential.key, session.link_keys.iv)
    await session.send(user_auth_finalize(answer))
