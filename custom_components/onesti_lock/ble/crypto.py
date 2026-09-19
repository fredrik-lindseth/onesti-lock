"""Key exchange and encryption for the BLE link, done the way the Nimly app does it.

Transcribed from the decompiled app (package com.nimly.ekey.ble):
crypto/exchangers/Secp256r1SecretExchanger.java for the key exchange,
crypto/encrypters/Aes128CbcEncrypter.java for AES, extensions/ByteExtensions.java
and extensions/BigIntegerExtensions.java for the byte order, and the call sites
in devices/NimlyEkeyDeviceBase.java and admin/devices/NimlyEkeyDevice.java for
how the pieces are combined. None of it has run against a lock yet.

Four details differ from the textbook and are easy to get wrong:

- Keys on the wire are little endian. A public key is X then Y, each 32 bytes
  least significant first, and a private key is the scalar the same way
  (BigIntegerExtensions.toLittleEndianHex).
- The ECDH secret is reversed before anyone reads it. The link key is the first
  16 bytes of the reversed secret and the link IV the last 16, and the owner key
  from UserAuthUpdate is those same first 16 bytes of its own exchange.
- Every message is encrypted on its own, from the same IV. Java's
  Cipher.doFinal puts the cipher back to its state at init, IV included, so
  the app's "IV increment" mode is plain CBC within one message and nothing
  carries over to the next. Its "IV reset" mode encrypts every 16-byte block
  alone with the original IV.
- The cipher runs without padding, but encrypt() first fills the message with
  zero bytes up to a whole block, so the length has to come from the frame
  inside, never from the ciphertext.

Nothing secret appears in an exception message or a repr: errors name lengths
and what was wrong, and the classes that hold keys leave them out of repr.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .errors import BleProtocolError, BleValidationError
from .protocol.const import CHALLENGE_LENGTH, PUBLIC_KEY_LENGTH

# Sizes the cipher and the curve fix (settings/Constants.java). The lengths
# that travel in frames, the public key and the challenge, are wire constants.
AES_BLOCK_SIZE: Final = 16
AES_KEY_LENGTH: Final = 16
PRIVATE_KEY_LENGTH: Final = 32
SHARED_SECRET_LENGTH: Final = 32

_CURVE: Final = ec.SECP256R1()
_COORDINATE_LENGTH: Final = PUBLIC_KEY_LENGTH // 2


# --- Byte helpers (extensions/ByteExtensions.java) ---------------------------


def bit_invert(data: bytes) -> bytes:
    """Every bit flipped (ByteExtensions.bitInverseArray)."""
    return bytes(byte ^ 0xFF for byte in data)


def zero_pad(data: bytes) -> bytes:
    """data followed by zero bytes up to a whole AES block.

    A length that is already a whole number of blocks, zero included, gets no
    padding, as in Aes128CbcEncrypter.encrypt.
    """
    return bytes(data) + bytes(-len(data) % AES_BLOCK_SIZE)


# --- Key exchange (crypto/exchangers/Secp256r1SecretExchanger.java) ----------


@dataclass(frozen=True)
class KeyPair:
    """A secp256r1 key pair in the app's wire encoding.

    private_key is the 32-byte scalar, little endian. public_key is the 64 bytes
    ExchangeKeyPubM and UserAuthUpdate carry: X then Y, each little endian.
    """

    private_key: bytes = field(repr=False)
    public_key: bytes = field(repr=False)


def generate_key_pair() -> KeyPair:
    """A fresh key pair, as the app makes one for every exchange."""
    return _key_pair(ec.generate_private_key(_CURVE))


def key_pair_from_private_key(private_key: bytes) -> KeyPair:
    """The key pair for a known private key, in wire encoding.

    For tests and for replaying a recorded exchange; a live exchange uses
    generate_key_pair.
    """
    return _key_pair(_load_private_key(private_key))


def compute_shared_secret(private_key: bytes, peer_public_key: bytes) -> bytes:
    """The 32-byte ECDH secret, reversed, as Secp256r1SecretExchanger.computeSecret returns it.

    private_key is ours in wire encoding; peer_public_key is the 64 bytes the
    other side sent (the lock's ExchangeKeyPubL or UserAuthUpdate answer, or a
    server key).
    """
    shared = _load_private_key(private_key).exchange(ec.ECDH(), _load_public_key(peer_public_key))
    return shared[::-1]


def encode_public_key(public_key: ec.EllipticCurvePublicKey) -> bytes:
    """A public key as the 64 wire bytes: X then Y, each little endian."""
    numbers = public_key.public_numbers()
    return numbers.x.to_bytes(_COORDINATE_LENGTH, "little") + numbers.y.to_bytes(_COORDINATE_LENGTH, "little")


def _key_pair(private: ec.EllipticCurvePrivateKey) -> KeyPair:
    scalar = private.private_numbers().private_value
    return KeyPair(
        private_key=scalar.to_bytes(PRIVATE_KEY_LENGTH, "little"),
        public_key=encode_public_key(private.public_key()),
    )


def _load_private_key(private_key: bytes) -> ec.EllipticCurvePrivateKey:
    if len(private_key) != PRIVATE_KEY_LENGTH:
        raise BleValidationError(f"Private key must be {PRIVATE_KEY_LENGTH} bytes, got {len(private_key)}")
    try:
        return ec.derive_private_key(int.from_bytes(private_key, "little"), _CURVE)
    except ValueError:
        # from None: the chained error would sit next to the key in a traceback.
        raise BleValidationError("Private key is not a valid secp256r1 scalar") from None


def _load_public_key(public_key: bytes) -> ec.EllipticCurvePublicKey:
    if len(public_key) != PUBLIC_KEY_LENGTH:
        raise BleProtocolError(f"Public key must be {PUBLIC_KEY_LENGTH} bytes, got {len(public_key)}")
    x = int.from_bytes(public_key[:_COORDINATE_LENGTH], "little")
    y = int.from_bytes(public_key[_COORDINATE_LENGTH:], "little")
    try:
        return ec.EllipticCurvePublicNumbers(x, y, _CURVE).public_key()
    except ValueError:
        raise BleProtocolError("Public key is not a point on secp256r1") from None


# --- Link and owner keys (devices/NimlyEkeyDeviceBase.java, admin/devices/NimlyEkeyDevice.java)


@dataclass(frozen=True)
class LinkKeys:
    """The AES key and IV one connection runs on after the key exchange."""

    key: bytes = field(repr=False)
    iv: bytes = field(repr=False)

    @classmethod
    def from_shared_secret(cls, shared_secret: bytes) -> LinkKeys:
        """Split a reversed secret: [0:16] is the key, [16:32] the IV (getLinkKey, getLinkIv)."""
        if len(shared_secret) != SHARED_SECRET_LENGTH:
            raise BleValidationError(f"Shared secret must be {SHARED_SECRET_LENGTH} bytes, got {len(shared_secret)}")
        return cls(key=shared_secret[:AES_KEY_LENGTH], iv=shared_secret[AES_KEY_LENGTH:])

    def cipher(self) -> Aes128Cbc:
        """The command stream's cipher. NimlyEkeyDeviceBase sets it with ivReset false."""
        return Aes128Cbc(self.key, self.iv, iv_reset=False)


def derive_link_keys(private_key: bytes, lock_public_key: bytes) -> LinkKeys:
    """Link key and IV from our ExchangeKeyPubM private key and the lock's ExchangeKeyPubL key."""
    return LinkKeys.from_shared_secret(compute_shared_secret(private_key, lock_public_key))


def derive_owner_key(private_key: bytes, lock_public_key: bytes) -> bytes:
    """The new owner key after UserAuthUpdate: the first 16 bytes of the reversed secret.

    private_key is the one whose public half went out in UserAuthUpdate, and
    lock_public_key the key in the lock's answer (NimlyEkeyDevice class $28).
    """
    return compute_shared_secret(private_key, lock_public_key)[:AES_KEY_LENGTH]


def answer_owner_challenge(challenge: bytes, owner_key: bytes, link_iv: bytes) -> bytes:
    """The UserAuthFinalize payload for a UserAuthBegin challenge.

    Decrypt the challenge with the owner key and the connection's link IV,
    flip every bit, encrypt it back (NimlyEkeyDevice class $27). The app uses
    the ivReset false cipher; for one block both modes give the same bytes.
    """
    if len(challenge) != CHALLENGE_LENGTH:
        raise BleProtocolError(f"Challenge must be {CHALLENGE_LENGTH} bytes, got {len(challenge)}")
    cipher = Aes128Cbc(owner_key, link_iv, iv_reset=False)
    return cipher.encrypt(bit_invert(cipher.decrypt(challenge)))


# --- AES (crypto/encrypters/Aes128CbcEncrypter.java) ------------------------


class Aes128Cbc:
    """AES-128-CBC without padding, in the app's two modes.

    iv_reset False: each message is one CBC run from the IV. This is what the
    command stream and owner auth use.
    iv_reset True: each 16-byte block is encrypted alone from the IV, so equal
    blocks give equal ciphertext. The app has the mode; nothing in it we have
    traced turns it on.

    Neither mode keeps state between calls, matching Cipher.doFinal.
    """

    def __init__(self, key: bytes, iv: bytes, *, iv_reset: bool) -> None:
        if len(key) != AES_KEY_LENGTH:
            raise BleValidationError(f"AES key must be {AES_KEY_LENGTH} bytes, got {len(key)}")
        if len(iv) != AES_BLOCK_SIZE:
            raise BleValidationError(f"AES IV must be {AES_BLOCK_SIZE} bytes, got {len(iv)}")
        self._key = bytes(key)
        self._iv = bytes(iv)
        self.iv_reset = iv_reset

    def __repr__(self) -> str:
        return f"Aes128Cbc(iv_reset={self.iv_reset})"

    def encrypt(self, plaintext: bytes) -> bytes:
        """Zero-pad to whole blocks, then encrypt. Empty in, empty out."""
        return self._run(zero_pad(plaintext), decrypt=False)

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt whole blocks. The zero padding stays; the frame inside says how long it is."""
        if len(ciphertext) % AES_BLOCK_SIZE:
            raise BleProtocolError(
                f"Cannot decrypt {len(ciphertext)} bytes, not a whole number of {AES_BLOCK_SIZE}-byte blocks"
            )
        return self._run(bytes(ciphertext), decrypt=True)

    def _run(self, data: bytes, *, decrypt: bool) -> bytes:
        if not self.iv_reset:
            return self._cbc(data, decrypt=decrypt)
        return b"".join(
            self._cbc(data[start : start + AES_BLOCK_SIZE], decrypt=decrypt)
            for start in range(0, len(data), AES_BLOCK_SIZE)
        )

    def _cbc(self, data: bytes, *, decrypt: bool) -> bytes:
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(self._iv))
        context = cipher.decryptor() if decrypt else cipher.encryptor()
        return context.update(data) + context.finalize()
