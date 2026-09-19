# Nimly/iotiliti: system architecture

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
│            │ MQTT over TLS 1.3, port 8883               │
└────────────┼────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────┐
│  Connect Bridge      │  ← Zigbee gateway (Squid.link 2B, MGW211)
│  (nimly Gateway)     │
│  ZigBee Coordinator  │
└──────────┬───────────┘
           │ ZigBee 3.0, ZCL Door Lock cluster
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

A React Native app (Hermes bytecode) for full lock administration through the
cloud. Commands go phone → iotiliti cloud → gateway → lock, and the app never
talks BLE to the lock. It authenticates with either an OAuth2 password grant or
AWS Cognito.

### nimly BLE (`easyaccess.ekey.app`)

Talks BLE directly to the lock, with no cloud in the path (phone → BLE → lock).
It is used for basic lock/unlock and setup. Decompiled (v1.5.2) and documented
in [ble-protocol.md](../nimly-ble-app/ble-protocol.md).

## White-label configuration

Same codebase, different branding and API URL:

| Config key                 | Nimly             | Keyfree | Salus | Homely        | Forebygg | Tryg Smart |
| -------------------------- | ----------------- | ------- | ----- | ------------- | -------- | ---------- |
| Prod API URL               | prod-neutralclone | keyfree | salus | api.homely.no | forebygg | tryg       |
| Font                       | Stabil Grotesk    | -       | -     | Gilroy        | Futura   | 27Sans     |
| AMS                        | Yes               | Yes     | No    | No            | No       | No         |
| ARC (alarm center)         | No                | No      | No    | No            | Yes      | No         |
| Keychain                   | Yes               | Yes     | -     | -             | -        | -          |
| Safe Unlock                | Yes               | Yes     | Yes   | -             | -        | -          |
| Fingerprint events visible | No                | -       | -     | -             | -        | -          |
| Safe Living (health)       | No                | No      | No    | No            | No       | No         |
| Certified mode             | No                | No      | No    | No            | No       | No         |

The Nimly, Keyfree, Salus, Homely and Forebygg columns are read from the brand
configuration inside the `com.easyaccess.connect` v1.27.84 bundle, which
carries every brand's config. The Tryg Smart column is not in that bundle; it
came from the newer apps decompiled on 2026-03-30, which were not kept.

> Complete API URL overview: docs/nimly-connect-app/reversing-notes.md

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

| Type         | Description        | Zigbee source      |
| ------------ | ------------------ | ------------------ |
| `pin`        | PIN code on keypad | 0x02 (keypad)      |
| `finger`     | Fingerprint        | 0x03 (fingerprint) |
| `tag`        | RFID/NFC tag       | 0x04 (rfid)        |
| `digitalKey` | Digital key in app | 0x00 (zigbee)      |
| `otp`        | One-time code      | -                  |

## API flow for PIN setting

```
1. User opens the nimly connect app
2. App authenticates against iotiliti.cloud (OAuth2)
3. App fetches device list: GET /devices
4. User selects lock and clicks "Add code"
5. App sends: POST /devices/{id}/access
   Body: { type: "pin", code: "8832", userId: "..." }
6. Cloud sends the command to the gateway over MQTT
7. Gateway sends ZCL set_pin_code to the lock
8. Lock confirms → Gateway → Cloud → App
```

Steps 6 and 7 are presumably why the app has no timeout problems: a gateway
that sits on the Zigbee network can hold the command until the sleepy lock
polls, where a ZHA call from HA gets one 7.68-second window. That is an
inference from the app's behaviour, not something observed on the gateway.
The MQTT payloads were not captured (TLS), so what the cloud actually sends is
unknown.

## Not a lock protocol: the "CAS" error codes

The bundle contains a table of `CAS_*` error codes (380000 and up:
`CAS_MSG_PU_BUSY`, `CAS_PREVIEW_*`, `CAS_PTZ_*`, `CAS_TALK_*`, `CAS_PLAYBACK_*`
and so on). Earlier versions of these docs took it for a cloud-to-gateway or
gateway-to-lock protocol. It is not: the codes are the Hik-Connect/Ezviz camera
SDK's error table (the app ships `com.ezviz` and `com.hikvision` for its camera
support, and the same object holds Ezviz `TTS_*` and `ANALYZE_DATA_*` codes).
They say nothing about how the lock platform talks to the gateway or the lock.

## Event system

Door lock events are reported three ways:

1. Zigbee attribute reports (0x0100), directly from lock to coordinator
2. Cloud event history: `GET /devices/{id}/event-history`
3. Cloud event stream: `/v1/apps/{id}/eventstream` (real-time)

Event types:

```
doorlock-settings-changed       settings changed
doorlock-access-created         new access created
doorlock-access-scan-requested  RFID scan requested
doorlock-access-deleted         access deleted
doorlock-failed-to-lock         locking failed
doorlock-access-updated         access updated
```

> Zigbee-level event format: docs/zigbee-protocol/zigbee-captures.md

## App ecosystem

### Connect apps (cloud, via gateway)

All are white-labels of `com.easyaccess.connect` (React Native/Hermes). The
URLs are what the newer builds decompiled on 2026-03-30 used; the v1.27.84
bundle kept locally configures `api-<brand>.iotiliti.cloud` for every brand
(details in [reversing-notes.md](reversing-notes.md#white-label-platform)):

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
- No certificate pinning observed in the app
- Test credentials accessible in the code
- Cloud to gateway is MQTT over TLS 1.3 against a self-signed CA baked into
  the hub; gateway to lock is ordinary Zigbee 3.0 (see
  [hardware-gateway.md](../connect-bridge/hardware-gateway.md))
- OAuth2 tokens stored in AsyncStorage (Android)
