# Nimly BLE Protocol Reference

Dekompilert fra `easyaccess.ekey.app` v1.5.1 (native Android/Kotlin).
All kommunikasjon skjer over én BLE-karakteristikk.

## BLE UUIDs

| Formål                         | UUID                                   |
| ------------------------------ | -------------------------------------- |
| **Service**                    | `ba4bfd00-c447-19bf-f38d-4890b3a824c8` |
| **Kommunikasjon** (r/w/notify) | `ba4bfd03-c447-19bf-f38d-4890b3a824c8` |
| **Advertising** (16-bit)       | `0xFD00`                               |
| CCCD                           | `00002902-0000-1000-8000-00805f9b34fb` |
| Device Info Service            | `0000180a-0000-1000-8000-00805f9b34fb` |
| Software Revision              | `00002a28-0000-1000-8000-00805f9b34fb` |

## Pakkeformat

### Layer 1 — Packet

```
[PacketType: 1B] [Length: 1B] [RFU: 1B] [SeqNum: 1B] [Payload: NB]
```

PacketType:
| Byte | Type |
|------|------|
| 0x01 | Single (ukryptert) |
| 0x02 | SingleEncrypted |
| 0x03 | BlobStart (multi-packet start) |
| 0x04 | BlobStream (fortsettelse) |
| 0x05 | BlobComplete (slutt) |
| 0x06 | Ack |
| 0x07 | Nac |
| 0xF0 | Error |

### Layer 2 — Command

```
[CommandId: 1B] [PayloadLength: 1B] [CommandRef: 1B] [RFU: 1B] [Payload: NB]
```

### Layer 3 — Response

```
[ResponseId: 1B] [Length: 1B] [CommandRef: 1B] [StatusId: 1B] [Payload: NB]
```

ResponseStatus:
| Byte | Status |
|------|--------|
| 0 | Success |
| 1 | Failed |
| 2 | NotAvailable |
| 3 | InternalError |
| 4 | ParameterError |
| 5 | LengthError |
| 6 | NotFoundError |
| 7 | NoMatchError |
| 8 | NotSupportedError |
| 9 | NotValidError |
| 10 | SecurityError |

## Alle BLE-kommandoer

| CommandId          | Hex      | Kommando                 | Payload                                                 |
| ------------------ | -------- | ------------------------ | ------------------------------------------------------- |
| ExchangeKeyPubM    | 0x01     | ECDH nøkkelutveksling    | 64B public key                                          |
| EkeyUserAuth       | 0x17     | Ekey-autentisering       | userId(1B) + deviceId(6B) + pubKey(64B) + encToken(32B) |
| EkeyOperate        | 0x18     | Lås/opplås               | operationType(1B): 1=unlock, 2=lock, 3=invalidate       |
| EkeyUserAdd        | 0x1B     | Legg til ekey-bruker     | userName(12B) + publicKey                               |
| EkeyUserRemove     | 0x1C     | Fjern ekey-bruker        | userId                                                  |
| EkeyUsersList      | 0x1D     | List ekey-brukere        | —                                                       |
| EkeyDeviceInfoGet  | 0x1F     | Hent enhetsinfo          | —                                                       |
| EkeyDeviceInfoSet  | 0x20     | Sett enhetsinfo          | —                                                       |
| UserAuthBegin      | 0x22     | Start brukerauth         | userId(1B) + deviceId(6B)                               |
| UserAuthFinalize   | 0x23     | Fullfør brukerauth       | encryptedInvertedChallenge(16B)                         |
| UserAuthUpdate     | 0x24     | Oppdater brukerauth      | —                                                       |
| DeviceIdSet        | 0x30     | Sett enhets-ID           | —                                                       |
| DeviceIdGet        | 0x31     | Hent enhets-ID           | —                                                       |
| DeviceNameSet      | 0x32     | Sett enhetsnavn          | —                                                       |
| DeviceNameGet      | 0x33     | Hent enhetsnavn          | —                                                       |
| CurrentTimeGet     | 0x40     | Hent tid                 | —                                                       |
| CurrentTimeSet     | 0x41     | Sett tid                 | —                                                       |
| ServerKeyUpdate    | 0x42     | Oppdater servernøkkel    | —                                                       |
| DeviceLogGet       | 0x44     | Hent enhetslogg          | —                                                       |
| **PinCodeSet**     | **0x52** | **Sett PIN-kode**        | **slotNumber(2B LE) + pinLength(1B) + pincode(ASCII)**  |
| **PinCodeClear**   | **0x53** | **Fjern PIN-kode**       | **slotNumber(2B LE)**                                   |
| RfidCodeClear      | 0x55     | Fjern RFID-kode          | slotNumber                                              |
| ScanRfidCode       | 0x56     | Scan RFID                | —                                                       |
| FingerprintScan    | 0x57     | Scan fingeravtrykk       | —                                                       |
| FingerprintClear   | 0x58     | Fjern fingeravtrykk      | —                                                       |
| VolumeSet          | 0x5A     | Sett lydvolum            | volume(1B)                                              |
| AutoLockSet        | 0x5B     | Sett auto-lås            | enabled(1B)                                             |
| KeypadEnableSet    | 0x5C     | Aktiver/deaktiver keypad | enabled(1B)                                             |
| BattInfoGet        | 0x5D     | Hent batteriinfo         | —                                                       |
| DeviceModelGet     | 0x62     | Hent modell              | —                                                       |
| FactoryResetModule | 0x70     | Fabrikkresett modul      | —                                                       |

## PIN-kode setting (0x52)

```
Payload: [slotNumber: uint16 LE] [pinLength: uint8] [pincode: ASCII bytes]

Eksempel — sett "8832" på slot 803:
  23 03  04  38 38 33 32
  │      │   └──────────── "8832" som ASCII
  │      └──────────────── lengde 4
  └─────────────────────── slot 803 (little-endian: 0x0323)
```

**Slot-nummerering (BLE):**

- Slot 0: Master-PIN
- Slot 800-899: Vanlige bruker-PINer

**NB:** BLE bruker slot 800-899, mens Zigbee ZCL bruker slot 3-199. Forskjellig nummerering!

**Krav:** Firmware ≥ 4.7.90, PIN 4-8 siffer (0-9).

## Kryptering

### Transport (ECDH + AES-128-CBC)

Hver BLE-tilkobling:

1. App genererer **secp256r1 (NIST P-256)** nøkkelpar
2. App sender public key (64B) via `ExchangeKeyPubM` (0x01)
3. Lås svarer med sin public key (64B)
4. App beregner ECDH shared secret, **reverserer byte-rekkefølgen**
5. **Link Key** = shared_secret[0..16] (AES-nøkkel)
6. **Link IV** = shared_secret[16..32] (AES IV)
7. All videre trafikk: **AES-128-CBC** (ingen padding)

Default nøkler (før key exchange): `0x11 × 16` / `0x22 × 16`

### Ekey-autentisering (token-basert)

For ekey-brukere (gjester etc.):

1. App har: userId, deviceId(6B), token(32B), sessionPublicKey(64B) — fra cloud API
2. App genererer nytt ECDH-par
3. Beregner session secret med sessionPublicKey
4. Krypterer token med AES-128-CBC(sessionSecret[0..16], linkIv)
5. Sender `EkeyUserAuth` (0x17)

### Eier-autentisering (challenge-response)

For låseier:

1. App sender `UserAuthBegin` (0x22): userId(1B) + deviceId(6B)
2. Lås svarer med 16-byte kryptert challenge
3. App dekrypterer med brukerens nøkkel (`deviceEncryptionKey` fra cloud API)
4. App **inverterer alle bits** i challenge
5. App krypterer invertert challenge tilbake
6. App sender `UserAuthFinalize` (0x23)

## Låsmodeller

| Modell          | Byte ID | Fingeravtrykk | Keypad Enable | Master PIN |
| --------------- | ------- | ------------- | ------------- | ---------- |
| EasyFingerTouch | 8       | Ja            | Nei           | Nei        |
| EasyCodeTouch   | 9       | Nei           | Nei           | Nei        |
| NimlyCode       | 21      | Nei           | Nei           | Nei        |
| NimlyTouch      | 22      | Nei           | Nei           | Nei        |
| **NimlyPro**    | **23**  | **Ja**        | Nei           | Nei        |
| NimlyIndoor     | 24      | Nei           | Nei           | Nei        |
| NimlyKeybox     | 26      | Nei           | Nei           | Nei        |
| NimlyTwist      | 27      | Nei           | Nei           | Nei        |
| NimlyCode2      | 31      | Nei           | Ja            | Ja         |
| NimlyTouch2     | 32      | Nei           | Ja            | Ja         |
| **NimlyPro24**  | **33**  | **Ja**        | **Ja**        | **Ja**     |
| NimlyIndoor2    | 34      | Nei           | Ja            | Ja         |
| NimlyKeybox2    | 36      | Nei           | Ja            | Ja         |
| NimlyTwist2     | 37      | Nei           | Ja            | Ja         |

Minimum firmware: 4.6.0 (tilkobling), 4.7.90 (modelldeteksjon, PIN, keypad, master PIN).

## BLE API (nimly ekey cloud)

Separat API fra Connect-appen:

| Base URL                        | Miljø      |
| ------------------------------- | ---------- |
| `https://api.ekey.nimly.io`     | Produksjon |
| `https://dev.api.ekey.nimly.io` | Utvikling  |

Auth: `POST /User/Login` (OAuth2 password grant)

| Method  | Path                                                      | Formål                  |
| ------- | --------------------------------------------------------- | ----------------------- |
| POST    | `/User/Login`                                             | Innlogging              |
| GET     | `/User`                                                   | Brukerinfo              |
| GET     | `/User/Locks`                                             | Alle låser              |
| GET     | `/User/Locks/{id}`                                        | Spesifikk lås           |
| POST    | `/Locations/{locId}/Locks`                                | Opprett lås             |
| GET     | `/Locations/{locId}/Locks/{id}/DeviceData`                | Public keys             |
| POST    | `/Locations/{locId}/Locks/{id}/Ekeys`                     | Opprett ekey            |
| GET     | `/Locations/{locId}/Locks/{id}/Ekeys/{ekeyId}/DeviceData` | Ekey tokens/nøkler      |
| POST    | `/Locations/{locId}/Locks/{id}/Credentials`               | Opprett credential      |
| GET/PUT | `/Locations/{locId}/Locks/{id}/Credentials/{credId}`      | Administrer credentials |

## Tilkoblingsflyt

```
1. BLE scan → finn 0xFD00 service data
2. connectGatt(transport=LE)
3. Request MTU 23
4. Discover services
5. Request connection priority HIGH
6. Les Software Revision (firmware-versjon)
7. Sjekk firmware ≥ 4.6.0
8. Enable notifications på ba4bfd03
9. ECDH key exchange → AES-128-CBC link
10. Query device model (firmware ≥ 4.7.90)
11. Autentiser (ekey-auth ELLER user-auth)
12. Send kommandoer (lock/unlock/pinSet/etc.)
```

## Lock state respons

Lås-tilstand inkluderer opplåsingsmetode:
| Byte | Metode |
|------|--------|
| 0 | Key (nøkkel) |
| 1 | Button (knapp) |
| 2 | Panel (keypad) |
| 3 | Fingerprint |
| 4 | RFID |
| 5 | Other |

## Scan-identifisering

BLE advertisements inneholder 0xFD00 service data:

- 2-byte device ID seed
- 6-byte device ID (reversert) for uinitialiserte låser
- For initialiserte: 2-byte seed + 6-byte SHA-1 hash prefix (seed + kjent deviceId)
