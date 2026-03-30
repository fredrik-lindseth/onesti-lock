# Cloud API reversing — status and the road ahead

## Goal

Recreate all functionality from the Nimly Connect app in Home Assistant:

- PIN codes (set/change/delete) without Zigbee sleepy device issues
- Event history with user identification
- Lock/unlock via cloud as backup

## What we have done

### 1. Decompiled the Nimly Connect app

- APK `com.easyaccess.connect` v1.27.84
- React Native with Hermes bytecode → 3.1M lines of decompiled JS
- Found all API endpoints, auth flow, CAS protocol
- **Result:** Complete API spec in `docs/nimly-connect-app/iotiliti-api-spec.yaml`

### 2. Decompiled all 7 white-label apps

- Keyfree, Salus, Forebygg, Homely, Copiax, Tekam, iotiliti
- All use identical codebase, only config varies
- Found new prod URL: `api.customer.prod-neutralclone.onesti.aws.neurosys.pro`
- Found Developer Options menu, LF's separate Keycloak realm
- **Result:** Complete overview in `docs/nimly-connect-app/reversing-notes.md`

### 3. Wireshark capture of the Connect Bridge (hub)

- Boot sequence: DNS → `boot-v2.onesti.io` → NTP → MQTT (port 8883)
- MQTT broker: `3.75.35.23` (AWS eu-central-1), self-signed cert
- Software stack: Embedded Linux, Dropbear SSH 2020.81, OpenSSL 1.1.1+
- **Result:** Complete in `docs/connect-bridge/hardware-gateway.md`

### 4. Tested cloud API directly

- OAuth2 auth works (`POST /oauth/v2/token`)
- `/locations` — returns locations
- `/locations/{id}/users` — returns users
- `/users/me` — returns profile
- `/devices/{id}` — exists, requires GUID
- **Result:** Auth and user data works

### 5. Paired lock with hub

- The lock was removed from ZHA and paired with the Connect Bridge
- The app can lock/unlock and shows gateway + Touch Pro
- PIN codes survive re-pairing (stored locally on the lock)

## What does NOT work

### group-devices returns `[]`

**This is the main blocker.** `GET /locations/{id}/group-devices` returns an empty array even though the app shows devices (gateway + Touch Pro) under the same location.

Tested with:

- Fresh OAuth2 token
- Both location IDs (HusA and Hus)
- Old URL (`api-neutralclone.iotiliti.cloud`)
- New URL (`api.customer.prod-neutralclone.onesti.aws.neurosys.pro`)
- With and without `X-Company-Id` header

All return `[]`. The app uses the exact same endpoint (verified in decompiled code).

**Possible causes:**

1. Server-side access control we don't understand
2. Token is missing a claim/scope that the app's token has
3. The app sets up something during onboarding that grants device access
4. Devices are tied to the gateway ID, not the location ID
5. There is a race condition — devices appear after a polling cycle

### MITM of the app failed

We tried to see the actual HTTP traffic from the app:

| Method                              | Result                                                                      |
| ----------------------------------- | --------------------------------------------------------------------------- |
| **mitmproxy + proxy on phone**      | App refuses (does not trust user CA, targetSdk=35)                          |
| **apk-mitm (patch APK)**           | Crashes — Ezviz SDK NullPointerException + NinePatch drawable corruption    |
| **apk-mitm --skip-patches**        | Still crashes (NinePatch)                                                   |
| **PCAPdroid**                       | Captures only hostnames/IPs, not URL paths (TLS)                            |
| **React Native DevTools**           | Release build, no debug port                                                |
| **adb backup**                      | App blocks backup (`allowBackup=false`)                                     |
| **run-as**                          | Package not debuggable                                                      |

## What the next person needs to do

### To crack group-devices

You need to see what the app actually sends — HTTP method, path, headers, body.
Choose one of these approaches:

#### A) Android emulator with root (recommended)

1. Set up an Android emulator (x86_64, Google APIs, **not** a Play Store image)
2. Emulator images with Google APIs have root via `adb root`
3. Install mitmproxy CA as system cert: `adb push cert.pem /system/etc/security/cacerts/`
4. Install Nimly Connect APK
5. Set proxy, capture all traffic
6. **Advantage:** Easiest, no patching needed

#### B) Frida gadget injection

1. Download `frida-gadget` for arm64 from GitHub releases
2. Use `objection patchapk` (requires x64 machine for apktool, or Docker)
3. Use `--skip-resources --ignore-nativelibs` to avoid NinePatch crash
4. Hook `OkHttp3` or `fetch` to log all requests
5. **Advantage:** Works on a real device, sees request+response

#### C) Manual smali patching

1. `apktool d` only the base APK (not split APKs)
2. Add `networkSecurityConfig` that trusts user CAs
3. **DO NOT** patch OkHttp or other classes
4. `apktool b`, sign, install together with unmodified split APKs
5. **Advantage:** Avoids apk-mitm's destructive changes

#### D) Contact Onesti directly

1. Write an email to Onesti (contact info at onestiproducts.io)
2. Ask about API documentation for integration partners
3. Mention that we are building an open-source HA integration
4. **Advantage:** Official support, no reversing needed

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

The integration should be a **hybrid** — ZHA for local control, cloud API for PIN setting and event history.

## Useful files

| File                                            | Contents                                       |
| ----------------------------------------------- | ---------------------------------------------- |
| `docs/nimly-connect-app/reversing-notes.md`     | Complete APK reversing                         |
| `docs/nimly-connect-app/iotiliti-api-spec.yaml` | OpenAPI spec (unverified)                      |
| `docs/nimly-connect-app/app-architecture.md`    | System architecture and white-label            |
| `docs/connect-bridge/hardware-gateway.md`       | Hub hardware and network analysis              |
| `docs/slot-numbering.md`                        | Slot numbering uncertainty                     |
| `docs/debugging.md`                             | Debugging guide                                |
| `secrets.md` (gitignored)                       | All client secrets, company IDs, test credentials |
| `reversing/`                                    | APK files and decompiled code                  |

## Timeline

- Decompiled Nimly Connect, found API endpoints
- Decompiled BLE app, documented ekey protocol
- Wireshark boot capture, paired lock with hub, tested cloud API, decompiled all white-label apps, MITM attempts failed, options flow UX improved
