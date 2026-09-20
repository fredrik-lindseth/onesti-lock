# Cloud API reversing: status and the road ahead

Status, September 2026: parked. The project's goal is full local
functionality without the vendor cloud or app
([feature-parity.md](feature-parity.md)), and this track only buys parity by
putting the cloud back in the path. It is kept as a record of what was tried
and what the API looks like, for anyone who needs the cloud for their own
reasons. The one part still worth running is a capture of the BLE app's cloud
(`api.ekey.nimly.io`, see
[nimly-ble-app/ble-protocol.md](nimly-ble-app/ble-protocol.md#ble-api-nimly-ekey-cloud)),
which would confirm the owner-key format the local enrollment derives. That
is not the Connect app's cloud described here.

## Goal, as it was

Recreate the Nimly Connect app in Home Assistant: PIN codes without the
Zigbee sleepy-device problem, event history with user identification, and
lock/unlock via cloud as backup.

## What was done

1. Decompiled the Nimly Connect app. APK `com.easyaccess.connect` v1.27.84,
   React Native with Hermes bytecode, 3.2M lines of JS. All API endpoints and
   the auth flow are in `docs/nimly-connect-app/iotiliti-api-spec.yaml`. The
   "CAS protocol" the first pass thought it had found was the bundled Ezviz
   camera SDK's error table (see the reversing notes).
2. Decompiled the seven other white-label apps: Keyfree, Salus, Forebygg,
   Homely, Copiax, Tekam and iotiliti. Identical codebase, only config
   differs. Found the new prod URL
   `api.customer.prod-neutralclone.onesti.aws.neurosys.pro`, a Developer
   Options menu, and LF's separate Keycloak realm
   (`docs/nimly-connect-app/reversing-notes.md`). Those seven decompilations
   were not kept; only Nimly Connect and Nimly BLE are in `reversing/`.
3. Wireshark capture of the Connect Bridge boot: DNS → `boot-v2.onesti.io` →
   NTP → MQTT on 8883. Broker `3.75.35.23` (AWS eu-central-1), self-signed
   cert. Embedded Linux, Dropbear SSH 2020.81, OpenSSL 1.1.1+. Full writeup in
   `docs/connect-bridge/hardware-gateway.md`.
4. Tested the cloud API directly. OAuth2 works (`POST /oauth/v2/token`).
   `/locations` returns locations, `/locations/{id}/users` users,
   `/users/me` the profile, and `/devices/{id}` exists but needs a GUID.
5. Paired the lock with the hub. Removed from ZHA, paired with the Connect
   Bridge; the app locks and unlocks and shows the gateway plus the Touch
   Pro. PIN codes survived re-pairing, since they live on the lock.

## What does not work

### group-devices returns `[]`

The main blocker. `GET /locations/{id}/group-devices` returns an empty array
while the app shows devices (gateway + Touch Pro) under the same location.

Tried with a fresh OAuth2 token, both location IDs (HusA and Hus), the old
URL (`api-neutralclone.iotiliti.cloud`), the new one
(`api.customer.prod-neutralclone.onesti.aws.neurosys.pro`), with and without
an `X-Company-Id` header. All `[]`. The app uses the same endpoint, verified
in decompiled code. `X-Company-Id` was a guess: the app's request interceptor
sets a header spelled `companyId`, next to `Platform`, `Mobile-App-Version`
and `Mobile-App-Build-Number`, on every request. That spelling has not been
tried, so the header is back on the list rather than ruled out.

Other possible causes: server-side access control we do not understand, a
claim or scope the app's token has and ours lacks, something the app sets up
during onboarding, devices tied to the gateway ID rather than the location
ID, or devices appearing only after a polling cycle.

### MITM of the app failed

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

See what the app sends: method, path, headers, body. Four ways.

A) Android emulator with root, the easiest. An x86_64 image with Google
APIs (not a Play Store image) has root via `adb root`. Push the mitmproxy CA
as a system cert (`adb push cert.pem /system/etc/security/cacerts/`),
install the APK, set the proxy, capture. No patching.

B) Frida gadget. Download `frida-gadget` for arm64 from GitHub releases and
run `objection patchapk` (needs an x64 machine for apktool, or Docker) with
`--skip-resources --ignore-nativelibs` to avoid the NinePatch crash, then
hook `OkHttp3` or `fetch` to log requests. Works on a real device and sees
both request and response.

C) Manual smali patching. `apktool d` only the base APK (not the splits), add
a `networkSecurityConfig` that trusts user CAs, and do not patch OkHttp or
other classes. `apktool b`, sign, install with the unmodified split APKs.
That keeps clear of apk-mitm's destructive changes.

D) Ask Onesti. Contact info at onestiproducts.io. Ask about API
documentation for integration partners and say it is for an open-source HA
integration. Official support, no reversing.

### To build a cloud integration in HA

With a device GUID:

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

That would be a hybrid: ZHA for local control, cloud for PIN setting and
history. We have since decided not to build a second transport at all; see
`docs/upstream-status.md`.

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

Decompiled Nimly Connect and found the endpoints; decompiled the BLE app and
documented the ekey protocol; then the Wireshark boot capture, pairing the
lock with the hub, testing the cloud API, decompiling the white-label apps,
the failed MITM attempts, and the options flow UX work.
