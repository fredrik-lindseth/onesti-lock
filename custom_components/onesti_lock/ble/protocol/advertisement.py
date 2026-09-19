"""What a lock says in its advertisement, and how to recognise an enrolled one.

The lock advertises service data under the 16-bit UUID 0xFD00
(ADVERTISING_UUID in client/const.py). BleScanner.getNimlyEkeyScanResult
reads it as:

    [seed:2][identifier:6]

A seed of 00 00 marks a lock nobody has enrolled; the identifier is then an
id of the lock's own, byte-reversed on the air. Any other seed means the lock
is enrolled, and the identifier is the first 6 bytes of SHA-1(seed ||
device id), with the device id enrollment set through DeviceIdSet. An
enrolled lock never shows its device id, so only someone who stored it can
tell which lock it is, which is why Enrollment keeps it.

Read from the app only; no advertisement has been captured yet.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..errors import BleProtocolError, BleValidationError
from .const import DEFAULT_DEVICE_ID_SEED, DEVICE_ID_LENGTH, DEVICE_ID_SEED_LENGTH
from .streams import ByteReader


@dataclass(frozen=True, slots=True)
class Advertisement:
    """The two fields of the lock's 0xFD00 service data."""

    seed: bytes
    identifier: bytes

    @property
    def enrolled(self) -> bool:
        return self.seed != DEFAULT_DEVICE_ID_SEED

    @property
    def factory_id(self) -> bytes | None:
        """The id a lock nobody has enrolled shows, as the app reads it; None once enrolled.

        The app keeps it as the scan result's device id, yet logs in to such
        a lock with the all-zero default id, so it is informational here.
        """
        return None if self.enrolled else self.identifier[::-1]

    def matches(self, device_id: bytes) -> bool:
        """Whether this is the enrolled lock with that device id."""
        if len(device_id) != DEVICE_ID_LENGTH:
            raise BleValidationError(f"Device id must be {DEVICE_ID_LENGTH} bytes, got {len(device_id)}")
        if not self.enrolled:
            return False
        digest = hashlib.sha1(self.seed + device_id, usedforsecurity=False).digest()
        return digest[:DEVICE_ID_LENGTH] == self.identifier


def parse_advertisement(service_data: bytes) -> Advertisement:
    """Read the 0xFD00 service data. Bytes after the first 8 are ignored, as the app ignores them."""
    needed = DEVICE_ID_SEED_LENGTH + DEVICE_ID_LENGTH
    if len(service_data) < needed:
        raise BleProtocolError(f"Advertisement service data is {len(service_data)} byte(s), needs {needed}")
    reader = ByteReader(service_data)
    return Advertisement(reader.read_bytes(DEVICE_ID_SEED_LENGTH), reader.read_bytes(DEVICE_ID_LENGTH))
