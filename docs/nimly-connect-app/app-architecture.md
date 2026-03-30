# Nimly/iotiliti — System Architecture

Basert på reverse engineering av `com.easyaccess.connect` v1.27.84.

## Oversikt

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
│            │ CAS Protocol (AES-kryptert)                │
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

## Apper

### nimly connect (`com.easyaccess.connect`)

- **Framework:** React Native (Hermes bytecode)
- **Formål:** Full låsadministrasjon via cloud
- **Kommunikasjon:** Phone → iotiliti cloud → Gateway → Lock
- **Auth:** OAuth2 password grant ELLER AWS Cognito
- **Ingen direkte BLE** til låsen

### nimly BLE (`easyaccess.ekey.app`)

- **Formål:** Direkte BLE-kommunikasjon med låsen
- **Kommunikasjon:** Phone → BLE → Lock (ingen cloud)
- **Brukes for:** Grunnleggende lock/unlock, oppsett
- **Ikke dekompilert ennå** — APK utilgjengelig via automatiserte verktøy

## White-label konfigurasjon

Samme kodebase, forskjellig branding og API-URL:

| Config-nøkkel             | Nimly             | Keyfree | Salus | Homely        | Forebygg | Tryg Smart |
| ------------------------- | ----------------- | ------- | ----- | ------------- | -------- | ---------- |
| Prod API URL              | prod-neutralclone | keyfree | salus | api.homely.no | forebygg | tryg       |
| Font                      | Stabil Grotesk    | -       | -     | Gilroy        | Futura   | 27Sans     |
| AMS                       | Ja                | Ja      | Nei   | Nei           | Nei      | Nei        |
| ARC (alarmsentral)        | Nei               | Nei     | Nei   | Nei           | Ja       | Nei        |
| Keychain                  | Ja                | Ja      | -     | -             | -        | -          |
| Safe Unlock               | Ja                | Ja      | Ja    | -             | -        | -          |
| Fingerprint events synlig | Nei               | -       | -     | -             | -        | -          |
| Safe Living (helse)       | Nei               | Nei     | Nei   | Nei           | Nei      | Nei        |
| Certified mode            | Nei               | Nei     | Nei   | Nei           | Nei      | Nei        |

> Komplett API-URL og client_secret oversikt: docs/nimly-connect-app/reversing-notes.md

## Støttede enhetstyper

```javascript
DoorlockTypes = {
  Yale: "yaledoorman",
  Danalock: "danalock",
  Easyaccess: "easyaccess", // EasyAccess/Nimly kodelås
  Easycode: "easycode", // Variant
  Idlock: "idlock", // ID Lock (norsk)
  Easyfinger: "easyfinger", // Med fingeravtrykk
  Iomodule: "iomodule", // I/O-modul
  Keybox: "keybox", // Nøkkelboks
  Dormakaba: "dormakaba", // Dormakaba-låser
};
```

## Tilgangstyper

| Type         | Beskrivelse          | Zigbee source      |
| ------------ | -------------------- | ------------------ |
| `pin`        | PIN-kode på keypad   | 0x02 (keypad)      |
| `finger`     | Fingeravtrykk        | 0x03 (fingerprint) |
| `tag`        | RFID/NFC-brikke      | 0x04 (rfid)        |
| `digitalKey` | Digital nøkkel i app | 0x00 (zigbee)      |
| `otp`        | Engangskode          | -                  |

## API-flyt for PIN-setting

```
1. Bruker åpner nimly connect-appen
2. App autentiserer mot iotiliti.cloud (OAuth2)
3. App henter enhetsliste: GET /devices
4. Bruker velger lås og klikker "Legg til kode"
5. App sender: POST /devices/{id}/access
   Body: { type: "pin", code: "8832", userId: "..." }
6. Cloud sender kommando til Gateway via CAS protocol
7. Gateway sender ZCL set_pin_code til låsen
8. Lås bekrefter → Gateway → Cloud → App
```

**Nøkkelinnsikt:** Steg 6-7 håndterer timing/wake automatisk — gatewayen venter til låsen poller og leverer kommandoen. Dette er hvorfor appen aldri har timeout-problemer, mens direkte ZHA-kall fra HA gjør det.

## CAS Protocol

Intern protokoll mellom cloud og gateway. AES-kryptert.

Feilkode-prefikser:

- `380xxx` — CAS systemfeil
- `380000` — OK
- `380041-380048` — Enhetsfeil (busy, failed, unsupported, no rights)
- `380106-380111` — Passordfeil
- `380125-380126` — Auth/tilkoblingsfeil

> Komplett CAS-feilkodetabell: docs/nimly-connect-app/reversing-notes.md

## Event-system

Doorlock-events rapporteres via:

1. **Zigbee attribute reports** (0x0100) — direkte fra lås til coordinator
2. **Cloud event-historikk** — `GET /devices/{id}/event-history`
3. **Cloud event stream** — `/v1/apps/{id}/eventstream` (sanntid)

Event-typer:

```
doorlock-settings-changed    — innstillinger endret
doorlock-access-created      — ny tilgang opprettet
doorlock-access-scan-requested — RFID-scan forespurt
doorlock-access-deleted      — tilgang slettet
doorlock-failed-to-lock      — låsing feilet
doorlock-access-updated      — tilgang oppdatert
```

> Zigbee-level event-format: docs/zigbee-protocol/zigbee-captures.md

## App-økosystem

### Connect-apper (cloud, via gateway)

Alle er white-label av `com.easyaccess.connect` (React Native/Hermes):

| Package                     | Navn           | Prod API                                                 | Merke            |
| --------------------------- | -------------- | -------------------------------------------------------- | ---------------- |
| `com.easyaccess.connect`    | nimly connect  | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | Nimly/EasyAccess |
| `com.safe4.keyfree`         | Keyfree        | `api.customer.keyfree.iotiliti.cloud`                    | Keyfree          |
| `com.salusprotekt.immunity` | Salus          | `api-salus.iotiliti.cloud`                               | Salus            |
| `se.forebygg.forebygg`      | Forebygg       | `api.customer.forebygg.iotiliti.cloud`                   | Forebygg         |
| `io.homely.home`            | Homely         | `api.homely.no`                                          | Homely           |
| `com.copiax.homesecurity`   | HomeSecurity   | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | Copiax           |
| `no.tekam.smarthus`         | Tekam Smarthus | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | Tekam            |
| `io.iotiliti.home`          | iotiliti       | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` | iotiliti (base)  |

### BLE-apper (direkte til lås)

| Package             | Navn            | API               | Merke         |
| ------------------- | --------------- | ----------------- | ------------- |
| easyaccess.ekey.app | nimly BLE       | api.ekey.nimly.io | Nimly         |
| no.safe4.easyaccess | Easy Access BLE | ukjent            | Safe4 (eldre) |

### Plattform-hierarki

```
Safe4 Security Group AS (morselskap)
  └── iotiliti (cloud-plattform, utviklet av Neurosys, Polen)
       ├── Nimly (norsk forbrukermerke)
       ├── EasyAccess (OEM/B2B)
       ├── Keyfree (norsk, Safe4-merke)
       ├── Salus Protect / Immunity (UK)
       ├── Homely (norsk smart hjem)
       ├── Forebygg (svensk sikkerhet)
       ├── Copiax / HomeSecurity (svensk)
       ├── Tekam Smarthus (norsk)
       ├── Folklarm / Appsolut Säkerhet (svensk)
       ├── Tryg Smart (norsk forsikring)
       ├── Safe4 Care / Confi.care (norsk helse)
       ├── LF (svensk, egen Keycloak-realm)
       └── Larmify (svensk)

Onesti Products AS (hardware)
  └── Alle fysiske låser + Connect Module (ZMNC010)
```

## Sikkerhetsnotater

- Client secrets hardkodet i APK (kan roteres server-side)
- Ingen certificate pinning observert
- Test-credentials tilgjengelige i koden
- AES-kryptering mellom gateway og lock (CAS)
- OAuth2 tokens lagres i AsyncStorage (Android)
