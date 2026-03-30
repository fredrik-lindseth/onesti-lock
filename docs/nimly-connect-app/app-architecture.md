# Nimly/iotiliti — System Architecture

Based on reverse engineering of `com.easyaccess.connect` v1.27.84.

## Overview

```
┌─────────────────────────────────────────────────────────┐
│                    iotiliti Cloud                        │
│  api-neutralclone.iotiliti.cloud (Nimly/EasyAccess)     │
│  api-keyfree.iotiliti.cloud (Keyfree)                   │
│  api-salus.iotiliti.cloud (Salus)                       │
│  api.homely.no (Homely)                                 │
│                                                         │
│  ┌──────────┐   ┌──────────┐  ┌────────────┐            │
│  │ OAuth2   │   │ Cognito  │  │ REST API   │            │
│  │ /oauth/  │   │ AWS      │  │ /devices/  │            │
│  │ v2/token │   │ eu-cen-1 │  │ /users/    │            │
│  └────┬─────┘   └────┬─────┘  │ /home/     │            │
│       │              │        │ /locations/│            │
│       └──────┬───────┘        │ /keybox/   │            │
│              │                └─────┬──────┘            │
│              ▼                      │                   │
│  ┌───────────────────┐              │                   │
│  │  Session Manager  │ ◄────────────┘                   │
│  └─────────┬─────────┘                                  │
│            │ CAS Protocol (AES-encrypted)               │
└────────────┼────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────┐
│  Connect Bridge      │  ← Zigbee Gateway (ZMNC010)
│  (nimly Gateway)     │
│  ZigBee Coordinator  │
└──────────┬───────────┘
           │ ZigBee 3.0 mesh
           ▼
┌──────────────────────┐  ┌──────────────────────┐
│  Nimly Touch Pro     │  │  EasyCodeTouch       │
│  (NimlyPRO)          │  │  (easyCodeTouch_v1)  │
│  EndDevice, battery  │  │  EndDevice, battery  │
│  DoorLock 0x0101     │  │  DoorLock 0x0101     │
└──────────────────────┘  └──────────────────────┘
```

## Apps

### nimly connect (`com.easyaccess.connect`)

- **Framework:** React Native (Hermes bytecode)
- **Purpose:** Full lock administration via cloud
- **Communication:** Phone → iotiliti cloud → Gateway → Lock
- **Auth:** OAuth2 password grant OR AWS Cognito
- **No direct BLE** to the lock

### nimly BLE (`easyaccess.ekey.app`)

- **Purpose:** Direct BLE communication with the lock
- **Communication:** Phone → BLE → Lock (no cloud)
- **Used for:** Basic lock/unlock, setup
- **Not yet decompiled** — APK unavailable via automated tools

## White-label configuration

Same codebase, different branding and API URL:

| Config key                | Nimly             | Keyfree | Salus | Homely        | Forebygg | Tryg Smart |
| ------------------------- | ----------------- | ------- | ----- | ------------- | -------- | ---------- |
| Prod API URL              | prod-neutralclone | keyfree | salus | api.homely.no | forebygg | tryg       |
| Font                      | Stabil Grotesk    | -       | -     | Gilroy        | Futura   | 27Sans     |
| AMS                       | Yes               | Yes     | No    | No            | No       | No         |
| ARC (alarm center)        | No                | No      | No    | No            | Yes      | No         |
| Keychain                  | Yes               | Yes     | -     | -             | -        | -          |
| Safe Unlock               | Yes               | Yes     | Yes   | -             | -        | -          |
| Fingerprint events visible | No               | -       | -     | -             | -        | -          |
| Safe Living (health)      | No                | No      | No    | No            | No       | No         |
| Certified mode            | No                | No      | No    | No            | No       | No         |

> Complete API URL and client_secret overview: docs/nimly-connect-app/reversing-notes.md

## Supported device types

```javascript
DoorlockTypes = {
  Yale: "yaledoorman",
  Danalock: "danalock",
  Easyaccess: "easyaccess", // EasyAccess/Nimly code lock
  Easycode: "easycode", // Variant
  Idlock: "idlock", // ID Lock (Norwegian)
  Easyfinger: "easyfinger", // With fingerprint
  Iomodule: "iomodule", // I/O module
  Keybox: "keybox", // Key box
  Dormakaba: "dormakaba", // Dormakaba locks
};
```

## Access types

| Type         | Description          | Zigbee source      |
| ------------ | -------------------- | ------------------ |
| `pin`        | PIN code on keypad   | 0x02 (keypad)      |
| `finger`     | Fingerprint          | 0x03 (fingerprint) |
| `tag`        | RFID/NFC tag         | 0x04 (rfid)        |
| `digitalKey` | Digital key in app   | 0x00 (zigbee)      |
| `otp`        | One-time code        | -                  |

## API flow for PIN setting

```
1. User opens the nimly connect app
2. App authenticates against iotiliti.cloud (OAuth2)
3. App fetches device list: GET /devices
4. User selects lock and clicks "Add code"
5. App sends: POST /devices/{id}/access
   Body: { type: "pin", code: "8832", userId: "..." }
6. Cloud sends command to Gateway via CAS protocol
7. Gateway sends ZCL set_pin_code to the lock
8. Lock confirms → Gateway → Cloud → App
```

**Key insight:** Steps 6-7 handle timing/wake automatically — the gateway waits until the lock polls and delivers the command. This is why the app never has timeout issues, while direct ZHA calls from HA do.

## CAS Protocol

Internal protocol between cloud and gateway. AES-encrypted.

Error code prefixes:

- `380xxx` — CAS system errors
- `380000` — OK
- `380041-380048` — Device errors (busy, failed, unsupported, no rights)
- `380106-380111` — Password errors
- `380125-380126` — Auth/connection errors

> Complete CAS error code table: docs/nimly-connect-app/reversing-notes.md

## Event system

Doorlock events are reported via:

1. **Zigbee attribute reports** (0x0100) — directly from lock to coordinator
2. **Cloud event history** — `GET /devices/{id}/event-history`
3. **Cloud event stream** — `/v1/apps/{id}/eventstream` (real-time)

Event types:

```
doorlock-settings-changed    — settings changed
doorlock-access-created      — new access created
doorlock-access-scan-requested — RFID scan requested
doorlock-access-deleted      — access deleted
doorlock-failed-to-lock      — locking failed
doorlock-access-updated      — access updated
```

> Zigbee-level event format: docs/zigbee-protocol/zigbee-captures.md

## App ecosystem

### Connect apps (cloud, via gateway)

All are white-labels of `com.easyaccess.connect` (React Native/Hermes):

| Package                     | Name           | Prod API                                                 | Brand            |
| --------------------------- | -------------- | -------------------------------------------------------- | ---------------- |
| `com.easyaccess.connect`    | nimly connect  | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | Nimly/EasyAccess |
| `com.safe4.keyfree`         | Keyfree        | `api.customer.keyfree.iotiliti.cloud`                    | Keyfree          |
| `com.salusprotekt.immunity` | Salus          | `api-salus.iotiliti.cloud`                               | Salus            |
| `se.forebygg.forebygg`      | Forebygg       | `api.customer.forebygg.iotiliti.cloud`                   | Forebygg         |
| `io.homely.home`            | Homely         | `api.homely.no`                                          | Homely           |
| `com.copiax.homesecurity`   | HomeSecurity   | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | Copiax           |
| `no.tekam.smarthus`         | Tekam Smarthus | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | Tekam            |
| `io.iotiliti.home`          | iotiliti       | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | iotiliti (base)  |

### BLE apps (direct to lock)

| Package             | Name            | API               | Brand         |
| ------------------- | --------------- | ----------------- | ------------- |
| easyaccess.ekey.app | nimly BLE       | api.ekey.nimly.io | Nimly         |
| no.safe4.easyaccess | Easy Access BLE | unknown           | Safe4 (older) |

### Platform hierarchy

```
Safe4 Security Group AS (parent company)
  └── iotiliti (cloud platform, developed by Neurosys, Poland)
       ├── Nimly (Norwegian consumer brand)
       ├── EasyAccess (OEM/B2B)
       ├── Keyfree (Norwegian, Safe4 brand)
       ├── Salus Protect / Immunity (UK)
       ├── Homely (Norwegian smart home)
       ├── Forebygg (Swedish security)
       ├── Copiax / HomeSecurity (Swedish)
       ├── Tekam Smarthus (Norwegian)
       ├── Folklarm / Appsolut Säkerhet (Swedish)
       ├── Tryg Smart (Norwegian insurance)
       ├── Safe4 Care / Confi.care (Norwegian health)
       ├── LF (Swedish, own Keycloak realm)
       └── Larmify (Swedish)

Onesti Products AS (hardware)
  └── All physical locks + Connect Module (ZMNC010)
```

## Security notes

- Client secrets hardcoded in APK (can be rotated server-side)
- No certificate pinning observed
- Test credentials accessible in the code
- AES encryption between gateway and lock (CAS)
- OAuth2 tokens stored in AsyncStorage (Android)
