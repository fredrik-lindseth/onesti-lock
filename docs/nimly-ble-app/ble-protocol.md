# Nimly BLE Protocol Reference

Decompiled from `easyaccess.ekey.app` v1.5.1 (native Android/Kotlin).
All communication happens over a single BLE characteristic.

## BLE UUIDs

| Purpose                        | UUID                                   |
| ------------------------------ | -------------------------------------- |
| **Service**                    | `ba4bfd00-c447-19bf-f38d-4890b3a824c8` |
| **Communication** (r/w/notify) | `ba4bfd03-c447-19bf-f38d-4890b3a824c8` |
| **Advertising** (16-bit)       | `0xFD00`                               |
| CCCD                           | `00002902-0000-1000-8000-00805f9b34fb` |
| Device Info Service            | `0000180a-0000-1000-8000-00805f9b34fb` |
| Software Revision              | `00002a28-0000-1000-8000-00805f9b34fb` |

## Packet format

### Layer 1 — Packet

```
[PacketType: 1B] [Length: 1B] [RFU: 1B] [SeqNum: 1B] [Payload: NB]
```

PacketType:

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

### Layer 2 — Command

```
[CommandId: 1B] [PayloadLength: 1B] [CommandRef: 1B] [RFU: 1B] [Payload: NB]
```

### Layer 3 — Response

```
[ResponseId: 1B] [Length: 1B] [CommandRef: 1B] [StatusId: 1B] [Payload: NB]
```

ResponseStatus:

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

## All BLE commands

| CommandId          | Hex      | Command                  | Payload                                                 |
| ------------------ | -------- | ------------------------ | ------------------------------------------------------- |
| ExchangeKeyPubM    | 0x01     | ECDH key exchange        | 64B public key                                          |
| EkeyUserAuth       | 0x17     | Ekey authentication      | userId(1B) + deviceId(6B) + pubKey(64B) + encToken(32B) |
| EkeyOperate        | 0x18     | Lock/unlock              | operationType(1B): 1=unlock, 2=lock, 3=invalidate       |
| EkeyUserAdd        | 0x1B     | Add ekey user            | userName(12B) + publicKey                               |
| EkeyUserRemove     | 0x1C     | Remove ekey user         | userId                                                  |
| EkeyUsersList      | 0x1D     | List ekey users          | —                                                       |
| EkeyDeviceInfoGet  | 0x1F     | Get device info          | —                                                       |
| EkeyDeviceInfoSet  | 0x20     | Set device info          | —                                                       |
| UserAuthBegin      | 0x22     | Start user auth          | userId(1B) + deviceId(6B)                               |
| UserAuthFinalize   | 0x23     | Finalize user auth       | encryptedInvertedChallenge(16B)                         |
| UserAuthUpdate     | 0x24     | Update user auth         | —                                                       |
| DeviceIdSet        | 0x30     | Set device ID            | —                                                       |
| DeviceIdGet        | 0x31     | Get device ID            | —                                                       |
| DeviceNameSet      | 0x32     | Set device name          | —                                                       |
| DeviceNameGet      | 0x33     | Get device name          | —                                                       |
| CurrentTimeGet     | 0x40     | Get time                 | —                                                       |
| CurrentTimeSet     | 0x41     | Set time                 | —                                                       |
| ServerKeyUpdate    | 0x42     | Update server key        | —                                                       |
| DeviceLogGet       | 0x44     | Get device log           | —                                                       |
| **PinCodeSet**     | **0x52** | **Set PIN code**         | **slotNumber(2B LE) + pinLength(1B) + pincode(ASCII)**  |
| **PinCodeClear**   | **0x53** | **Clear PIN code**       | **slotNumber(2B LE)**                                   |
| RfidCodeClear      | 0x55     | Clear RFID code          | slotNumber                                              |
| ScanRfidCode       | 0x56     | Scan RFID                | —                                                       |
| FingerprintScan    | 0x57     | Scan fingerprint         | —                                                       |
| FingerprintClear   | 0x58     | Clear fingerprint        | —                                                       |
| VolumeSet          | 0x5A     | Set sound volume         | volume(1B)                                              |
| AutoLockSet        | 0x5B     | Set auto-lock            | enabled(1B)                                             |
| KeypadEnableSet    | 0x5C     | Enable/disable keypad    | enabled(1B)                                             |
| BattInfoGet        | 0x5D     | Get battery info         | —                                                       |
| DeviceModelGet     | 0x62     | Get model                | —                                                       |
| FactoryResetModule | 0x70     | Factory reset module     | —                                                       |

## PIN code setting (0x52)

```
Payload: [slotNumber: uint16 LE] [pinLength: uint8] [pincode: ASCII bytes]

Example — set "8832" on slot 803:
  23 03  04  38 38 33 32
  │      │   └──────────── "8832" as ASCII
  │      └──────────────── length 4
  └─────────────────────── slot 803 (little-endian: 0x0323)
```

**Slot numbering (BLE):**

- Slot 0: Master PIN
- Slot 800-899: Regular user PINs

**Note:** BLE uses slots 800-899, while Zigbee ZCL uses slots 3-999. Different numbering!

**Requirements:** Firmware ≥ 4.7.90, PIN 4-8 digits (0-9).

## Encryption

### Transport (ECDH + AES-128-CBC)

Each BLE connection:

1. App generates **secp256r1 (NIST P-256)** key pair
2. App sends public key (64B) via `ExchangeKeyPubM` (0x01)
3. Lock responds with its public key (64B)
4. App computes ECDH shared secret, **reverses byte order**
5. **Link Key** = shared_secret[0..16] (AES key)
6. **Link IV** = shared_secret[16..32] (AES IV)
7. All further traffic: **AES-128-CBC** (no padding)

Default keys (before key exchange): `0x11 × 16` / `0x22 × 16`

### Ekey authentication (token-based)

For ekey users (guests etc.):

1. App has: userId, deviceId(6B), token(32B), sessionPublicKey(64B) — from cloud API
2. App generates new ECDH pair
3. Computes session secret with sessionPublicKey
4. Encrypts token with AES-128-CBC(sessionSecret[0..16], linkIv)
5. Sends `EkeyUserAuth` (0x17)

### Owner authentication (challenge-response)

For lock owner:

1. App sends `UserAuthBegin` (0x22): userId(1B) + deviceId(6B)
2. Lock responds with 16-byte encrypted challenge
3. App decrypts with user's key (`deviceEncryptionKey` from cloud API)
4. App **inverts all bits** in challenge
5. App encrypts inverted challenge back
6. App sends `UserAuthFinalize` (0x23)

## Lock models

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

Minimum firmware: 4.6.0 (connection), 4.7.90 (model detection, PIN, keypad, master PIN).

## BLE API (nimly ekey cloud)

Separate API from the Connect app:

| Base URL                        | Environment |
| ------------------------------- | ----------- |
| `https://api.ekey.nimly.io`     | Production  |
| `https://dev.api.ekey.nimly.io` | Development |

Auth: `POST /User/Login` (OAuth2 password grant)

| Method  | Path                                                      | Purpose              |
| ------- | --------------------------------------------------------- | -------------------- |
| POST    | `/User/Login`                                             | Login                |
| GET     | `/User`                                                   | User info            |
| GET     | `/User/Locks`                                             | All locks            |
| GET     | `/User/Locks/{id}`                                        | Specific lock        |
| POST    | `/Locations/{locId}/Locks`                                | Create lock          |
| GET     | `/Locations/{locId}/Locks/{id}/DeviceData`                | Public keys          |
| POST    | `/Locations/{locId}/Locks/{id}/Ekeys`                     | Create ekey          |
| GET     | `/Locations/{locId}/Locks/{id}/Ekeys/{ekeyId}/DeviceData` | Ekey tokens/keys     |
| POST    | `/Locations/{locId}/Locks/{id}/Credentials`               | Create credential    |
| GET/PUT | `/Locations/{locId}/Locks/{id}/Credentials/{credId}`      | Manage credentials   |

## Connection flow

```
1. BLE scan → finn 0xFD00 service data
2. connectGatt(transport=LE)
3. Request MTU 23
4. Discover services
5. Request connection priority HIGH
6. Read Software Revision (firmware version)
7. Check firmware ≥ 4.6.0
8. Enable notifications on ba4bfd03
9. ECDH key exchange → AES-128-CBC link
10. Query device model (firmware ≥ 4.7.90)
11. Authenticate (ekey-auth OR user-auth)
12. Send commands (lock/unlock/pinSet/etc.)
```

## Lock state response

Lock state includes unlock method:
| Byte | Method |
|------|--------|
| 0 | Key |
| 1 | Button |
| 2 | Panel (keypad) |
| 3 | Fingerprint |
| 4 | RFID |
| 5 | Other |

## Scan identification

BLE advertisements contain 0xFD00 service data:

- 2-byte device ID seed
- 6-byte device ID (reversed) for uninitialized locks
- For initialized locks: 2-byte seed + 6-byte SHA-1 hash prefix (seed + known deviceId)
