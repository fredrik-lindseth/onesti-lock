# BLE auth provisioning: can we own the lock locally?

Static analysis of the decompiled Nimly BLE app (`easyaccess.ekey.app`
v1.5.2, in `reversing/nimly-ble-decompiled/`, with the `apktool` smali where
jadx failed). The question: after a factory reset, is there a local
owner-enrollment path over BLE, or does the owner key only come from the ekey
cloud?

The code that implements the answer is in [ble-library.md](ble-library.md).

Labels as in [ble-protocol.md](ble-protocol.md): **(app code)** read in the
Java or smali, **(JDK run)** produced by the app's own crypto classes on
OpenJDK, **(untested on a lock)** still needs hardware. Nothing here has been
tried against a lock.

**Conclusion: a fully local owner-enrollment path exists.** The owner key is
generated locally by an ECDH exchange between app and lock. The ekey cloud
never mints it; it stores a copy the client computed. No server-signed token
is needed to become owner of a factory-reset lock. The cloud is needed only
for the guest ("ekey") sharing path, which we do not need. (app code;
untested on a lock)

## The three key layers

Three separate crypto layers. Only the third depends on the cloud, and only
for guests.

1. **Transport link key** (`NimlyEkeyDeviceBase`). Every connection runs a
   fresh secp256r1 ECDH: `ExchangeKeyPubM` (0x01) out, the lock's public key
   back, both in the clear. The shared secret is reversed; `[0:16]` is the
   AES key and `[16:32]` the IV. Every payload after that is AES-128-CBC, one
   CBC run per message from the link IV, zero-padded to whole blocks. Local,
   no identity: a tunnel, not authentication. Details in
   [ble-protocol.md](ble-protocol.md#encryption). (app code, JDK run)

2. **Owner auth** (challenge-response, `UserAuthBegin`/`UserAuthFinalize`).
   Proves you hold the owner key. Local, no cloud. (app code)

3. **Guest auth** (`EkeyUserAuth` 0x17, token-based). Needs a 32-byte token
   and a session public key minted by the ekey cloud. The only cloud-bound
   path, and optional. (app code)

## Owner auth: challenge-response with a symmetric key

`userAuthenticate()` in `admin/devices/NimlyEkeyDevice.java` (class `$27`;
app code):

1. `UserAuthBegin` (0x22) with `userId(1B) + deviceId(6B)`.
2. Lock returns a 16-byte challenge (`ResponseUserAuthBegin`).
3. App decrypts it with AES-128-CBC(key = owner key, iv = link IV), inverts
   every bit (`ByteExtensions.bitInverseArray`), encrypts the result with the
   same key and IV, and sends it in `UserAuthFinalize` (0x23).

The link IV is this connection's. That the lock encrypts the challenge the
same way is inferred from the app decrypting it so; the lock side is
untested. Both messages also travel inside the link encryption. The lock's
`UserAuthFinalize` answer carries a `credentials` byte the app never reads.

The owner key is a plain 16-byte AES key (`ParamUserAuth.key`). Nothing is
signed. Whoever holds those 16 bytes is the owner. (app code)

## The default owner credential on a factory-reset lock

`AddLockFragment.onDisplay` authenticates a freshly scanned lock with,
verbatim (app code):

```java
new ParamUserAuth(0, Constants.DefaultDeviceId, Constants.DefaultEncryptionKey)
```

From `ble/settings/Constants.java` (app code):

| Constant               | Value               | Used for                          |
| ---------------------- | ------------------- | --------------------------------- |
| `DefaultAdminUserId`   | `0`                 | owner auth user id                |
| `DefaultDeviceId`      | `00 00 00 00 00 00` | owner auth device id              |
| `DefaultEncryptionKey` | `11` x 16           | owner key for the challenge       |
| `DefaultEncryptionIv`  | `22` x 16           | nothing: no code reads it         |

So a factory-reset lock is expected to accept owner auth with a hardcoded
key (`0x11` x 16) and a zero device id, compile-time constants fetched from
nowhere. That is the door in, and it needs no server. The challenge is still
decrypted with the link IV, not `DefaultEncryptionIv`. That the lock accepts
the default key on current firmware is untested on a lock.

The advertisement says whether a lock is still in this state: an unenrolled
lock advertises seed `00 00` and an id of its own, an enrolled one a random
seed and a SHA-1 prefix of seed and device id
([ble-protocol.md](ble-protocol.md#scan-identification)). A lock enrolled
through the app and cloud has to be factory reset physically before the flow
below.

## Enrollment: the owner key is derived locally, then stored in the cloud

jadx could not decompile `AddLockFragment.finishSetup`. The order below is
read from the smali of `AddLockFragment.smali`, where the Kotlin line table
puts the BLE calls on source lines 197, 201, 202, 203 and 206, with the
arguments visible as constants and getter calls. (app code, smali)

1. Owner auth with the default credential, in `onDisplay`.
2. Cloud bookkeeping: create or fetch a location, `POST` the lock, `GET` its
   `DeviceData` (the server public key).
3. **`userAuthenticateUpdate()` (`UserAuthUpdate` 0x24) with
   `ParamUserAuthUpdate(0, 0)`: user id 0, credentials 0.** The crux. Class
   `$28`:
   - App generates a new secp256r1 key pair.
   - Sends `userId(1B) + credentials(1B) + publicKey(64B)`.
   - Lock replies with its own public key (`ResponseUserAuthUpdate`).
   - App computes `computeSecret(appPriv, lockPub)`, which returns the
     secret **byte-reversed**, and takes `[0:16]`. In raw ECDH terms that is
     `reverse(raw[16:32])`, not `raw[0:16]`. **That 16-byte value is the new
     owner key.** (app code, JDK run)
   Computed on the phone from the BLE exchange; the cloud is not in this
   step. What another `credentials` value would grant is not traced.
4. `deviceIdSet()` (`DeviceIdSet` 0x30) with `LockDto.getDeviceId()`, a
   6-byte id the cloud assigned in step 2.
5. `setTime()` (`CurrentTimeSet` 0x41) with
   `TimeExtensions.currentUint32Time()`: minutes since 2023-01-01 00:00 UTC
   as uint32. The app refuses a time before that epoch.
6. `serverKeyUpdate()` (`ServerKeyUpdate` 0x42) pushes the 64-byte
   `serverPublicKey` from the cloud's `DeviceData` into the lock and gets a
   64-byte lock public key back. This is what lets the cloud later mint guest
   ekey tokens; a 64-byte key with no signature, so not a trust anchor.
7. `deviceNameSet()` (`DeviceNameSet` 0x32) with the typed name, cut to 8
   bytes (`limitByteLength(name, 8)`).
8. `PUT DeviceData` with the lock public key from step 6 as
   `devicePublicKey`, then `POST` the credential: name `"Admin"`,
   `deviceUserId` 0, `deviceCredentials` 0, `deviceEncryptionKey` = the owner
   key from step 3.

The credential upload is the tell. `LockCredentialCreateDto` has a client
setter `setDeviceEncryptionKey(byte[])`: the app uploads the owner key it
computed in step 3. On reconnect, `ConnectLockFragment` downloads it back via
`LockCredentialDto.getDeviceEncryptionKey()` and authenticates with
`ParamUserAuth(deviceUserId, scanResult.deviceId, deviceEncryptionKey)`,
device id being the one whose hash matched the advertisement. The cloud is a
key-sync store for a value the client generated. (app code, smali)

## What this means for the integration

For full local owner control we replicate the enrollment locally and keep
the owner key in HA's own storage. The BLE library implements steps 2-7 in
`ble/client/session.py`, `ble/client/auth.py`, `ble/client/enrollment.py`
and `ble/protocol/commands.py` under `custom_components/onesti_lock/`,
untested on a lock and not wired in ([ble-library.md](ble-library.md)).

1. Factory reset the lock (physical).
2. BLE connect, transport ECDH handshake.
3. Owner auth with `userId 0`, `deviceId 00 x 6`, `key 0x11 x 16`.
4. `UserAuthUpdate` with user id 0 and credentials 0: generate a key pair,
   exchange, derive our own 16-byte owner key, **store it in HA** (this
   replaces the cloud credential). From here on the default key presumably
   no longer opens the lock, so anything learned after this point must be
   kept even if a later step fails.
5. `DeviceIdSet` with a 6-byte device id we pick (the cloud picks it in the
   app), and remember it: every later owner auth sends it, and it is the
   only way to recognise the lock's advertisement.
6. `CurrentTimeSet`, `ServerKeyUpdate` and `DeviceNameSet`, in the app's
   order.
7. From then on, owner auth with our stored key and device id unlocks every
   owner command: `PinCodeSet`/`Clear`, `FingerprintScan`/`Clear`,
   `ScanRfidCode`/`RfidCodeClear`, `EkeyOperate` lock/unlock, `BattInfoGet`,
   `DeviceLogGet`, `AutoLockSet`, `VolumeSet`, `KeypadEnableSet`.

`ServerKeyUpdate` only matters for cloud guest ekeys, which we do not use. We
still send it, with the public half of a key pair we generate and keep,
because the app sends it on every enrollment in the same session and nothing
shows whether the lock treats setup as complete without it. Holding that
private key ourselves also means no one else's server key stays trusted by
the lock. Managing everyone as owner-set credentials (PIN, fingerprint,
RFID) needs no cloud.

The only thing that still needs the ekey cloud is guest sharing
(`EkeyUserAuth` 0x17, token + session key). We drop it. A one-time cloud
bootstrap would only be needed to hand out cloud-minted guest keys, which is
not the goal.

## Wire formats confirmed here

Command payloads without the Layer 2 header (app code):

| Command            | Id   | Payload                                            | Answer                    |
| ------------------ | ---- | -------------------------------------------------- | ------------------------- |
| `UserAuthBegin`    | 0x22 | `userId(1B) + deviceId(6B)`                        | `challenge(16B)`          |
| `UserAuthFinalize` | 0x23 | `encrypt(bitInvert(decrypt(challenge)))`, 16B      | `credentials(1B)`         |
| `UserAuthUpdate`   | 0x24 | `userId(1B) + credentials(1B) + publicKey(64B)`    | `lockPublicKey(64B)`      |
| `DeviceIdSet`      | 0x30 | `deviceId(6B)`                                     | empty                     |
| `CurrentTimeSet`   | 0x41 | `minutes since 2023-01-01 UTC (uint32 LE)`         | empty                     |
| `ServerKeyUpdate`  | 0x42 | `serverPublicKey(64B)`                             | `lockPublicKey(64B)`      |
| `DeviceNameSet`    | 0x32 | `name(9B, ASCII, NUL-filled, max 8 chars)`         | empty                     |

Owner-auth crypto: AES-128-CBC, key = owner key (16B), iv = this
connection's link IV, `NoPadding` (the 16-byte challenge needs none). Bit
inversion is a bitwise NOT over the decrypted 16 bytes. Public keys are X
then Y, 32 bytes each, little endian. (app code, JDK run)

## Caveats

- All from static analysis of one app version plus a JDK run of its crypto
  classes; never run against hardware. That a factory-reset lock accepts
  `0x11 x 16` on current firmware is confirmed only in code.
- The lock may bind the owner key to the device id set in step 4; the app
  sets one during enrollment and sends it in every later `UserAuthBegin`, so
  our flow does the same and remembers it. Whether the lock checks it is
  untested on a lock.
- The owner key is `[0:16]` of the reversed secret, so the byte order
  depends on the secret being a full 32 bytes with leading zeros kept.
  Python's `cryptography` always gives that, so our side is not at risk.
  Whether the lock's own ECDH pads to 32 bytes too is untested. The app has
  the same question about Conscrypt: if it stripped a leading zero the app
  would disagree with the lock about one connection in 256. That the app
  works in the field is weak evidence that the lock pads.
- Firmware floor: 4.6.0 to connect, 4.7.90 for model detection and the admin
  commands (PIN, fingerprint, RFID, keypad, auto-lock, volume, battery). The
  enrollment commands themselves are offered from 4.6.0.
- Which reset puts a lock back into the factory state this flow needs is not
  known. There are two: the module's own button (about 15 s, which also
  drops the Zigbee pairing) and the lock body's gold reset button (which
  deletes every code, tag and fingerprint). The owner key presumably lives in
  the module, so the module reset is the likely one, but nobody has watched
  the seed go back to `00 00` after either. A lock already enrolled in the
  vendor's BLE app (or unloc) has to go through that reset first, and after
  our enrollment that app no longer has the lock.
