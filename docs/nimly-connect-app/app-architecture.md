# Nimly/iotiliti: system architecture

From reverse engineering of `com.easyaccess.connect` v1.27.84.

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

nimly connect (`com.easyaccess.connect`) is a React Native app (Hermes
bytecode) for lock administration through the cloud. Commands go phone →
iotiliti cloud → gateway → lock; the app never talks BLE to the lock. It
authenticates with an OAuth2 password grant or AWS Cognito.

nimly BLE (`easyaccess.ekey.app`) talks BLE straight to the lock, no cloud in
the path, for basic lock/unlock and setup. Decompiled (v1.5.2) and documented
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

Nimly, Keyfree, Salus, Homely and Forebygg are read from the brand
configuration inside the v1.27.84 bundle, which carries every brand's
config. Tryg Smart is not in that bundle; it came from the newer apps
decompiled on 2026-03-30, which were not kept. The full API URL table is in
`docs/nimly-connect-app/reversing-notes.md`.

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

Steps 6 and 7 are presumably why the app never sees a timeout: a gateway on
the Zigbee network can hold the command until the sleepy lock polls, where a
ZHA call from HA gets one 7.68-second window. That is inferred from the app's
behaviour, not observed on the gateway. The MQTT payloads were never captured
(TLS), so what the cloud sends is unknown.

## Not a lock protocol: the "CAS" error codes

The bundle has a table of `CAS_*` error codes (380000 and up:
`CAS_MSG_PU_BUSY`, `CAS_PREVIEW_*`, `CAS_PTZ_*`, `CAS_TALK_*`,
`CAS_PLAYBACK_*`). Earlier versions of these docs took it for a
cloud-to-gateway or gateway-to-lock protocol. It is the Hik-Connect/Ezviz
camera SDK's error table (the app ships `com.ezviz` and `com.hikvision` for
camera support, and the same object holds Ezviz `TTS_*` and `ANALYZE_DATA_*`
codes). It says nothing about how the platform talks to the gateway or the
lock.

## Event system

Door lock events are reported three ways:

1. Zigbee attribute reports (0x0100), lock to coordinator
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

The Zigbee-level format is in `docs/zigbee-protocol/zigbee-captures.md`.

## App ecosystem

### Connect apps (cloud, via gateway)

All white-labels of `com.easyaccess.connect` (React Native/Hermes). The URLs
are what the newer builds decompiled on 2026-03-30 used; the v1.27.84 bundle
kept locally configures `api-<brand>.iotiliti.cloud` for every brand
([reversing-notes.md](reversing-notes.md#white-label-platform)):

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
       └── one tenant per brand, the table below

Onesti Products AS (hardware)
  └── All physical locks + Connect Module (ZMNC010)
```

### The tenant roster

Read out of the twelve Android builds kept on 2026-09-20 (listed in
[app-versions.md](app-versions.md)). Every build carries the whole family's
brand configuration, not just its own, so the roster can be read from any one
of them, and a brand appearing or disappearing between builds is dated by the
build it is in.

Three independent things in a build name a tenant, and the Evidence column says
which of them were found: **H** an API host (`api-<key>.iotiliti.cloud` or the
older `api.customer.<key>.iotiliti.cloud`), **T** theme assets (`logo-<key>`,
`bg-dashboard-<key>`, `arc-<key>`), **P** a support PDF folder
(`assets/pdf/support/<key>/`, only shipped by builds up to 1.22).

| Key | Brand | Country | Own app | Evidence | In builds | Host today |
| --- | ----- | ------- | ------- | -------- | --------- | ---------- |
| `easyaccess` | Nimly / EasyAccess | NO | `com.easyaccess.connect` | TP | all | via neutralclone |
| `iotiliti` | iotiliti (neutral) | - | `io.iotiliti.home` | TP | all | via neutralclone |
| `keyfree` | Keyfree (Safe4) | NO | `com.safe4.keyfree` | HTP | all | live |
| `homely` | Homely | NO | `io.homely.home` | HTP | all | live (`api.homely.no`) |
| `forebygg` | Förebygg | SE | `se.forebygg.forebygg` | HTP | all | live |
| `copiax` | Copiax / HomeSecurity | SE | `com.copiax.homesecurity` | TP | all | via neutralclone |
| `tekam` | Tekam Smarthus | NO | `no.tekam.smarthus` | TP | all | via neutralclone |
| `salus` | Salus Protect / Immunity | SE | `com.salusprotekt.immunity` | HT | 1.24 and up | live |
| `larmify` | Larmify | SE | `se.larmify.larmify` | T | 1.27 and up | via neutralclone |
| `conficare` | Confi.care | NO | see below | T | 1.25 and up | via neutralclone |
| `safe4care` | Safe4 Care | NO | none | H | 1.24 and up | live |
| `lf` | LF (Länsförsäkringar) | SE | none | H | 1.24 and up | live |
| `folklarm` | Folklarm / Appsolut Säkerhet | SE | `com.folklarm.appsolutsakerhet` | TP | up to 1.25 | via neutralclone |
| `tryg` | Tryg Smart | NO | `com.tryg.smart` | HTP | up to 1.27 | NXDOMAIN |
| `waoo` | Waoo Home Protect | DK | none | HTP | up to 1.24 | NXDOMAIN |
| `safely` | Safely | UK | `com.safelyteam.safely` | HTP | up to 1.25 | NXDOMAIN |
| `nearsens` | nearsens | NO | none | TP | up to 1.24 | domain dead |
| `eidsiva` | Eidsiva "Tett På" | NO | none | HTP | up to 1.22 | page 404 |
| `larmplus` | larmplus | SE | none | TP | up to 1.22 | domain dead |
| `assured` | Home Assurance (John Lewis) | UK | none | TP | 1.20 only | - |
| `neutralclone` | internal, the unbranded build | - | - | H | all | live |
| `neurosys` | internal, the developer's test tenant | - | - | H | 1.24 and up | test only |

Twenty brands, then, plus two internal keys, where the hierarchy above used to
list thirteen. The Host today column is a DNS lookup made on 2026-09-20, not
something read in the app: `api-tryg`, `api.tryg`, `api.customer.waoo`,
`api.safely` and their test hosts do not resolve, while `api-keyfree`,
`api-salus`, `api-lf` and `api-safe4care` do. So the roster shrinks, and the
tenants that left the code also left the platform.

`conficare` and `safely` are probably one brand renamed. Package
`com.safelyteam.safely`, recorded in app-versions.md as Confi.care, is branded
Safely in the 1.20.9 build we have: its icon is `logo_safely`, its support PDF
sends users to `safelyteam.co.uk`, and no `conficare` asset is in it. The
`conficare` theme key and `shop.confi.care` appear from 1.25 on, in builds that
carry no `safely` assets. `safelyteam.co.uk` is dead and `confi.care` is live.
That reads as a rename, but nothing in the code says so.

### Waoo, and what "a brand is in the code" means

Waoo is a Danish fibre ISP, part of Fibia P/S. In the app it is a full tenant,
not a leftover string. The Tekam 1.22.44 build gives it an API host
(`api.customer.waoo.iotiliti.cloud`, plus a test host), its own logo, dashboard
background and arc, its terms and privacy links
(`waoo.dk/kundeservice/vejledninger-og-vilkar/` and
`waoo.dk/om-waoo/persondataogcookies/`), and a support PDF in Danish and
English. That is exactly the set Tekam, Homely and Förebygg get in the same
build.

The PDF names the product: Waoo Home Protect, an alarm on a police-approved
central station, `protect@waoo.dk`, +45 44 16 16 16. It says nothing about a
door lock, and the lock is not mentioned anywhere in the Waoo-specific strings.

On the web there is nothing left. waoo.dk sells fibre, TV and telephony and has
no Home Protect page; the Wayback copies of waoo.dk from 2020 to 2023 only
carry an unrelated "Waoo Smart Home", Google Nest kit sold through L'EASY and
3C Retail, which is not this platform. The tenant host stopped resolving. Waoo
is last seen in a 1.24 build, so the product ran at some point and is gone.

Whether a Waoo customer could buy the lock is unanswered. Nothing found says
yes and nothing says no.

The other brands have not been checked the same way, and most of the countries
above come from the domain they link to rather than from a company register.
Two were checked and are worth writing down. Eidsiva's support PDF lists the
door lock as its own line, "Dørlås: Easy Access", so that bundle did include
the lock under the Easy Access name. Confi.care's site sells sensors, plugs and
an alarm watch for elderly care and no lock at all. Keyfree's own site presents
Keyfree as software on top of existing locks rather than a lock vendor.

None of this changes anything in the integration. It is business context for
who ships the same hardware, and a second argument for not building a cloud
transport: the tenant list churns.

## Security notes

- Client secrets hardcoded in the APK (can be rotated server-side)
- No certificate pinning observed
- Test credentials accessible in the code
- Cloud to gateway is MQTT over TLS 1.3 against a self-signed CA baked into
  the hub; gateway to lock is ordinary Zigbee 3.0
  ([hardware-gateway.md](../connect-bridge/hardware-gateway.md))
- OAuth2 tokens stored in AsyncStorage (Android)
