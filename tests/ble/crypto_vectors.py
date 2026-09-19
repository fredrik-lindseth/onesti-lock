"""Byte vectors for ble/crypto.py.

Kept apart from vectors.py, which holds the frame vectors. Nothing here was
captured from a lock. Each vector is one of three kinds, and the comment above
it says which:

- kat: a published known-answer test (NIST), independent of the app and of us.
- executed: printed by tests/ble/java/CryptoVectors.java, which runs the app's
  own decompiled crypto classes on a desktop JDK. It proves our Python does
  what the app's code does, byte for byte. It does not prove the lock agrees,
  and Android's Cipher provider is Conscrypt, not the JDK's.
- derived: worked out from a kat or executed vector by the rule the app's code
  applies (reverse, split, take [0:16]), so a test states the rule on its own.

Keys and challenges that are not from NIST are arbitrary test inputs.
"""
from __future__ import annotations


def _hex(text: str) -> bytes:
    return bytes.fromhex(text)


# --- secp256r1 ---------------------------------------------------------------

# kat: the curve's generator G (SEC 2, section 2.4.2), which is the public key
# for the private key 1.
P256_GX = _hex("6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296")
P256_GY = _hex("4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5")
# kat: the curve order n. A private key must lie in 1..n-1.
P256_N = _hex("ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551")

# kat: NIST CAVS ECC CDH primitive test vectors, P-256, COUNT = 0. Big endian,
# as NIST writes them. IUT is our side, CAVS the peer.
CAVS_D_IUT = _hex("7d7dc5f71eb29ddaf80d6214632eeae03d9058af1fb6d22ed80badb62bc1a534")
CAVS_QIUT_X = _hex("ead218590119e8876b29146ff89ca61770c4edbbf97d38ce385ed281d8a6b230")
CAVS_QIUT_Y = _hex("28af61281fd35e2fa7002523acc85a429cb06ee6648325389f59edfce1405141")
CAVS_QCAVS_X = _hex("700c48f77f56584c5cc632ca65640db91b6bacce3a4df6b42ce7cc838833d287")
CAVS_QCAVS_Y = _hex("db71e509e3fd9b060ddb20ba5c51dcc5948d46fbf640dfe0441782cab85fa4ac")
CAVS_Z = _hex("46fc62106420ff012e54a434fbdd2d25ccc5852060561e68040dd7778997bd7b")

# executed: the same vector in the app's wire encoding (CryptoVectors:
# private_le, own_public, peer_public), each coordinate little endian.
CAVS_PRIVATE_KEY_WIRE = _hex("34a5c12bb6ad0bd82ed2b61faf58903de0ea2e6314620df8da9db21ef7c57d7d")
CAVS_OWN_PUBLIC_KEY_WIRE = _hex(
    "30b2a6d881d25e38ce387df9bbedc47017a69cf86f14296b87e819015918d2ea"
    "415140e1fced599f38258364e66eb09c425ac8ac232500a72f5ed31f2861af28"
)
CAVS_PEER_PUBLIC_KEY_WIRE = _hex(
    "87d2338883cce72cb4f64d3aceac6b1bb90d6465ca32c65c4c58567ff7480c70"
    "aca45fb8ca821744e0df40f6fb468d94c5dc515cba20db0d069bfde309e571db"
)
# executed: Secp256r1SecretExchanger.computeSecret on those keys (secret).
# It is CAVS_Z reversed.
CAVS_SHARED_SECRET = _hex("7bbd978977d70d04681e56602085c5cc252dddfb34a4542e01ff20641062fc46")

# derived: getLinkKey and getLinkIv, [0:16] and [16:32] of the secret. The
# owner key UserAuthUpdate yields is the same [0:16] of its own exchange.
CAVS_LINK_KEY = _hex("7bbd978977d70d04681e56602085c5cc")
CAVS_LINK_IV = _hex("252dddfb34a4542e01ff20641062fc46")

# --- AES-128 -----------------------------------------------------------------

# kat: NIST SP 800-38A, appendix F.1.1 (ECB) and F.2.1 (CBC), AES-128.
SP800_38A_KEY = _hex("2b7e151628aed2a6abf7158809cf4f3c")
SP800_38A_IV = _hex("000102030405060708090a0b0c0d0e0f")
SP800_38A_PLAINTEXT = _hex(
    "6bc1bee22e409f96e93d7e117393172a"
    "ae2d8a571e03ac9c9eb76fac45af8e51"
    "30c81c46a35ce411e5fbc1191a0a52ef"
    "f69f2445df4f9b17ad2b417be66c3710"
)
SP800_38A_CBC_CIPHERTEXT = _hex(
    "7649abac8119b246cee98e9b12e9197d"
    "5086cb9b507219ee95db113a917678b2"
    "73bed6b8e3c1743b7116e69e22229516"
    "3ff1caa1681fac09120eca307586e1a7"
)
SP800_38A_ECB_CIPHERTEXT = _hex(
    "3ad77bb40d7a3660a89ecaf32466ef97"
    "f5d3d58503b9699de785895a96fdbaaf"
    "43b1cd7f598ece23881b00e3ed030688"
    "7b0c785e27e8ad3f8223207104725dd4"
)

# executed: Aes128CbcEncrypter with ivReset true on the SP 800-38A key, IV and
# plaintext (reset). Block one equals CBC block one; every later block is
# encrypted from the original IV again.
SP800_38A_IV_RESET_CIPHERTEXT = _hex(
    "7649abac8119b246cee98e9b12e9197d"
    "bb4428e13712722750d4dbec8294bba0"
    "d9f6492663158e947664820606526b40"
    "27e1ff0bdb5b68c6613ec30d7e59fccc"
)

# executed: ivReset false with the SP 800-38A key and IV, on inputs that need
# zero padding (pad_5, pad_17). The app encrypts 01 02 03 04 05 as that plus
# eleven zero bytes, and 00..10 as two blocks.
PAD_5_PLAINTEXT = _hex("0102030405")
PAD_5_CIPHERTEXT = _hex("2d971c5ddabf641d9a013db4f06d296f")
PAD_17_PLAINTEXT = _hex("000102030405060708090a0b0c0d0e0f10")
PAD_17_CIPHERTEXT = _hex("7df76b0c1ab899b33e42f047b91b546f09961489d1984ceac1b48410a277fbeb")

# --- Owner auth --------------------------------------------------------------

# executed: NimlyEkeyDevice $27 with the default owner key (0x11 x 16), link IV
# SP800_38A_IV and this challenge (owner_answer).
OWNER_CHALLENGE = _hex("00112233445566778899aabbccddeeff")
OWNER_ANSWER_DEFAULT_KEY = _hex("a2cbc9d9b56c2df7b8f15917ce44d566")
