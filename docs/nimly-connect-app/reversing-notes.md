# Nimly Connect App — Reverse Engineering

APK: `com.easyaccess.connect` v1.27.84 (171 MB)
Framework: React Native with Hermes bytecode
Decompiled with: `jadx` + `hermes-dec` → 3.1M lines of JavaScript

## Architecture

The app **never communicates directly with the lock**. The communication path is:

```
Phone → Cloud API (iotiliti.cloud) → ZigBee Gateway (Connect Bridge) → Lock
         ↕ OAuth2/Cognito              ↕ CAS protocol (AES-encrypted)
```

No BLE communication found in this app (that is a separate app: `nimly BLE`).

## White-label platform

The app is a white-label from **iotiliti** (formerly NeutrAlClone). The same codebase is used by:

| Brand                | API URL                                                                                                   |
| -------------------- | --------------------------------------------------------------------------------------------------------- |
| **Nimly/EasyAccess** | `api-neutralclone.iotiliti.cloud` (older) / `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` (new) |
| Keyfree              | `api.customer.keyfree.iotiliti.cloud`                                                                     |
| Salus                | `api-salus.iotiliti.cloud`                                                                                |
| Forebygg             | `api.customer.forebygg.iotiliti.cloud`                                                                    |
| Homely               | `api.homely.no`                                                                                           |

Company IDs in `secrets.md` (gitignored).

## Authentication

### OAuth2 (primary)

```
POST /oauth/v2/token
{
  grant_type: "password",
  username: "<email>",
  password: "<password>",
  client_id: "account",
  client_secret: "<extracted-from-apk, see secrets.md>"
}

POST /oauth/v2/refresh-token
{
  grant_type: "refresh_token",
  refresh_token: "<token>",
  client_id: "account",
  client_secret: "<extracted-from-apk, see secrets.md>"
}
```

### AWS Cognito (alternative)

```
Region: eu-central-1
User Pool (prod): <extracted-from-apk, see secrets.md>
Client ID (prod): <extracted-from-apk, see secrets.md>
```

### Header

```
Authorization: Bearer <access_token>
```

## REST API — Door lock endpoints

| Method | Path                                      | Function                 |
| ------ | ----------------------------------------- | ------------------------ |
| POST   | `/devices/{id}/lock`                      | Lock the door            |
| POST   | `/devices/{id}/action`                    | General action           |
| PATCH  | `/devices/{id}/settings`                  | Change settings          |
| GET    | `/devices/{id}/access`                    | Get all users/codes      |
| POST   | `/devices/{id}/access`                    | **Create new PIN/code**  |
| PATCH  | `/devices/{id}/access`                    | Update access            |
| DELETE | `/devices/{id}/access`                    | Delete access            |
| GET    | `/devices/{id}/event-history`             | Event log                |
| POST   | `/devices`                                | Add device               |
| DELETE | `/devices/{id}`                           | Remove device            |
| PATCH  | `/devices/{id}`                           | Update device            |
| POST   | `/devices/{id}/keychain-lock`             | Lock via keychain        |
| PATCH  | `/devices/{id}/alarm-reaction`            | Change alarm reaction    |
| PATCH  | `/devices/{id}/alarm-profile`             | Change alarm profile     |
| POST   | `/devices/{id}/access/scan-tag`           | Scan RFID tag            |
| GET    | `/devices/{id}/features-history`          | Feature history          |
| PATCH  | `/devices/{id}/input-actions/{actionId}`  | Update input actions     |
| PATCH  | `/devices/{id}/output-actions/{actionId}` | Update output actions    |
| GET    | `/devices/{id}/demand`                    | Consumption values       |

### Keybox (crypto keys)

| Method | Path                                | Function            |
| ------ | ----------------------------------- | ------------------- |
| POST   | `/keybox/users/{userId}/keys`       | Create user key     |
| POST   | `/keybox/devices/{deviceId}/tokens` | Create device token |
| GET    | `/keybox/devices/{deviceId}/keys`   | Get device key      |

## Access types

```javascript
DeviceAccessMethodType = {
  Pin: "pin", // Code on keypad
  Tag: "tag", // RFID/NFC tag
  Otp: "otp", // One-time code
  DigitalKey: "digitalKey", // Digital key (app)
  Finger: "finger", // Fingerprint
};
```

## User model

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

## Lock types in the platform

```javascript
DoorlockTypes = {
  Yale: "yaledoorman",
  Danalock: "danalock",
  Easyaccess: "easyaccess",
  Easycode: "easycode",
  Idlock: "idlock",
  Easyfinger: "easyfinger",
  Iomodule: "iomodule",
  Keybox: "keybox",
  Dormakaba: "dormakaba",
};
```

> See also: docs/nimly-connect-app/app-architecture.md for complete DoorlockTypes reference.

## Lock modes

```javascript
DoorlockLockModeValues = {
  ManualLockAwayOff: "MANUAL_LOCK_AWAY_OFF",
  AutoLockAwayOff: "AUTO_LOCK_AWAY_OFF",
  ManualLockAwayOn: "MANUAL_LOCK_AWAY_ON",
  AutoLockAwayOn: "AUTO_LOCK_AWAY_ON",
};
```

## Event reporting

```javascript
DoorLockEventFeatureState = {
  AUTO_LOCK: "reportautolock",
  LOCKED: "reportlocked",
  EVENT: "reportevent",
  SECURE_SENSOR: "reportsecuresensor",
  LOW_BATTERY: "reportlowbat",
  UNKNOWN_CARD: "reportunknowncard",
  LOCK_STATE: "lockstate",
};
```

Doorlock events:

```
doorlock-settings-changed
doorlock-access-created
doorlock-access-scan-requested
doorlock-access-deleted
doorlock-failed-to-lock
doorlock-access-updated
```

> See also: docs/nimly-connect-app/app-architecture.md for cloud event system.

## CAS Protocol (Gateway ↔ Lock)

The gateway uses the "CAS" (Command and Status?) protocol with **AES encryption**:

Key error codes:
| Code | Name | Meaning |
|------|------|---------|
| 380000 | CAS*MSG_NO_ERROR | OK |
| 380001 | CAS_MSG_UNKNOW_ERROR | Unknown error |
| 380006 | CAS_MSG_COMMAND_UNKNOW | Unknown command |
| 380041 | CAS_MSG_PU_BUSY | Device busy |
| 380042 | CAS_MSG_OPERATION_FAILED | Operation failed |
| 380043 | CAS_PU_NO_CRYPTO_FOUND | Crypto key missing |
| 380047 | CAS_SYSTEM_COMMAND_PU_COMMAND_UNSUPPORTED | Command not supported |
| 380048 | CAS_SYSTEM_COMMAND_PU_NO_RIGHTS_TO_DO_COMMAND | Insufficient rights |
| 380106-380111 | CAS_PU_PASSWORD_UPDATE*\* | Password error |
| 380125 | CAS_PU_REFUSE_CLIENT_CONNECTION | Connection refused |
| 380126 | CAS_PLATFORM_CLIENT_VERIFY_AUTH_ERROR | Auth error |

## Configuration (Nimly-specific)

```javascript
{
    safeUnlockEnabled: true,
    amsServiceEnabled: true,
    showUserForFingerprintEvents: false,  // ← intentionally hidden!
    keypadAsAccessDeviceEnabled: true,
    installationPartnerCountryListEnabled: true,
    fontFamily: 'Stabil Grotesk'
}
```

## Implications for the integration

### PIN setting via cloud API

Instead of struggling with Zigbee sleepy device timeouts, we can potentially set PINs via REST API:

```
POST https://api-neutralclone.iotiliti.cloud/devices/{deviceId}/access
Authorization: Bearer <token>
{
    type: "pin",
    code: "8832",
    userId: "..."
}
```

This bypasses Zigbee entirely — the gateway handles timing.

### Event history

```
GET /devices/{deviceId}/event-history
```

Can provide complete event log with user info — better than Zigbee attribute reports.

### Prerequisites

- Requires Connect Bridge (gateway) — not just Connect Module
- Requires a Nimly account with an associated lock
- The API is not officially documented

## Tools

- `apkeep` — APK from Play Store
- `jadx` — Android APK → Java
- `hermes-dec` — React Native Hermes bytecode → JavaScript
- Source: `com.easyaccess.connect.xapk` v1.27.84

## Security observations

- Client secrets and API URLs are hardcoded in the app
- Test environment credentials are accessible
- Bug report credentials found in APK (see secrets.md)
- Sentry DSN exposed
- AWS Cognito pool IDs accessible
- No certificate pinning observed

## White-label decompilation (2026-03-30)

Decompiled all 7 white-label apps in the iotiliti ecosystem via `apkeep` + `hbc-decompiler`.
All use identical codebase (React Native/Hermes), only the config block varies.

### All API instances (prod)

| Brand          | Package                         | Prod API URL                                             |
| -------------- | ------------------------------- | -------------------------------------------------------- |
| **Nimly**      | `com.easyaccess.connect`        | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` |
| **Copiax**     | `com.copiax.homesecurity`       | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` |
| **Tekam**      | `no.tekam.smarthus`             | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` |
| **Folklarm**   | `com.folklarm.appsolutsakerhet` | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` |
| **iotiliti**   | `io.iotiliti.home`              | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` |
| **Keyfree**    | `com.safe4.keyfree`             | `api.customer.keyfree.iotiliti.cloud`                    |
| **Forebygg**   | `se.forebygg.forebygg`          | `api.customer.forebygg.iotiliti.cloud`                   |
| **Homely**     | `io.homely.home`                | `api.homely.no`                                          |
| **Safe4 Care** | _(in iotiliti app)_             | `api-safe4care.iotiliti.cloud`                           |
| **Tryg Smart** | _(in iotiliti app)_             | `api.tryg.iotiliti.cloud`                                |
| **Salus**      | `com.salusprotekt.immunity`     | `api-salus.iotiliti.cloud`                               |
| **LF**         | _(in iotiliti app)_             | `api-lf.iotiliti.cloud`                                  |

Client secrets, company IDs, and test credentials in `secrets.md` (gitignored).

### API URL migration

Nimly Connect v1.27.84 (our version) uses `api-neutralclone.iotiliti.cloud`.
Newer versions (from the iotiliti app) have migrated to `api.customer.prod-neutralclone.onesti.aws.neurosys.pro`.
Both URLs point to the same database — tested with a fresh token, identical responses.

### Internal test API

`https://test-api-neurosys.iotiliti.cloud` — Neurosys (Poland) internal test instance.
Client secret in `secrets.md`.

### Hidden Developer Options

All apps have a hidden "Developer Options" menu:

- Switch between Production / Test / Internal API
- Enable Instabug (error reporting)
- Copy Device Token (push notification token)
- Enable Error Reports
- Show app version and build number

### LF instance (separate auth)

The LF brand uses its own Keycloak realm: `realms/lftt-kong-oidc/protocol/openid-connect/token`.
External auth: `https://test-auth.lfhub.net`. Credentials in secrets.md.
Username login (not email), no password change, no account deletion.

### Finding: group-devices empty on all APIs

Tested `GET /locations/{id}/group-devices` with a fresh token against:

- `api-neutralclone.iotiliti.cloud` → `[]`
- `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` → `[]`

The app shows devices (gateway + touch pro), but the API returns an empty list.
Possible causes: server-side access control, caching, or the devices
are registered via a mechanism we have not reproduced via API.
