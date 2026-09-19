"""ble/crypto.py: key exchange, AES modes, link and owner keys, owner auth.

The classes below say what kind of evidence each test rests on:

- Kat*: published NIST known answers. They check that we call the primitives
  correctly and that the wire encoding round-trips a known key.
- Executed*: bytes printed by the app's own decompiled crypto classes on a JDK
  (tests/ble/java/CryptoVectors.java). They pin us to what the app does.
- Derived*: rules read from the app's call sites, stated as tests.
- SelfConsistent*: our own output checked against itself. They catch a broken
  round trip, never a wrong convention both directions share.

None of it has been checked against a lock.
"""
from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..conftest import load_component_module
from . import crypto_vectors as v
from .leaks import MARKER, assert_clean, assert_no_material

const = load_component_module("ble.protocol.const")
client_const = load_component_module("ble.client.const")
errors = load_component_module("ble.errors")
crypto = load_component_module("ble.crypto")


def _le(big_endian: bytes) -> bytes:
    return big_endian[::-1]


def _wire(x: bytes, y: bytes) -> bytes:
    return _le(x) + _le(y)


class TestSizes:
    def test_cipher_and_curve_sizes(self):
        # settings/Constants.java; the challenge is one AES block.
        assert crypto.AES_BLOCK_SIZE == crypto.AES_KEY_LENGTH == const.CHALLENGE_LENGTH == 16
        assert crypto.PRIVATE_KEY_LENGTH == crypto.SHARED_SECRET_LENGTH == 32


# --- kat ---------------------------------------------------------------------


class TestKatKeyExchange:
    def test_private_key_one_gives_the_generator(self):
        # The smallest scalar also checks that a key with 31 leading zero
        # bytes (big endian) still encodes as 32 bytes.
        pair = crypto.key_pair_from_private_key(b"\x01" + bytes(31))
        assert pair.private_key == b"\x01" + bytes(31)
        assert pair.public_key == _wire(v.P256_GX, v.P256_GY)

    def test_cavs_public_key(self):
        pair = crypto.key_pair_from_private_key(_le(v.CAVS_D_IUT))
        assert pair.public_key == _wire(v.CAVS_QIUT_X, v.CAVS_QIUT_Y)

    def test_cavs_shared_secret_is_z_reversed(self):
        secret = crypto.compute_shared_secret(_le(v.CAVS_D_IUT), _wire(v.CAVS_QCAVS_X, v.CAVS_QCAVS_Y))
        assert secret == _le(v.CAVS_Z)

    def test_largest_private_key_is_accepted(self):
        n = int.from_bytes(v.P256_N, "big")
        pair = crypto.key_pair_from_private_key((n - 1).to_bytes(32, "little"))
        # (n - 1) * G = -G: same X, Y mirrored.
        p = 2**256 - 2**224 + 2**192 + 2**96 - 1
        gy = int.from_bytes(v.P256_GY, "big")
        assert pair.public_key == _wire(v.P256_GX, (p - gy).to_bytes(32, "big"))


class TestKatAes:
    def test_cbc_is_sp800_38a(self):
        cipher = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=False)
        assert cipher.encrypt(v.SP800_38A_PLAINTEXT) == v.SP800_38A_CBC_CIPHERTEXT
        assert cipher.decrypt(v.SP800_38A_CBC_CIPHERTEXT) == v.SP800_38A_PLAINTEXT

    def test_iv_reset_with_zero_iv_is_ecb(self):
        # Each block alone from IV 0 is E(K, P), which is what ECB is.
        cipher = crypto.Aes128Cbc(v.SP800_38A_KEY, bytes(16), iv_reset=True)
        assert cipher.encrypt(v.SP800_38A_PLAINTEXT) == v.SP800_38A_ECB_CIPHERTEXT
        assert cipher.decrypt(v.SP800_38A_ECB_CIPHERTEXT) == v.SP800_38A_PLAINTEXT


# --- executed ----------------------------------------------------------------


class TestExecutedKeyExchange:
    def test_wire_encoding_of_the_private_key(self):
        assert _le(v.CAVS_D_IUT) == v.CAVS_PRIVATE_KEY_WIRE

    def test_wire_encoding_of_the_public_keys(self):
        own = crypto.key_pair_from_private_key(v.CAVS_PRIVATE_KEY_WIRE)
        assert own.public_key == v.CAVS_OWN_PUBLIC_KEY_WIRE
        assert _wire(v.CAVS_QCAVS_X, v.CAVS_QCAVS_Y) == v.CAVS_PEER_PUBLIC_KEY_WIRE

    def test_shared_secret(self):
        secret = crypto.compute_shared_secret(v.CAVS_PRIVATE_KEY_WIRE, v.CAVS_PEER_PUBLIC_KEY_WIRE)
        assert secret == v.CAVS_SHARED_SECRET

    def test_encode_public_key(self):
        key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(v.CAVS_QIUT_X, "big"), int.from_bytes(v.CAVS_QIUT_Y, "big"), ec.SECP256R1()
        ).public_key()
        assert crypto.encode_public_key(key) == v.CAVS_OWN_PUBLIC_KEY_WIRE


class TestExecutedAes:
    def test_iv_reset(self):
        cipher = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=True)
        assert cipher.encrypt(v.SP800_38A_PLAINTEXT) == v.SP800_38A_IV_RESET_CIPHERTEXT
        assert cipher.decrypt(v.SP800_38A_IV_RESET_CIPHERTEXT) == v.SP800_38A_PLAINTEXT

    def test_no_chaining_between_messages(self):
        # Cipher.doFinal puts the app's cipher back to its IV, so the same
        # message twice gives the same bytes twice.
        cipher = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=False)
        first = cipher.encrypt(v.SP800_38A_PLAINTEXT)
        assert cipher.encrypt(v.SP800_38A_PLAINTEXT) == first == v.SP800_38A_CBC_CIPHERTEXT

    @pytest.mark.parametrize(
        ("plaintext", "ciphertext"),
        [(v.PAD_5_PLAINTEXT, v.PAD_5_CIPHERTEXT), (v.PAD_17_PLAINTEXT, v.PAD_17_CIPHERTEXT)],
    )
    def test_zero_padding(self, plaintext, ciphertext):
        cipher = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=False)
        assert cipher.encrypt(plaintext) == ciphertext
        # The padding comes back; the frame inside carries the real length.
        assert cipher.decrypt(ciphertext) == crypto.zero_pad(plaintext)

    @pytest.mark.parametrize("iv_reset", [False, True])
    def test_empty_stays_empty(self, iv_reset):
        cipher = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=iv_reset)
        assert cipher.encrypt(b"") == b""
        assert cipher.decrypt(b"") == b""


class TestExecutedOwnerAuth:
    def test_answer_with_the_default_key(self):
        answer = crypto.answer_owner_challenge(v.OWNER_CHALLENGE, client_const.DEFAULT_ENCRYPTION_KEY, v.SP800_38A_IV)
        assert answer == v.OWNER_ANSWER_DEFAULT_KEY


# --- derived -----------------------------------------------------------------


class TestDerivedKeys:
    def test_link_keys_split_the_reversed_secret(self):
        keys = crypto.LinkKeys.from_shared_secret(v.CAVS_SHARED_SECRET)
        assert (keys.key, keys.iv) == (v.CAVS_LINK_KEY, v.CAVS_LINK_IV)

    def test_derive_link_keys(self):
        keys = crypto.derive_link_keys(v.CAVS_PRIVATE_KEY_WIRE, v.CAVS_PEER_PUBLIC_KEY_WIRE)
        assert keys == crypto.LinkKeys(key=v.CAVS_LINK_KEY, iv=v.CAVS_LINK_IV)

    def test_owner_key_is_the_first_half_of_the_reversed_secret(self):
        # NimlyEkeyDevice $28: copyOfRange(computeSecret(...), 0, 16). Not the
        # first 16 bytes of the raw ECDH output, which would be CAVS_Z[:16].
        owner_key = crypto.derive_owner_key(v.CAVS_PRIVATE_KEY_WIRE, v.CAVS_PEER_PUBLIC_KEY_WIRE)
        assert owner_key == v.CAVS_LINK_KEY == _le(v.CAVS_Z[16:])
        assert owner_key != v.CAVS_Z[:16]

    def test_command_stream_cipher_chains_within_a_message(self):
        # NimlyEkeyDeviceBase sets the stream's encrypter with ivReset false.
        keys = crypto.LinkKeys(key=v.SP800_38A_KEY, iv=v.SP800_38A_IV)
        cipher = keys.cipher()
        assert cipher.iv_reset is False
        assert cipher.encrypt(v.SP800_38A_PLAINTEXT) == v.SP800_38A_CBC_CIPHERTEXT


class TestDerivedOwnerAuth:
    def test_answer_is_encrypt_invert_decrypt(self):
        # Written out with the primitives, one block, key and IV arbitrary.
        key, iv = bytes(range(16)), bytes(range(16, 32))
        challenge = bytes(range(32, 48))

        def run(data: bytes, *, decrypt: bool) -> bytes:
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
            context = cipher.decryptor() if decrypt else cipher.encryptor()
            return context.update(data) + context.finalize()

        expected = run(bytes(b ^ 0xFF for b in run(challenge, decrypt=True)), decrypt=False)
        assert crypto.answer_owner_challenge(challenge, key, iv) == expected


class TestDerivedBitInvert:
    def test_every_bit_flips(self):
        assert crypto.bit_invert(bytes.fromhex("00ff0f5a")) == bytes.fromhex("ff00f0a5")

    def test_twice_is_identity(self):
        data = bytes(range(256))
        assert crypto.bit_invert(crypto.bit_invert(data)) == data

    def test_empty(self):
        assert crypto.bit_invert(b"") == b""


class TestDerivedZeroPad:
    @pytest.mark.parametrize(("length", "padded"), [(0, 0), (1, 16), (15, 16), (16, 16), (17, 32), (32, 32)])
    def test_lengths(self, length, padded):
        data = bytes([0xAB] * length)
        result = crypto.zero_pad(data)
        assert len(result) == padded
        assert result == data + bytes(padded - length)

    def test_accepts_bytearray(self):
        assert crypto.zero_pad(bytearray(b"\x01")) == b"\x01" + bytes(15)


# --- self-consistency --------------------------------------------------------


class TestSelfConsistentKeyExchange:
    def test_both_sides_agree(self):
        app, lock = crypto.generate_key_pair(), crypto.generate_key_pair()
        assert crypto.compute_shared_secret(app.private_key, lock.public_key) == crypto.compute_shared_secret(
            lock.private_key, app.public_key
        )

    def test_fresh_pair_round_trips_through_its_private_key(self):
        pair = crypto.generate_key_pair()
        assert len(pair.private_key) == 32
        assert len(pair.public_key) == 64
        assert crypto.key_pair_from_private_key(pair.private_key) == pair

    def test_fresh_pairs_differ(self):
        assert crypto.generate_key_pair().private_key != crypto.generate_key_pair().private_key

    def test_owner_key_both_sides(self):
        app, lock = crypto.generate_key_pair(), crypto.generate_key_pair()
        assert crypto.derive_owner_key(app.private_key, lock.public_key) == crypto.derive_owner_key(
            lock.private_key, app.public_key
        )


class TestSelfConsistentAes:
    @pytest.mark.parametrize("iv_reset", [False, True])
    @pytest.mark.parametrize("length", [1, 15, 16, 17, 31, 32, 33, 68, 200])
    def test_round_trip(self, iv_reset, length):
        cipher = crypto.Aes128Cbc(os.urandom(16), os.urandom(16), iv_reset=iv_reset)
        plaintext = os.urandom(length)
        ciphertext = cipher.encrypt(plaintext)
        assert len(ciphertext) % 16 == 0
        assert cipher.decrypt(ciphertext) == crypto.zero_pad(plaintext)

    def test_iv_reset_repeats_equal_blocks(self):
        # The weakness of the mode, and the quickest way to tell the two apart.
        block = bytes(range(16))
        reset = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=True).encrypt(block * 2)
        chained = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=False).encrypt(block * 2)
        assert reset[:16] == reset[16:]
        assert chained[:16] != chained[16:]
        assert reset[:16] == chained[:16]

    def test_does_not_keep_the_callers_buffer(self):
        key, iv = bytearray(v.SP800_38A_KEY), bytearray(v.SP800_38A_IV)
        cipher = crypto.Aes128Cbc(key, iv, iv_reset=False)
        key[:] = bytes(16)
        iv[:] = bytes(16)
        assert cipher.encrypt(v.SP800_38A_PLAINTEXT) == v.SP800_38A_CBC_CIPHERTEXT


class TestSelfConsistentOwnerAuth:
    def test_lock_side_check(self):
        # The lock would send E(R) and expect E(NOT R) back.
        owner_key, link_iv = os.urandom(16), os.urandom(16)
        lock = crypto.Aes128Cbc(owner_key, link_iv, iv_reset=False)
        secret = os.urandom(16)
        answer = crypto.answer_owner_challenge(lock.encrypt(secret), owner_key, link_iv)
        assert lock.decrypt(answer) == crypto.bit_invert(secret)

    def test_both_modes_agree_on_one_block(self):
        owner_key, link_iv, challenge = os.urandom(16), os.urandom(16), os.urandom(16)
        reset = crypto.Aes128Cbc(owner_key, link_iv, iv_reset=True)
        expected = reset.encrypt(crypto.bit_invert(reset.decrypt(challenge)))
        assert crypto.answer_owner_challenge(challenge, owner_key, link_iv) == expected


# --- validation, and no secrets in errors or repr ----------------------------

class TestValidation:
    @pytest.mark.parametrize("length", [0, 31, 33])
    def test_private_key_length(self, length):
        key = MARKER[:length]
        with pytest.raises(errors.BleValidationError, match=f"32 bytes, got {length}") as excinfo:
            crypto.key_pair_from_private_key(key)
        assert_clean(excinfo, key or b"\xa5")

    @pytest.mark.parametrize(
        "scalar",
        [0, int.from_bytes(v.P256_N, "big"), int.from_bytes(v.P256_N, "big") + 1, 2**256 - 1],
        ids=["zero", "n", "n+1", "max"],
    )
    def test_private_key_out_of_range(self, scalar):
        key = scalar.to_bytes(32, "little")
        with pytest.raises(errors.BleValidationError, match="not a valid secp256r1 scalar") as excinfo:
            crypto.compute_shared_secret(key, v.CAVS_PEER_PUBLIC_KEY_WIRE)
        assert_clean(excinfo, key)

    @pytest.mark.parametrize("length", [0, 63, 65])
    def test_public_key_length(self, length):
        with pytest.raises(errors.BleProtocolError, match=f"64 bytes, got {length}"):
            crypto.compute_shared_secret(v.CAVS_PRIVATE_KEY_WIRE, bytes([0xA5] * length))

    def test_public_key_off_the_curve(self):
        off_curve = (1).to_bytes(32, "little") + (1).to_bytes(32, "little")
        with pytest.raises(errors.BleProtocolError, match="not a point on secp256r1") as excinfo:
            crypto.compute_shared_secret(v.CAVS_PRIVATE_KEY_WIRE, off_curve)
        assert_clean(excinfo, v.CAVS_PRIVATE_KEY_WIRE)

    def test_public_key_in_big_endian_is_refused(self):
        # The mistake the wire encoding invites. A big-endian key is almost
        # never a point on the curve when read little endian.
        with pytest.raises(errors.BleProtocolError):
            crypto.compute_shared_secret(v.CAVS_PRIVATE_KEY_WIRE, v.CAVS_QCAVS_X + v.CAVS_QCAVS_Y)

    @pytest.mark.parametrize("length", [0, 31, 33])
    def test_shared_secret_length(self, length):
        with pytest.raises(errors.BleValidationError, match=f"32 bytes, got {length}") as excinfo:
            crypto.LinkKeys.from_shared_secret(MARKER[:length])
        assert_clean(excinfo, MARKER[:length] or b"\xa5")

    @pytest.mark.parametrize(("key_length", "iv_length"), [(15, 16), (17, 16), (32, 16), (16, 15), (16, 17)])
    def test_aes_key_and_iv_length(self, key_length, iv_length):
        key, iv = MARKER[:key_length], bytes([0x5A] * iv_length)
        with pytest.raises(errors.BleValidationError, match="must be 16 bytes") as excinfo:
            crypto.Aes128Cbc(key, iv, iv_reset=False)
        assert_clean(excinfo, key, iv)

    @pytest.mark.parametrize("length", [1, 15, 17])
    def test_decrypt_partial_block(self, length):
        cipher = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=False)
        with pytest.raises(errors.BleProtocolError, match=f"Cannot decrypt {length} bytes") as excinfo:
            cipher.decrypt(MARKER[:length])
        assert_clean(excinfo, MARKER[:length], v.SP800_38A_KEY)

    @pytest.mark.parametrize("length", [0, 15, 32])
    def test_challenge_length(self, length):
        with pytest.raises(errors.BleProtocolError, match=f"16 bytes, got {length}"):
            crypto.answer_owner_challenge(MARKER[:length], client_const.DEFAULT_ENCRYPTION_KEY, v.SP800_38A_IV)

    def test_owner_key_length(self):
        key = MARKER[:15]
        with pytest.raises(errors.BleValidationError) as excinfo:
            crypto.answer_owner_challenge(v.OWNER_CHALLENGE, key, v.SP800_38A_IV)
        assert_clean(excinfo, key)

    def test_errors_belong_to_the_library(self):
        with pytest.raises(errors.BleError):
            crypto.Aes128Cbc(b"", b"", iv_reset=False)


class TestRepr:
    def test_key_pair(self):
        pair = crypto.key_pair_from_private_key(v.CAVS_PRIVATE_KEY_WIRE)
        assert_no_material(repr(pair), pair.private_key, pair.public_key)
        assert repr(pair) == "KeyPair()"

    def test_link_keys(self):
        keys = crypto.LinkKeys.from_shared_secret(v.CAVS_SHARED_SECRET)
        assert_no_material(repr(keys), keys.key, keys.iv)

    def test_cipher(self):
        cipher = crypto.Aes128Cbc(v.SP800_38A_KEY, v.SP800_38A_IV, iv_reset=True)
        assert_no_material(repr(cipher), v.SP800_38A_KEY, v.SP800_38A_IV)
        assert repr(cipher) == "Aes128Cbc(iv_reset=True)"
