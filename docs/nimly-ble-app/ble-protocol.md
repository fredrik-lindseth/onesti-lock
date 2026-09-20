# Nimly BLE protocol reference

Decompiled with `jadx` from `easyaccess.ekey.app` v1.5.2 (versionCode 13,
native Android/Kotlin; the sources sit in `reversing/nimly-ble-decompiled/`,
local and gitignored). Where jadx could not decompile a method, the `apktool`
smali of the same APK was read instead. All communication happens over a
single BLE characteristic. The integration does not use BLE today; the
protocol is documented as a possible future channel. A Python implementation
of it lives in `custom_components/onesti_lock/ble/`, not yet wired into the
integration or run against a lock; see [ble-library.md](ble-library.md).

Each claim carries one of three labels:

- **(app code)**: read directly in the decompiled Java or the smali.
- **(JDK run)**: the app's own decompiled crypto classes were compiled and run
  on OpenJDK, and the output matched. The harness is
  `tests/ble/java/CryptoVectors.java`, with stubs for `android.util.Base64`
  and `kotlin.UByte`; how to run it is in
  [ble-library.md](ble-library.md#where-the-vectors-come-from). Android uses Conscrypt rather than SunJCE; the `Cipher`
  and `KeyAgreement` contract is the same, but only a lock can settle it.
- **(untested on a lock)**: nothing in this document has been captured from or
  sent to a real lock yet. The label is repeated where a reader might assume
  otherwise.

Paths in parentheses are relative to `com/nimly/ekey/ble/` in the sources.

## BLE UUIDs

(app code, `settings/Constants.java`)

| Purpose                    | UUID                                   |
| -------------------------- | -------------------------------------- |
| Service                    | `ba4bfd00-c447-19bf-f38d-4890b3a824c8` |
| Communication (r/w/notify) | `ba4bfd03-c447-19bf-f38d-4890b3a824c8` |
| Advertising (16-bit)       | `0xFD00`                               |
| CCCD                       | `00002902-0000-1000-8000-00805f9b34fb` |
| Device Info Service        | `0000180a-0000-1000-8000-00805f9b34fb` |
| Software Revision          | `00002a28-0000-1000-8000-00805f9b34fb` |

## Packet format

All multi-byte integers are little endian (app code,
`LittleEndianStreamWriter`/`Reader`).

### Layer 1: Packet

```
[PacketType: 1B] [Length: 1B] [RFU: 1B] [SeqNum: 1B] [Payload: Length bytes]
```

(app code, `communication/packets/Packet.java`) `Length` is the payload length
only. `Packet.toData` refuses a payload over 255 bytes, and `Packet.fromData`
ignores any bytes after the declared length.

PacketType (app code, `PacketTypeId.java`):

| Byte | Type                           |
| ---- | ------------------------------ |
| 0x01 | Single (unencrypted)           |
| 0x02 | SingleEncrypted                |
| 0x03 | BlobStart (multi-packet start) |
| 0x04 | BlobStream (continuation)      |
| 0x05 | BlobComplete (end)             |
| 0x06 | Ack                            |
| 0x07 | Nac                            |
| 0xF0 | Error                          |

The app never sends Ack, Nac or Error and never waits for one: the methods
that would (`waitStatusResponse`, `writeStatusResponse` in `PayloadStream`)
are private and never called. What the lock means by them is not traced
(app code).

### Blobs and the MTU

The app asks for MTU 23 and never more (`BleConnection.DefaultMtu`). A packet
then has room for 23 - 3 (ATT header) - 4 (packet header) = 16 payload bytes
(`PayloadStream.getPayloadMax`). (app code)

`PayloadStream` sends a payload as one Single packet only when its length plus
4 fits that room, so at MTU 23 anything over 12 bytes goes as a blob. Since
every encrypted payload is padded to a multiple of 16 bytes (see
[Encryption](#encryption)), every encrypted command goes as a blob. (app code)

A blob is a BlobStart packet, zero or more BlobStream packets and a
BlobComplete packet (app code, `communication/blobs/Blob.java`,
`PayloadStream.writeBlob`):

```
BlobStart payload: [Flags: 1B] [TotalLength: uint16] [RFU: 1B] [first chunk]
```

- Bit 0 of `Flags` is set when the payload is encrypted; the app sets no other
  bit. `TotalLength` is the length of the whole payload.
- The first chunk is at most 12 bytes at MTU 23 (room minus the 4-byte blob
  header), later chunks fill whole packets (16 bytes).
- Sequence numbers start at 1 for each payload and count up per packet.
- The receiver takes the BlobStart sequence number as given and checks that
  each BlobStream/BlobComplete follows the previous one by exactly 1. It fails
  the blob unless the chunks add up to exactly `TotalLength`. Sequence numbers
  on Single packets are not checked.

What the lock does with the blob `RFU` byte or other flag bits is unknown
(untested on a lock).

### Layer 2: Command

```
[CommandId: 1B] [PayloadLength: 1B] [CommandRef: 1B] [RFU: 1B] [Payload: NB]
```

(app code, `communication/commands/Command.java`) `Command.serialize` refuses
a CommandRef outside 1-254. Which ref the app uses depends on the firmware
(`CommandStream.nextCommandRef`, `openStream`):

- Below firmware 4.7.90: every command carries the fixed ref 16.
- From 4.7.90: a counter that runs 1-127 and wraps back to 1.

The app matches an answer to its command on CommandRef alone, one command at a
time, and waits 320 ms after a matched answer before it releases the next
command (`CommandStream.CommandResponseDelay`). The response timeout is 20 s
(`NimlyEkeyDeviceBase.DefaultTimeout`). (app code)

### Layer 3: Response

```
[ResponseId: 1B] [Length: 1B] [CommandRef: 1B] [StatusId: 1B] [Payload: Length bytes]
```

(app code, `communication/responses/Response.java`) A response carries the id
of the command it answers. `Response.deserialize` reads exactly `Length`
payload bytes and ignores the rest, which is what makes a decrypted payload
with zero padding readable without stripping.

ResponseStatus (app code, `ResponseStatusId.java`). Anything but Success fails
the command, and so does a status byte the enum does not know:

| Byte | Status            |
| ---- | ----------------- |
| 0    | Success           |
| 1    | Failed            |
| 2    | NotAvailable      |
| 3    | InternalError     |
| 4    | ParameterError    |
| 5    | LengthError       |
| 6    | NotFoundError     |
| 7    | NoMatchError      |
| 8    | NotSupportedError |
| 9    | NotValidError     |
| 10   | SecurityError     |

### Events

The lock also sends two responses nobody asked for (app code,
`admin/devices/NimlyEkeyDevice.responseHandler`). They arrive with CommandRef
128 (0x80), which the counter never reaches, and the app reads them only when
the ref is 128. It never looks at their status byte.

| ResponseId | Name       | Payload                                                      |
| ---------- | ---------- | ------------------------------------------------------------ |
| 0x60       | LockStatus | slotNumber(uint16) + state(1B) + method(1B)                  |
| 0x14       | UserAdded  | slotNumber(uint16) + status(1B)                              |

LockStatus `state`: 1 = Locked, 2 = Unlocked. `method`: 0 = Key, 1 = Button,
2 = Panel (keypad), 3 = Fingerprint, 4 = RFID, 5 = Other. UserAdded `status`:
0 = NotAdded, 1 = PinCode, 2 = RfidCode, 3 = Fingerprint, 4 = SlotOccupied.
`state`, `method` and `status` are required enums: a value outside the list
fails the whole response in the app. (app code, `responses/lockstatus/`,
`responses/useradded/`)

## All BLE commands

Payload layouts are the `serializeCommand` methods in
`communication/commands/*/Command*.java` (app code). `-` means an empty
payload. Strings are ASCII.

| CommandId          | Hex  | Command                | Payload                                                     |
| ------------------ | ---- | ---------------------- | ----------------------------------------------------------- |
| ExchangeKeyPubM    | 0x01 | ECDH key exchange      | publicKey(64B)                                              |
| EkeyUserAuth       | 0x17 | Ekey (guest) auth      | userId(1B) + deviceId(6B) + publicKey(64B) + encToken(32B)  |
| EkeyOperate        | 0x18 | Lock/unlock            | operation(1B): 1 = unlock, 2 = lock, 3 = invalidate token   |
| EkeyUserAdd        | 0x1B | Add ekey user          | userName(12B, NUL-filled, max 11 chars) + publicKey (length not checked) |
| EkeyUserRemove     | 0x1C | Remove ekey user       | userId(1B)                                                  |
| EkeyUsersList      | 0x1D | List ekey users        | -                                                           |
| EkeyDeviceInfoGet  | 0x1F | Get device info blob   | -                                                           |
| EkeyDeviceInfoSet  | 0x20 | Set device info blob   | serverInfo (opaque bytes from the cloud)                    |
| UserAuthBegin      | 0x22 | Start owner auth       | userId(1B) + deviceId(6B)                                   |
| UserAuthFinalize   | 0x23 | Finish owner auth      | answer(16B), see [Owner authentication](#owner-authentication-challenge-response) |
| UserAuthUpdate     | 0x24 | Replace owner key      | userId(1B) + credentials(1B) + publicKey(64B)               |
| DeviceIdSet        | 0x30 | Set device ID          | deviceId(6B)                                                |
| DeviceIdGet        | 0x31 | Get device ID          | -                                                           |
| DeviceNameSet      | 0x32 | Set device name        | name(9B, NUL-filled, max 8 chars)                           |
| DeviceNameGet      | 0x33 | Get device name        | -                                                           |
| CurrentTimeGet     | 0x40 | Get time               | -                                                           |
| CurrentTimeSet     | 0x41 | Set time               | time(uint32), minutes since 2023-01-01 00:00 UTC            |
| ServerKeyUpdate    | 0x42 | Set server public key  | serverPublicKey(64B)                                        |
| DeviceLogGet       | 0x44 | Get device log         | -                                                           |
| PinCodeSet         | 0x52 | Set PIN code           | slotNumber(uint16) + pinLength(1B) + pincode(ASCII digits)  |
| PinCodeClear       | 0x53 | Clear PIN code         | slotNumber(uint16)                                          |
| RfidCodeClear      | 0x55 | Clear RFID tag         | slotNumber(uint16), 900-999                                 |
| ScanRfidCode       | 0x56 | Enroll RFID tag        | slotNumber(uint16), 900-999                                 |
| FingerprintScan    | 0x57 | Enroll fingerprint     | slotNumber(uint16), 150-199                                 |
| FingerprintClear   | 0x58 | Clear fingerprint      | slotNumber(uint16), 150-199                                 |
| VolumeSet          | 0x5A | Set sound volume       | volume(1B): 0 = off, 1 = low, 2 = normal                    |
| AutoLockSet        | 0x5B | Set auto-lock          | enabled(1B)                                                 |
| KeypadEnableSet    | 0x5C | Enable/disable keypad  | enabled(1B)                                                 |
| BattInfoGet        | 0x5D | Get battery info       | -                                                           |
| DeviceModelGet     | 0x62 | Get model              | -                                                           |
| FactoryResetModule | 0x70 | Factory reset module   | -                                                           |

Note the order around 0x55-0x58: RFID is 0x55 clear and 0x56 scan,
fingerprint is 0x57 scan and 0x58 clear. The slot range each command class
checks is what pins the pairing down (app code).

Response payloads (app code, `communication/responses/*/Response*.java`):

| Response          | Payload                                                          |
| ----------------- | ---------------------------------------------------------------- |
| ExchangeKeyPubL   | lockPublicKey(64B)                                               |
| UserAuthBegin     | challenge(16B)                                                   |
| UserAuthFinalize  | credentials(1B), not read by the app                             |
| UserAuthUpdate    | lockPublicKey(64B)                                               |
| ServerKeyUpdate   | lockPublicKey(64B)                                               |
| DeviceIdGet       | deviceId(6B)                                                     |
| DeviceNameGet     | name(9B, NUL-terminated)                                         |
| CurrentTimeGet    | time(uint32), same unit as CurrentTimeSet                        |
| DeviceLogGet      | length(1B) + log(length bytes); the app discards it              |
| BattInfoGet       | level(uint16) + lowBatteryFlag(1B, 1 = low) + percent(1B)        |
| DeviceModelGet    | model(1B), see [Lock models](#lock-models); unknown reads as 0   |
| FingerprintScan   | slotNumber(uint16) + lockStatus(1B)                              |
| ScanRfidCode      | slotNumber(uint16) + lockStatus(1B)                              |
| EkeyUserAdd       | userId(1B) + sessionPublicKey(64B) + tokenPublicKey(64B)         |
| EkeyUsersList     | count(1B) + count x [userId(1B) + name(12B)]                     |
| EkeyDeviceInfoGet | all remaining bytes, opaque                                      |

`lockStatus` in the scan answers: 0 = Ok, 1 = Error, 2 = UnknownCommand,
3 = CrcError, 4 = InvalidData, 5 = NoSpaceLeft, 6 = NoMatch; an unknown value
reads as null rather than failing. The unit of the battery `level`, the
meaning of the `credentials` byte and the content of the device log are not
traced.

## PIN code setting (0x52)

```
Payload: [slotNumber: uint16 LE] [pinLength: uint8] [pincode: ASCII bytes]

Example: set "8832" on slot 803, command payload only:
  23 03  04  38 38 33 32
  │      │   └──────────── "8832" as ASCII
  │      └──────────────── length 4
  └─────────────────────── slot 803 (little-endian: 0x0323)
```

Those seven bytes are what `CommandPincodeSet.serializeCommand` writes, not
the whole Layer 2 frame. With the header the command is:

```
52 07 <ref> 00  23 03 04 38 38 33 32
│  │  │     │   └──────────────────── payload as above
│  │  │     └──────────────────────── RFU
│  │  └────────────────────────────── CommandRef (16, or the 1-127 counter)
│  └───────────────────────────────── payload length 7
└──────────────────────────────────── PinCodeSet
```

These 11 bytes are then zero-padded to 16, encrypted with the link key and
sent as a two-packet blob. (app code; derived from the serializers, not
captured from a lock)

The app refuses to send a slot outside these ranges (checked client-side in
each command class, `VerifyExtensions.verifyRange`; app code):

| Credential  | BLE slots | Commands                                    |
| ----------- | --------- | ------------------------------------------- |
| PIN         | 800-899   | PinCodeSet, PinCodeClear                    |
| Fingerprint | 150-199   | FingerprintScan (0x57), FingerprintClear (0x58) |
| RFID        | 900-999   | ScanRfidCode (0x56), RfidCodeClear (0x55)   |

The RFID lower bound appears in the Java source as
`TypedValues.Custom.TYPE_INT`, an unrelated androidx constant that jadx
substituted because it has the same value, 900.

The master PIN is the one exception. `masterPincodeSet` sends PinCodeSet to
slot 0 with the range check switched off (`ignoreSlotNumberCheck`), and the
app offers it only on models with the Master PIN flag in the table below
(app code). Whether the lock accepts a PinCodeSet on any other slot outside
800-899 is untested on a lock.

Zigbee ZCL uses slots 0-999 with the master slots first (see
[slot-numbering.md](../slot-numbering.md)), so the two channels number
differently.

A PIN is 4-8 characters, digits 0-9 only (`PincodeMinLength`/
`PincodeMaxLength` in `Constants`, plus a digit check in `CommandPincodeSet`;
app code). The app's error message for a bad PIN quotes the PIN.

## Encryption

### Transport (ECDH + AES-128-CBC)

Every BLE connection sets up its own link key
(`devices/NimlyEkeyDeviceBase.java`):

1. App generates a **secp256r1 (NIST P-256)** key pair.
2. App sends its public key via `ExchangeKeyPubM` (0x01). On the wire a public
   key is X then Y, each 32 bytes little endian; a private key is the 32-byte
   scalar, little endian (`BigIntegerExtensions.toLittleEndianHex`, zero-filled
   to 32 bytes). (app code, JDK run)
3. Lock answers `ExchangeKeyPubL` with its public key in the same form.
4. App computes the raw ECDH secret (32 bytes) and **reverses its byte order**
   (`Secp256r1SecretExchanger.computeSecret`). (app code, JDK run)
5. **Link key** = reversed_secret[0:16], **link IV** = reversed_secret[16:32]
   (`getLinkKey`, `getLinkIv`). (app code, JDK run)
6. From then on every payload in both directions is AES-128-CBC with the link
   key and IV.

Nothing is encrypted before this. `PayloadStream` encrypts and decrypts only
once an encrypter is set, and the app sets it right after the lock's
`ExchangeKeyPubL` arrives, so both handshake messages travel in the clear. At
68 bytes each, they go as unencrypted blobs (flag 0). (app code)

How the cipher is applied (`crypto/encrypters/Aes128CbcEncrypter.java`,
constructed with `ivReset = false` in `NimlyEkeyDeviceBase`):

- The `Cipher` is `AES/CBC/NoPadding`, but `encrypt()` first fills the message
  with zero bytes up to a whole number of 16-byte blocks. An empty message
  encrypts to empty. `decrypt()` refuses a length that is not a multiple of 16
  and returns the padding with the plaintext; the Layer 2/3 length field says
  where the message ends. (app code, JDK run)
- Each message is its own CBC run starting from the link IV. The cipher is
  initialised once and `doFinal` resets it to the original IV on every call,
  so blocks chain within one message but not across messages; the same
  message sent twice gives the same ciphertext. (app code, JDK run)
- The whole Layer 2 command is encrypted in one call before it is cut into
  packets, and the whole reassembled payload is decrypted after it arrives.
  (app code)
- Once the encrypter is set, the app decrypts every incoming payload, whatever
  the packet type or blob flag says. (app code)

The class also has an `ivReset = true` mode that encrypts each 16-byte block
on its own from the original IV (ECB-like). Nothing in the app uses it: all
four places that construct `Aes128CbcEncrypter` pass `false`. (app code)

The shared secret is reversed, which only gives the same key on both sides if
both keep it at a fixed 32 bytes, leading zeros included. Python's
`cryptography` does, so our side is settled; whether the lock's own ECDH pads
the same way is not. The app depends on Conscrypt, Android's provider, doing
it: a stripped leading zero would put the app out of step with the lock about
one connection in 256, so the app working in the field is weak evidence that
both it and the lock pad.

`Constants` also defines `DefaultEncryptionKey` (`0x11` x 16) and
`DefaultEncryptionIv` (`0x22` x 16). Neither is a transport key. The first is
the factory owner key used in owner authentication below; the second is never
read anywhere in the app. (app code)

### Ekey authentication (token-based)

Used by ekey users, such as guests (`NimlyEkeyDevice.ekeyAuth`; app code):

1. App has userId, deviceId(6B), token(32B) and sessionPublicKey(64B) from the
   cloud API.
2. App generates a new ECDH key pair.
3. Computes the secret with sessionPublicKey (reversed, as above).
4. Encrypts the token with AES-128-CBC(key = secret[0:16], iv = link IV).
5. Sends `EkeyUserAuth` (0x17) with the new public key and the encrypted token.

### Owner authentication (challenge-response)

Where the owner key comes from, and whether the lock can be owned without the
cloud, is worked out in [ble-auth-provisioning.md](ble-auth-provisioning.md):
it is derived locally by an ECDH exchange (`UserAuthUpdate` 0x24), and a
factory-reset lock is enrolled with a hardcoded default key, so no cloud token
is needed to become owner.

Used by the lock owner (`NimlyEkeyDevice.userAuthenticate`, class `$27`; app
code):

1. App sends `UserAuthBegin` (0x22): userId(1B) + deviceId(6B).
2. Lock answers with a 16-byte challenge.
3. App decrypts it with AES-128-CBC(key = owner key, iv = link IV). The owner
   key is the 16-byte key from enrollment; on a factory-reset lock it is
   `0x11` x 16.
4. App **inverts all bits** of the decrypted challenge
   (`ByteExtensions.bitInverseArray`).
5. App encrypts the result again with the same key and IV.
6. App sends it in `UserAuthFinalize` (0x23).

Both messages also travel inside the link encryption, so the challenge is
encrypted twice on the wire. (app code; the owner-side arithmetic also JDK
run)

## Lock models

(app code, `responses/shared/LockModelId.java`; the three flags are the enum's
constructor arguments)

| Model           | Byte ID | Fingerprint | Keypad Enable | Master PIN |
| --------------- | ------- | ----------- | ------------- | ---------- |
| EasyFingerTouch | 8       | Yes         | No            | No         |
| EasyCodeTouch   | 9       | No          | No            | No         |
| NimlyCode       | 21      | No          | No            | No         |
| NimlyTouch      | 22      | No          | No            | No         |
| **NimlyPro**    | **23**  | **Yes**     | No            | No         |
| NimlyIndoor     | 24      | No          | No            | No         |
| NimlyKeybox     | 26      | No          | No            | No         |
| NimlyTwist      | 27      | No          | No            | No         |
| NimlyCode2      | 31      | No          | Yes           | Yes        |
| NimlyTouch2     | 32      | No          | Yes           | Yes        |
| **NimlyPro24**  | **33**  | **Yes**     | **Yes**       | **Yes**    |
| NimlyIndoor2    | 34      | No          | Yes           | Yes        |
| NimlyKeybox2    | 36      | No          | Yes           | Yes        |
| NimlyTwist2     | 37      | No          | Yes           | Yes        |

A model byte not in the list reads as Unknown (0), with no features.

Minimum firmware, as the app enforces it (app code, `Constants` and the
`feature()` methods in `NimlyEkeyDevice`):

- **4.6.0** to connect at all.
- **4.7.90** for DeviceModelGet, the CommandRef counter, and the admin
  operations PinCodeSet/Clear, master PIN, FingerprintScan/Clear,
  ScanRfidCode/RfidCodeClear, KeypadEnableSet, AutoLockSet, VolumeSet and
  BattInfoGet. Fingerprint, keypad and master PIN also need the model flag.
- Everything else (owner and ekey auth, EkeyOperate, device id and name, time,
  server key, device log, ekey users, factory reset) is offered on any
  firmware from 4.6.0.

These are the app's gates, and the library's Session applies the same ones
(`protocol/features.py`, see [ble-library.md](ble-library.md)). What older
firmware does with the commands is untested on a lock.

## BLE API (nimly ekey cloud)

This is a separate API from the one the Connect app uses (app code,
`nimly/ekey/api/`).

| Base URL                        | Environment |
| ------------------------------- | ----------- |
| `https://api.ekey.nimly.io`     | Production  |
| `https://dev.api.ekey.nimly.io` | Development |

Login is `POST /User/Login` (OAuth2 password grant).

| Method  | Path                                                      | Purpose                                  |
| ------- | --------------------------------------------------------- | ---------------------------------------- |
| POST    | `/User/Login`                                             | Login                                    |
| GET     | `/User`                                                   | User info                                |
| GET     | `/User/Locks`                                             | All locks                                |
| GET     | `/User/Locks/{id}`                                        | Specific lock                            |
| POST    | `/Locations/{locId}/Locks`                                | Create lock                              |
| GET/PUT | `/Locations/{locId}/Locks/{id}/DeviceData`                | Server public key / lock public key      |
| POST    | `/Locations/{locId}/Locks/{id}/Ekeys`                     | Create ekey                              |
| GET     | `/Locations/{locId}/Locks/{id}/Ekeys/{ekeyId}/DeviceData` | Ekey tokens/keys                         |
| POST    | `/Locations/{locId}/Locks/{id}/Credentials`               | Create credential                        |
| GET/PUT | `/Locations/{locId}/Locks/{id}/Credentials/{credId}`      | Manage credentials                       |
| POST    | `/EkeyDeviceInfo`                                         | Relay the lock's EkeyDeviceInfoGet blob  |
| GET     | `/EkeyDeviceInfo/{lockId}/Latest`                         | Latest synced state (battery percent)    |

On every owner connection `ConnectLockFragment` reads the lock's
`EkeyDeviceInfoGet` blob, posts it to `/EkeyDeviceInfo`, and writes the
cloud's answer back with `EkeyDeviceInfoSet` (app code, smali). What the blob
contains is not traced.

## Connection flow

(app code, `NimlyEkeyDeviceBase`, `BleConnection`)

```
1. BLE scan → find 0xFD00 service data
2. connectGatt(transport=LE)
3. Request MTU 23
4. Discover services
5. Request connection priority HIGH
6. Read Software Revision (firmware version, "major.minor.bugfix")
7. Check firmware ≥ 4.6.0
8. Enable notifications on ba4bfd03
9. ExchangeKeyPubM/L in the clear → link key and IV → AES-128-CBC from here
10. DeviceModelGet (firmware ≥ 4.7.90 only)
11. Authenticate (ekey auth OR owner auth)
12. Send commands (lock/unlock/pinSet/etc.)
```

## Scanning

(app code, `scanner/BleScanner.startScanning`, line 64-67) The app sets no
scan filter at all. It calls the one-argument
`BluetoothLeScanner.startScan(ScanCallback)`, so Android's defaults apply:
`SCAN_MODE_LOW_POWER`, `CALLBACK_TYPE_ALL_MATCHES`, legacy advertisements
only, 1M PHY. No `ScanFilter.Builder`, `ScanSettings.Builder`, `setLegacy` or
`setPhy` appears anywhere in the APK. Before scanning it requires the GPS
provider to be enabled (`verifyLocationEnabled`, line 38-43).

Everything is filtered in the callback. `NimlyEkeyDeviceScannerBase.onScanResult`
(line 60-74) runs every result past every device id the caller has set, and
`BleScanner.getNimlyEkeyScanResult` (line 75-104) drops the result unless
`scanRecord.getServiceData(0000fd00-0000-1000-8000-00805f9b34fb)` is non-null.
Nothing is matched on device name, address or manufacturer data; the one name
check in that method rewrites the display name `GlennI` to `Nimly` after the
result has already been accepted.

The two UI entry points differ only in which device ids they hand the scanner
(app code):

- `AddLockScannerFragment` (line 151-199) sets the single all-zero
  `Constants.DefaultDeviceId` and shows only results with
  `isInitialized == false`: a factory-reset lock.
- `ConnectLockScannerFragment` (smali, `refreshScan$1`, line 649) sets the
  device ids of the locks the account owns, from the cloud, and shows only
  `isInitialized == true`.

Both scan for exactly 10 seconds (`delay(10000)`, `0x2710` in the smali) and
then stop. There is no retry, no backoff and no timeout message: the user
presses "Scan" again. The only advice the app offers is the "How to activate
pairing mode" popup (`popup_module_setup_help.xml`), quoted under
[When the lock advertises](#when-the-lock-advertises).

A connection is always built from a live scan result:
`NimlyEkeyDeviceScanner.createDevice` passes
`scanResult.getScanResult().getDevice()` into `BleConnection`, and
`BleConnection.connect` calls `connectGatt(context, false, this, TRANSPORT_LE)`
with `autoConnect = false` (line 274). `BluetoothAdapter.getRemoteDevice` and
`createBond` are not called anywhere. The app therefore cannot reach a lock it
has not just seen advertise, and never bonds or whitelists one.

## When the lock advertises

The app assumes an enrolled lock advertises whenever it is scanned for: the
connect screen just scans for 10 seconds and expects to find it. Nothing in
the app code says under what conditions the lock actually does so
(app code, not answered).

The vendor documentation is the only source on that, and it ties advertising
to pairing mode. The app's own help popup
(`resources/res/layout/popup_module_setup_help.xml`, line 24):

> To activate pairing mode, remove and reinsert the batteries/power while the
> inside and outside unit are connected. The module will enter pairing mode
> for about four minutes (indicated by blue LED blinking for bluetooth or
> orange blinking for Zigbee 3.0).

And the Connect Module installation guide (`docs/manuals/`,
`EN-Connect-Module-Installation-Guide-231024`), for the same module:

> The module enters pairing mode automatically for four minutes, indicated by
> orange (zigbee) and blue (bluetooth) flashing from the module. Did you use
> too long to connect? To re-enter pairing mode, remove and reinsert the
> batteries/power while the units are connected.

Same Connect Module, one radio stack, two roles. Whether a module already
joined to a Zigbee network still advertises 0xFD00 outside that four-minute
window is not stated anywhere in the app, the manuals or the Nimly Connect
app, and no advertisement has been captured from a Zigbee-paired lock. The
Nimly Connect app never scans for locks over BLE at all: its only
`BluetoothLeScanner` use is the bundled Espressif provisioning library for the
Connect Gateway.

## Scan identification

(app code, `scanner/BleScanner.getNimlyEkeyScanResult`, line 77-99) The 0xFD00
service data is read as:

```
[seed: 2B] [identifier: 6B]
```

- Seed `00 00`: the lock is not enrolled. The identifier is an id of the lock's
  own, byte-reversed on the air. The app keeps it as the scan result's device
  id, but logs in to such a lock with the all-zero default device id.
- Any other seed: the lock is enrolled, and the identifier is the first 6
  bytes of SHA-1(seed || deviceId), with the device id set by `DeviceIdSet`
  during enrollment. The app recognises its own lock by computing that hash
  for each device id it knows. An enrolled lock never shows its device id.

No advertisement has been captured yet (untested on a lock). Scans from an
ESP32 proxy 50 cm from a Zigbee-paired NimlyPRO, from the Home Assistant host
and from a Shelly scanner, awake lock included, saw no 0xFD00 service data at
all. The layout above is what the app reads, so a capture would settle it; the
open question is whether that lock advertises in the first place.
