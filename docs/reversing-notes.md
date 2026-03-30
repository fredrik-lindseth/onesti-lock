# Nimly Connect App — Reverse Engineering

APK: `com.easyaccess.connect` v1.27.84 (171 MB)
Framework: React Native med Hermes bytecode
Dekompilert med: `jadx` + `hermes-dec` → 3.1M linjer JavaScript

## Arkitektur

Appen snakker **aldri direkte med låsen**. Kommunikasjonen er:

```
Phone → Cloud API (iotiliti.cloud) → ZigBee Gateway (Connect Bridge) → Lock
         ↕ OAuth2/Cognito              ↕ CAS protocol (AES-kryptert)
```

Ingen BLE-kommunikasjon funnet i denne appen (det er en separat app: `nimly BLE`).

## White-label plattform

Appen er en white-label fra **iotiliti** (tidligere NeutrAlClone). Samme kodebase brukes av:

| Merke | API URL | Company ID |
|-------|---------|------------|
| **Nimly/EasyAccess** | `api-neutralclone.iotiliti.cloud` | `90ded287-2356-4007-ac39-d3e1261afb59` |
| Keyfree | `api-keyfree.iotiliti.cloud` | `b960e7e6-02bd-490b-8c90-e6c428c45eea` |
| Salus | `api-salus.iotiliti.cloud` | `93bd9ef6-8bd0-4ad0-b045-5644fd62ef70` |
| Forebygg | `api-forebygg.iotiliti.cloud` | (i koden) |
| Homely | `api.homely.no` | `a21f32b6-4ac9-4c85-b97a-8b6ae565f37c` |

## Autentisering

### OAuth2 (primær)
```
POST /oauth/v2/token
{
  grant_type: "password",
  username: "<email>",
  password: "<password>",
  client_id: "account",
  client_secret: "55c78905-7601-48fa-b589-2d15c4ad60e7"
}

POST /oauth/v2/refresh-token
{
  grant_type: "refresh_token",
  refresh_token: "<token>",
  client_id: "account",
  client_secret: "55c78905-7601-48fa-b589-2d15c4ad60e7"
}
```

### AWS Cognito (alternativ)
```
Region: eu-central-1
User Pool (prod): eu-central-1_tpM2xORxr
Client ID (prod): 5hp9t37ltaqdrf9c5lb743ihj7
```

### Header
```
Authorization: Bearer <access_token>
```

## REST API — Dørlås-endepunkter

| Method | Path | Funksjon |
|--------|------|----------|
| POST | `/devices/{id}/lock` | Lås døren |
| POST | `/devices/{id}/action` | Generell handling |
| PATCH | `/devices/{id}/settings` | Endre innstillinger |
| GET | `/devices/{id}/access` | Hent alle brukere/koder |
| POST | `/devices/{id}/access` | **Opprett ny PIN/kode** |
| PATCH | `/devices/{id}/access` | Oppdater tilgang |
| DELETE | `/devices/{id}/access` | Slett tilgang |
| GET | `/devices/{id}/event-history` | Hendelseslogg |
| POST | `/devices` | Legg til enhet |
| DELETE | `/devices/{id}` | Fjern enhet |
| PATCH | `/devices/{id}` | Oppdater enhet |
| POST | `/devices/{id}/keychain-lock` | Lås via keychain |
| PATCH | `/devices/{id}/alarm-reaction` | Endre alarm-reaksjon |
| PATCH | `/devices/{id}/alarm-profile` | Endre alarm-profil |
| POST | `/devices/{id}/access/scan-tag` | Scan RFID-tag |
| GET | `/devices/{id}/features-history` | Feature-historikk |
| PATCH | `/devices/{id}/input-actions/{actionId}` | Oppdater input-actions |
| PATCH | `/devices/{id}/output-actions/{actionId}` | Oppdater output-actions |
| GET | `/devices/{id}/demand` | Forbruksverdier |

### Keybox (kryptonøkler)
| Method | Path | Funksjon |
|--------|------|----------|
| POST | `/keybox/users/{userId}/keys` | Opprett brukernøkkel |
| POST | `/keybox/devices/{deviceId}/tokens` | Opprett enhetstoken |
| GET | `/keybox/devices/{deviceId}/keys` | Hent enhetsnøkkel |

## Tilgangstyper

```javascript
DeviceAccessMethodType = {
    Pin: 'pin',        // Kode på keypad
    Tag: 'tag',        // RFID/NFC-brikke
    Otp: 'otp',        // Engangskode
    DigitalKey: 'digitalKey',  // Digital nøkkel (app)
    Finger: 'finger'   // Fingeravtrykk
}
```

## Brukermodell

```javascript
{
    id, firstName, lastName, email, phone, language,
    hasDoorlockAccess: false,
    hasAlarmPin: false,
    hasAlarmTag: false,
    hasDoorlockPin: false,
    hasDoorlockTag: false,
    hasDoorlockFingerprint: false,
    roles: null,
    active: true,
    keychainEnabled: false,
    hasLocations: false
}
```

## Låstyper i plattformen

```javascript
DoorlockTypes = {
    Yale: 'yaledoorman',
    Danalock: 'danalock',
    Easyaccess: 'easyaccess',
    Easycode: 'easycode',
    Idlock: 'idlock',
    Easyfinger: 'easyfinger',
    Iomodule: 'iomodule',
    Keybox: 'keybox',
    Dormakaba: 'dormakaba'
}
```

> Se også: docs/app-architecture.md for komplett DoorlockTypes-referanse.

## Låsmodus

```javascript
DoorlockLockModeValues = {
    ManualLockAwayOff: 'MANUAL_LOCK_AWAY_OFF',
    AutoLockAwayOff: 'AUTO_LOCK_AWAY_OFF',
    ManualLockAwayOn: 'MANUAL_LOCK_AWAY_ON',
    AutoLockAwayOn: 'AUTO_LOCK_AWAY_ON'
}
```

## Event-rapportering

```javascript
DoorLockEventFeatureState = {
    AUTO_LOCK: 'reportautolock',
    LOCKED: 'reportlocked',
    EVENT: 'reportevent',
    SECURE_SENSOR: 'reportsecuresensor',
    LOW_BATTERY: 'reportlowbat',
    UNKNOWN_CARD: 'reportunknowncard',
    LOCK_STATE: 'lockstate'
}
```

Doorlock-events:
```
doorlock-settings-changed
doorlock-access-created
doorlock-access-scan-requested
doorlock-access-deleted
doorlock-failed-to-lock
doorlock-access-updated
```

> Se også: docs/app-architecture.md for cloud event-system.

## CAS Protocol (Gateway ↔ Lock)

Gatewayen bruker "CAS" (Command and Status?) protokoll med **AES-kryptering**:

Nøkkelfeilkoder:
| Kode | Navn | Betydning |
|------|------|-----------|
| 380000 | CAS_MSG_NO_ERROR | OK |
| 380001 | CAS_MSG_UNKNOW_ERROR | Ukjent feil |
| 380006 | CAS_MSG_COMMAND_UNKNOW | Ukjent kommando |
| 380041 | CAS_MSG_PU_BUSY | Enhet opptatt |
| 380042 | CAS_MSG_OPERATION_FAILED | Operasjon feilet |
| 380043 | CAS_PU_NO_CRYPTO_FOUND | Kryptonøkkel mangler |
| 380047 | CAS_SYSTEM_COMMAND_PU_COMMAND_UNSUPPORTED | Kommando ikke støttet |
| 380048 | CAS_SYSTEM_COMMAND_PU_NO_RIGHTS_TO_DO_COMMAND | Manglende rettigheter |
| 380106-380111 | CAS_PU_PASSWORD_UPDATE_* | Passordfeil |
| 380125 | CAS_PU_REFUSE_CLIENT_CONNECTION | Tilkobling avvist |
| 380126 | CAS_PLATFORM_CLIENT_VERIFY_AUTH_ERROR | Auth-feil |

## Konfigurasjon (Nimly-spesifikt)

```javascript
{
    safeUnlockEnabled: true,
    amsServiceEnabled: true,
    showUserForFingerprintEvents: false,  // ← bevisst skjult!
    keypadAsAccessDeviceEnabled: true,
    installationPartnerCountryListEnabled: true,
    fontFamily: 'Stabil Grotesk'
}
```

## Implikasjoner for integrasjonen

### PIN-setting via cloud API
I stedet for å slite med Zigbee sleepy device timeout, kan vi potensielt sette PIN via REST API:
```
POST https://api-neutralclone.iotiliti.cloud/devices/{deviceId}/access
Authorization: Bearer <token>
{
    type: "pin",
    code: "1112",
    userId: "..."
}
```
Dette omgår Zigbee helt — gatewayen håndterer timing.

### Event-historikk
```
GET /devices/{deviceId}/event-history
```
Kan gi komplett hendelseslogg med brukerinfo — bedre enn Zigbee attribute reports.

### Forutsetninger
- Krever Connect Bridge (gateway) — ikke bare Connect Module
- Krever Nimly-konto med tilknyttet lås
- API-et er ikke offisielt dokumentert

## Verktøy

- `apkeep` — APK fra Play Store
- `jadx` — Android APK → Java
- `hermes-dec` — React Native Hermes bytecode → JavaScript
- Kilde: `com.easyaccess.connect.xapk` v1.27.84

## Sikkerhetsobservasjoner

- Client secrets og API-URLer er hardkodet i appen
- Test-miljø credentials er tilgjengelige
- Bug report credentials funnet: `Onesti-Tester / 011255Tester`
- Sentry DSN eksponert
- AWS Cognito pool IDs tilgjengelige
- Ingen certificate pinning observert
