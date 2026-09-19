// Prints the "executed" vectors in tests/ble/crypto_vectors.py by running the
// Nimly app's own crypto classes, as decompiled, on a desktop JDK.
//
// The app sources are local only (reversing/ is gitignored). From the main
// checkout, with any JDK 17 or newer:
//
//   S=reversing/nimly-ble-decompiled/sources
//   B=com/nimly/ekey/ble
//   W=$(mktemp -d)
//   (cd $S && for f in $B/crypto/encrypters/*.java $B/crypto/exchangers/*.java \
//       $B/extensions/ByteExtensions.java $B/extensions/BigIntegerExtensions.java \
//       $B/extensions/StringExtensions.java $B/models/Data.java $B/models/IData.java; do
//     mkdir -p $W/$(dirname $f) && cp $f $W/$f; done)
//   cp -R tests/ble/java/stubs/. tests/ble/java/CryptoVectors.java $W
//   (cd $W && javac -nowarn -d out $(find . -name '*.java') && java -cp out CryptoVectors)
//
// The two stubs stand in for android.util.Base64 and kotlin.UByte, the only
// things those classes need from outside the package. Last run on OpenJDK 27.
//
// What this proves: our Python does what the app's code does. What it does not:
// the app runs on Android, whose Cipher comes from Conscrypt, not the JDK's
// SunJCE. Both follow the same Cipher contract (doFinal resets to the IV given
// at init), but only a capture from a lock settles it.

import com.nimly.ekey.ble.crypto.encrypters.Aes128CbcEncrypter;
import com.nimly.ekey.ble.crypto.exchangers.IPrivateKey;
import com.nimly.ekey.ble.crypto.exchangers.Secp256r1SecretExchanger;
import com.nimly.ekey.ble.extensions.BigIntegerExtensions;
import com.nimly.ekey.ble.extensions.ByteExtensions;
import com.nimly.ekey.ble.extensions.StringExtensions;
import java.lang.reflect.Method;
import java.math.BigInteger;
import java.security.KeyFactory;
import java.security.interfaces.ECPrivateKey;
import java.security.interfaces.ECPublicKey;
import java.security.spec.ECPoint;
import java.security.spec.ECPublicKeySpec;

public class CryptoVectors {
    static String hex(byte[] b) { return ByteExtensions.bytesToHex(b); }
    static byte[] unhex(String s) { return StringExtensions.hexToByteArray(s); }
    static String le(String bigEndianHex) { return BigIntegerExtensions.toLittleEndianHex(new BigInteger(bigEndianHex, 16)); }

    public static void main(String[] args) throws Exception {
        Secp256r1SecretExchanger exchanger = new Secp256r1SecretExchanger();

        // NIST CAVS ECC CDH, P-256, COUNT = 0, handed to the app in its own
        // little-endian hex.
        String privateLe = le("7d7dc5f71eb29ddaf80d6214632eeae03d9058af1fb6d22ed80badb62bc1a534");
        String peerLe = le("700c48f77f56584c5cc632ca65640db91b6bacce3a4df6b42ce7cc838833d287")
                + le("db71e509e3fd9b060ddb20ba5c51dcc5948d46fbf640dfe0441782cab85fa4ac");
        System.out.println("private_le    " + privateLe);
        System.out.println("peer_public   " + peerLe);
        System.out.println("secret        " + exchanger.computeSecret(
                new com.nimly.ekey.ble.crypto.exchangers.PrivateKey(privateLe),
                new com.nimly.ekey.ble.crypto.exchangers.PublicKey(peerLe)));

        // The public key for that private key (QIUT), through the app's own
        // private encoder.
        Method toPrivate = Secp256r1SecretExchanger.class.getDeclaredMethod("getPrivateKey", IPrivateKey.class);
        toPrivate.setAccessible(true);
        ECPrivateKey privateKey = (ECPrivateKey) toPrivate.invoke(
                exchanger, new com.nimly.ekey.ble.crypto.exchangers.PrivateKey(privateLe));
        ECPublicKey own = (ECPublicKey) KeyFactory.getInstance("EC").generatePublic(new ECPublicKeySpec(new ECPoint(
                new BigInteger("ead218590119e8876b29146ff89ca61770c4edbbf97d38ce385ed281d8a6b230", 16),
                new BigInteger("28af61281fd35e2fa7002523acc85a429cb06ee6648325389f59edfce1405141", 16)),
                privateKey.getParams()));
        Method encode = Secp256r1SecretExchanger.class.getDeclaredMethod("getPublicKey", ECPublicKey.class);
        encode.setAccessible(true);
        System.out.println("own_public    " + encode.invoke(exchanger, own));

        // NIST SP 800-38A F.2.1 key, IV and plaintext through both modes.
        byte[] key = unhex("2b7e151628aed2a6abf7158809cf4f3c");
        byte[] iv = unhex("000102030405060708090a0b0c0d0e0f");
        byte[] plain = unhex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
                + "30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710");
        Aes128CbcEncrypter increment = new Aes128CbcEncrypter(key, iv, false);
        Aes128CbcEncrypter reset = new Aes128CbcEncrypter(key, iv, true);
        System.out.println("increment_1   " + hex(increment.encrypt(plain)));
        // Same encrypter, same message again: equal output means nothing chains.
        System.out.println("increment_2   " + hex(increment.encrypt(plain)));
        System.out.println("reset         " + hex(reset.encrypt(plain)));
        System.out.println("pad_5         " + hex(increment.encrypt(unhex("0102030405"))));
        System.out.println("pad_17        " + hex(increment.encrypt(unhex("000102030405060708090a0b0c0d0e0f10"))));
        System.out.println("empty         '" + hex(increment.encrypt(new byte[0])) + "'");

        // Owner auth as NimlyEkeyDevice $27 does it, with the default key and
        // an arbitrary challenge and link IV.
        Aes128CbcEncrypter owner = new Aes128CbcEncrypter(ByteExtensions.buildRepeatArray(17, 16), iv, false);
        byte[] challenge = unhex("00112233445566778899aabbccddeeff");
        System.out.println("owner_answer  " + hex(owner.encrypt(ByteExtensions.bitInverseArray(owner.decrypt(challenge)))));
    }
}
