# Nimly Connect app: reverse engineering

XAPK `com.easyaccess.connect` v1.27.84 (161 MB), React Native with Hermes
bytecode. Decompiled with `jadx` + `hermes-dec` into 3.2M lines of JavaScript
(`reversing/nimly-connect-decompiled.js`, local and gitignored).

## Architecture

The app never talks to the lock directly. Everything goes through the cloud
and the gateway:

```
Phone → Cloud API (iotiliti.cloud) → ZigBee Gateway (Connect Bridge) → Lock
         ↕ OAuth2/Cognito              ↕ MQTT/TLS                ↕ Zigbee 3.0
```

There is no BLE code in this app. BLE lives in the separate `nimly BLE` app.

## White-label platform

The app is a white-label of iotiliti (formerly NeutrAlClone), and the same
codebase serves several brands. The v1.27.84 bundle carries every brand's
config, each with `API_URL`, `TEST_API_URL`, `INTERNAL_API_URL` and a client
secret per environment:

| Brand                | In the v1.27.84 bundle (verified)  | In the newer builds decompiled 2026-03-30 (not kept)     |
| -------------------- | ---------------------------------- | -------------------------------------------------------- |
| **Nimly/EasyAccess** | `api-neutralclone.iotiliti.cloud`  | `api.customer.prod-neutralclone.onesti.aws.neurosys.pro` |
| Keyfree              | `api-keyfree.iotiliti.cloud`       | `api.customer.keyfree.iotiliti.cloud`                    |
| Salus                | `api-salus.iotiliti.cloud`         | `api-salus.iotiliti.cloud`                               |
| Forebygg             | `api-forebygg.iotiliti.cloud`      | `api.customer.forebygg.iotiliti.cloud`                   |
| Homely               | `api.homely.no`                    | `api.homely.no`                                          |
| Safe4 Care           | `api-safe4care.iotiliti.cloud`     | `api-safe4care.iotiliti.cloud`                           |
| LF                   | `api-lf.iotiliti.cloud`            | `api-lf.iotiliti.cloud`                                  |
| Tryg Smart           | not present                        | `api.tryg.iotiliti.cloud`                                |

Test instances follow `test-api-<brand>.iotiliti.cloud`. The left column can
be re-checked with `grep` in the decompiled bundle; the right column rests on
the March notes, since those decompilations were not kept. For Nimly both
URLs were confirmed live and equivalent (see "API URL migration"); for
Keyfree and Forebygg the other URL has not been tested.

The right column is mislabelled as newer. The `api.customer.*` form in it is
the older scheme, so those March builds were behind v1.27.84, not ahead of it.
Their version numbers were not kept, so that is inferred from the host form
alone. See "API URL migration" below.

The company id per brand (a GUID: a `companyId` header on every request, a
body field on a few endpoints, and the predicate the app filters the location
list on) is in the header of `iotiliti-api-spec.yaml`, which also says why it
is not a secret.

## Authentication

OAuth2 is the primary route:

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

AWS Cognito is the alternative: region eu-central-1, prod user pool and
client ID extracted from the APK (see secrets.md). Requests carry
`Authorization: Bearer <access_token>`.

## REST API: door lock endpoints

| Method | Path                                      | Function                |
| ------ | ----------------------------------------- | ----------------------- |
| POST   | `/devices/{id}/lock`                      | Lock the door           |
| POST   | `/devices/{id}/action`                    | General action          |
| PATCH  | `/devices/{id}/settings`                  | Change settings         |
| GET    | `/devices/{id}/access`                    | Get all users/codes     |
| POST   | `/devices/{id}/access`                    | Create new PIN/code     |
| PATCH  | `/devices/{id}/access`                    | Update access           |
| DELETE | `/devices/{id}/access`                    | Delete access           |
| GET    | `/devices/{id}/event-history`             | Event log               |
| POST   | `/devices`                                | Add device              |
| DELETE | `/devices/{id}`                           | Remove device           |
| PATCH  | `/devices/{id}`                           | Update device           |
| POST   | `/devices/{id}/keychain-lock`             | Lock via keychain       |
| PATCH  | `/devices/{id}/alarm-reaction`            | Change alarm reaction   |
| PATCH  | `/devices/{id}/alarm-profile`             | Change alarm profile    |
| POST   | `/devices/{id}/access/scan-tag`           | Scan RFID tag           |
| GET    | `/devices/{id}/features-history`          | Feature history         |
| PATCH  | `/devices/{id}/input-actions/{actionId}`  | Update input actions    |
| PATCH  | `/devices/{id}/output-actions/{actionId}` | Update output actions   |
| GET    | `/devices/{id}/demand`                    | Consumption values      |

Keybox (crypto keys):

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

The `DoorlockTypes` enum (Yale, Danalock, Easyaccess, Easycode, Idlock,
Easyfinger, Iomodule, Keybox, Dormakaba) is in
[app-architecture.md](app-architecture.md#supported-device-types) with
per-type annotations.

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

The `doorlock-*` cloud event types are in
[app-architecture.md](app-architecture.md#event-system).

## The "CAS" error codes are the Ezviz camera SDK, not the lock

The bundle has a table of `CAS_*` error codes (380000 `CAS_MSG_NO_ERROR`,
380041 `CAS_MSG_PU_BUSY`, 380047
`CAS_SYSTEM_COMMAND_PU_COMMAND_UNSUPPORTED` and about a hundred more).
Earlier versions of these notes read it as a gateway protocol called CAS
with AES encryption. It is the error table of the Hik-Connect/Ezviz camera
SDK the app bundles for camera support: the same table carries
`CAS_PREVIEW_*`, `CAS_PTZ_*`, `CAS_TALK_*` and `CAS_PLAYBACK_*`, the
neighbouring objects are Ezviz `TTS_*` and `ANALYZE_DATA_*` codes, and the
decompiled sources contain `com/ezviz` and `com/hikvision`. The Ezviz SDK is
also what crashed `apk-mitm` (`cloud-api-status.md`). Nothing in it describes
the cloud-to-bridge or bridge-to-lock hops; what is known about those is in
`../connect-bridge/hardware-gateway.md`: MQTT over TLS to the cloud, Zigbee
3.0 to the lock.

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

The REST API could set PINs without the Zigbee sleepy-device timeouts, since
the gateway handles the timing:

```
POST https://api-neutralclone.iotiliti.cloud/devices/{deviceId}/access
Authorization: Bearer <token>
{
    type: "pin",
    code: "8832",
    userId: "..."
}
```

`GET /devices/{deviceId}/event-history` could give a full event log with user
info, more than the Zigbee attribute reports carry.

Prerequisites: a Connect Bridge (the Connect Module alone is not enough), a
Nimly account with the lock attached, and an API that is not officially
documented.

## Tools

`apkeep` (APK from Play Store), `jadx` (APK to Java), `hermes-dec` (Hermes
bytecode to JavaScript). Source: `com.easyaccess.connect.xapk` v1.27.84.

## Security observations

- Client secrets and API URLs hardcoded in the app
- Test environment credentials accessible
- Bug reporting goes through Instabug; whatever it carries was not copied out
- Sentry DSN exposed
- AWS Cognito pool IDs accessible
- No certificate pinning observed

What was copied into `secrets.md` (gitignored): the Nimly OAuth2 client
secret, the Cognito pool and client ids, and the built-in test login.
Nothing else was kept; the other brands' secrets are in the brand config
block of the decompiled bundle if ever needed.

## White-label decompilation (2026-03-30)

Seven white-label apps besides Nimly Connect were decompiled with `apkeep` +
`hbc-decompiler`: Keyfree, Salus, Forebygg, Homely, Copiax, Tekam and
iotiliti. One codebase (React Native/Hermes), only the config block differs.
Folklarm, Tryg Smart, Safe4 Care, LF and Larmify were found in those apps'
brand configuration; their own APKs, where they have one, were not
decompiled. None of the seven decompilations were kept, not even version
numbers, so the table below cannot be re-checked locally.
[app-versions.md](app-versions.md) is the baseline the next round compares
against, and says what to keep this time.

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

### API URL migration

Both hosts point to the same database: on 2026-03-30 a fresh token gave
identical responses from `api-neutralclone.iotiliti.cloud` and
`api.customer.prod-neutralclone.onesti.aws.neurosys.pro`, so both were live
then. That is the only measurement here.

The direction was read backwards until 2026-09-20. This note said the
`onesti.aws.neurosys.pro` form was the newer one, from the iotiliti build of
the day. Reading the host literals in thirteen builds shows the opposite:
`api.customer.*`, partly on `onesti.aws.neurosys.pro`, is the old scheme and
`api-*.iotiliti.cloud` the new one, rolled out brand by brand and done by
1.27.x. Nimly Connect v1.27.84 has no `onesti.aws.neurosys.pro` literal at all.
The table and the ordering are in
[app-versions.md](app-versions.md#the-api-host-scheme-read-across-thirteen-builds-2026-09-20).

### Internal test API

`https://test-api-neurosys.iotiliti.cloud` is Neurosys's internal test
instance (Poland), configured as `INTERNAL_API_URL` in the bundle. Its client
secret was not kept.

### Hidden Developer Options

Every app has a hidden "Developer Options" menu: switch between Production,
Test and Internal API, enable Instabug, copy the push device token, enable
error reports, show app version and build number.

### LF instance (separate auth)

LF uses its own Keycloak realm,
`realms/lftt-kong-oidc/protocol/openid-connect/token`, with external auth at
`https://test-auth.lfhub.net`. Credentials not kept. Users log in with a
username rather than an email, and cannot change their password or delete
their account.

### Finding: group-devices empty on all APIs

`GET /locations/{id}/group-devices` with a fresh token against
`api-neutralclone.iotiliti.cloud` and
`api.customer.prod-neutralclone.onesti.aws.neurosys.pro` both return `[]`,
while the app shows the gateway and the Touch Pro. Possible causes:
server-side access control, caching, or devices registered through a
mechanism we have not reproduced over the API. `cloud-api-status.md` has
what was tried.
