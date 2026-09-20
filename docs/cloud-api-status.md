# Cloud API reversing: status and the road ahead

**Status, September 2026: parked.** The project's goal is full local
functionality without the vendor cloud or app ([feature-parity.md](feature-parity.md)),
and this track buys parity only by putting the cloud back in the path. It is
kept as a record of what was tried and what the API looks like, for anyone
who needs the cloud for their own reasons. The one part of it still worth
running is a capture of the *BLE* app's cloud (`api.ekey.nimly.io`, see
[nimly-ble-app/ble-protocol.md](nimly-ble-app/ble-protocol.md#ble-api-nimly-ekey-cloud)),
which would confirm the owner-key format the local enrollment derives, not
the Connect app's cloud described here.

## Goal, as it was

Recreate all functionality from the Nimly Connect app in Home Assistant: PIN
codes (set/change/delete) without Zigbee sleepy device issues, event history
with user identification, and lock/unlock via cloud as backup.

## What we have done

### 1. Decompiled the Nimly Connect app

APK `com.easyaccess.connect` v1.27.84, a React Native app with Hermes
bytecode that decompiled to 3.2M lines of JS. Found all API endpoints and the
auth flow. The full spec is in `docs/nimly-connect-app/iotiliti-api-spec.yaml`.
The "CAS protocol" the first pass thought it had found was the bundled Ezviz
camera SDK's error table, not a lock protocol (see the reversing notes).

### 2. Decompiled the seven other white-label apps

Keyfree, Salus, Forebygg, Homely, Copiax, Tekam and iotiliti all use an
identical codebase, only config varies. Found the new prod URL
`api.customer.prod-neutralclone.onesti.aws.neurosys.pro`, a Developer Options
menu, and LF's separate Keycloak realm. Full overview in
`docs/nimly-connect-app/reversing-notes.md`. Those seven decompilations were
not kept; only the Nimly Connect and Nimly BLE ones are in `reversing/`.

### 3. Wireshark capture of the Connect Bridge (hub)

Boot sequence is DNS → `boot-v2.onesti.io` → NTP → MQTT (port 8883). The MQTT
broker is `3.75.35.23` (AWS eu-central-1) with a self-signed cert. Software
stack: embedded Linux, Dropbear SSH 2020.81, OpenSSL 1.1.1+. Full writeup in
`docs/connect-bridge/hardware-gateway.md`.

### 4. Tested cloud API directly

OAuth2 auth works (`POST /oauth/v2/token`). `/locations` returns locations,
`/locations/{id}/users` returns users, `/users/me` returns the profile, and
`/devices/{id}` exists but requires a GUID. Auth and user data work.

### 5. Paired lock with hub

The lock was removed from ZHA and paired with the Connect Bridge. The app can
lock and unlock and shows the gateway plus the Touch Pro. PIN codes survive
re-pairing, since they are stored locally on the lock.

## What does not work

### group-devices returns `[]`

This is the main blocker. `GET /locations/{id}/group-devices` returns an empty
array even though the app shows devices (gateway + Touch Pro) under the same
location.

Tested with a fresh OAuth2 token, both location IDs (HusA and Hus), the old
URL (`api-neutralclone.iotiliti.cloud`), the new URL
(`api.customer.prod-neutralclone.onesti.aws.neurosys.pro`), and with and
without an `X-Company-Id` header. All return `[]`. The app uses the exact
same endpoint, verified in decompiled code. `X-Company-Id` was a guess and is
not what the app sends. Its request interceptor sets a header spelled
`companyId`, next to `Platform`, `Mobile-App-Version` and
`Mobile-App-Build-Number`, on every request. That exact spelling has not been
tried here, so the header is back on the list of things to test rather than
ruled out.

Possible causes:

- server-side access control we don't understand
- a claim or scope the app's token has and ours lacks
- something the app sets up during onboarding that grants device access
- devices tied to the gateway ID rather than the location ID
- a race condition where devices appear only after a polling cycle

### MITM of the app failed

We tried to see the actual HTTP traffic from the app:

| Method                     | Result                                                                  |
| -------------------------- | ----------------------------------------------------------------------- |
| mitmproxy + proxy on phone | App refuses (does not trust user CA, targetSdk=35)                      |
| apk-mitm (patch APK)       | Crashes: Ezviz SDK NullPointerException + NinePatch drawable corruption |
| apk-mitm --skip-patches    | Still crashes (NinePatch)                                               |
| PCAPdroid                  | Captures only hostnames/IPs, not URL paths (TLS)                        |
| React Native DevTools      | Release build, no debug port                                            |
| adb backup                 | App blocks backup (`allowBackup=false`)                                 |
| run-as                     | Package not debuggable                                                  |

## What the next person needs to do

### To crack group-devices

You need to see what the app actually sends: HTTP method, path, headers, body.
Choose one of these approaches.

**A) Android emulator with root (recommended).** Set up an x86_64 emulator
with Google APIs (**not** a Play Store image), which has root via `adb root`.
Install the mitmproxy CA as a system cert
(`adb push cert.pem /system/etc/security/cacerts/`), install the Nimly Connect
APK, set the proxy and capture all traffic. This is the easiest route and needs
no patching.

**B) Frida gadget injection.** Download `frida-gadget` for arm64 from GitHub
releases and use `objection patchapk` (needs an x64 machine for apktool, or
Docker). Pass `--skip-resources --ignore-nativelibs` to avoid the NinePatch
crash, then hook `OkHttp3` or `fetch` to log all requests. It works on a real
device and sees both request and response.

**C) Manual smali patching.** `apktool d` only the base APK (not the split
APKs), add a `networkSecurityConfig` that trusts user CAs, and **do not** patch
OkHttp or other classes. `apktool b`, sign, and install together with the
unmodified split APKs, which keeps clear of apk-mitm's destructive changes.

**D) Contact Onesti directly.** Email Onesti (contact info at
onestiproducts.io), ask about API documentation for integration partners, and
mention that we are building an open-source HA integration. That would give
official support with no reversing needed.

### To build cloud API integration in HA

Once you have the device ID (GUID):

```python
# PIN setting via cloud (bypasses Zigbee sleepy device)
POST /devices/{deviceId}/access
Authorization: Bearer <token>
{"type": "pin", "code": "1234", "userId": "..."}

# Event history
GET /devices/{deviceId}/event-history
Authorization: Bearer <token>

# Lock/unlock
POST /devices/{deviceId}/lock
Authorization: Bearer <token>
{"action": "lock"}  # or "unlock"
```

Such an integration would be a hybrid: ZHA for local control, cloud API for
PIN setting and event history. Note that we have since decided not to build a
second transport at all; see `docs/upstream-status.md` for the reasoning.

## Useful files

| File                                            | Contents                                          |
| ----------------------------------------------- | ------------------------------------------------- |
| `docs/nimly-connect-app/reversing-notes.md`     | Complete APK reversing                            |
| `docs/nimly-connect-app/iotiliti-api-spec.yaml` | OpenAPI spec (unverified)                         |
| `docs/nimly-connect-app/app-architecture.md`    | System architecture and white-label               |
| `docs/connect-bridge/hardware-gateway.md`       | Hub hardware and network analysis                 |
| `docs/slot-numbering.md`                        | Slot numbering uncertainty                        |
| `docs/debugging.md`                             | Debugging guide                                   |
| `secrets.md` (gitignored)                       | Client secrets, test credentials, the hub install code (the company ids are not secrets and stand in the spec header) |
| `reversing/`                                    | APK files and decompiled code                     |

## Timeline

- Decompiled Nimly Connect, found API endpoints
- Decompiled BLE app, documented ekey protocol
- Wireshark boot capture, paired lock with hub, tested cloud API, decompiled all white-label apps, MITM attempts failed, options flow UX improved
