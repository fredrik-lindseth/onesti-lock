"""protocol/advertisement.py: the 0xFD00 service data.

The advertisement vectors are derived from BleScanner.getNimlyEkeyScanResult:
no advertisement has been captured from a lock.
"""
from __future__ import annotations

import hashlib

import pytest

from ...conftest import load_component_module

advertisement = load_component_module("ble.protocol.advertisement")
errors = load_component_module("ble.errors")

DEVICE_ID = bytes.fromhex("5A 17 C3 09 E4 21")

# derived: a lock nobody has enrolled, seed 00 00, then its own id reversed.
UNENROLLED = bytes.fromhex("00 00 66 55 44 33 22 11")
# derived: an enrolled lock with seed 12 34. The identifier is SHA-1 over the
# seed followed by DEVICE_ID, first 6 bytes: SHA-1(12 34 5A 17 C3 09 E4 21).
SEED = bytes.fromhex("12 34")
ENROLLED = SEED + hashlib.sha1(SEED + DEVICE_ID).digest()[:6]


class TestAdvertisement:
    def test_unenrolled_lock(self):
        ad = advertisement.parse_advertisement(UNENROLLED)
        assert not ad.enrolled
        assert ad.factory_id == bytes.fromhex("11 22 33 44 55 66")
        assert not ad.matches(DEVICE_ID)

    def test_enrolled_lock_matches_its_device_id_only(self):
        ad = advertisement.parse_advertisement(ENROLLED + b"\xff\xff")
        assert ad.enrolled
        assert ad.factory_id is None
        assert ad.matches(DEVICE_ID)
        assert not ad.matches(bytes.fromhex("5A 17 C3 09 E4 22"))

    def test_the_hash_depends_on_the_seed(self):
        other_seed = bytes.fromhex("12 35") + ENROLLED[2:]
        assert not advertisement.parse_advertisement(other_seed).matches(DEVICE_ID)

    def test_too_short(self):
        with pytest.raises(errors.BleProtocolError, match="7 byte"):
            advertisement.parse_advertisement(ENROLLED[:7])

    def test_device_id_length(self):
        with pytest.raises(errors.BleValidationError, match="6 bytes"):
            advertisement.parse_advertisement(ENROLLED).matches(b"\x01")

