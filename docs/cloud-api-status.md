# Cloud API reversing — status og veien videre

Sist oppdatert: 2026-03-30

## Mål

Gjenskape all funksjonalitet fra Nimly Connect-appen i Home Assistant:

- PIN-koder (sett/endre/slett) uten Zigbee sleepy device-problemer
- Event-historikk med brukeridentifikasjon
- Lock/unlock via cloud som backup

## Hva vi har gjort

### 1. Dekompilert Nimly Connect-appen

- APK `com.easyaccess.connect` v1.27.84
- React Native med Hermes bytecode → 3.1M linjer dekompilert JS
- Funnet alle API-endepunkter, auth-flyt, CAS-protokoll
- **Resultat:** Komplett API-spec i `docs/nimly-connect-app/iotiliti-api-spec.yaml`

### 2. Dekompilert alle 7 white-label-apper

- Keyfree, Salus, Forebygg, Homely, Copiax, Tekam, iotiliti
- Alle bruker identisk kodebase, kun config varierer
- Fant ny prod-URL: `api.customer.prod-neutralclone.onesti.aws.neurosys.pro`
- Fant Developer Options-meny, LF sin separate Keycloak-realm
- **Resultat:** Komplett oversikt i `docs/nimly-connect-app/reversing-notes.md`

### 3. Wireshark-capture av Connect Bridge (hub)

- Boot-sekvens: DNS → `boot-v2.onesti.io` → NTP → MQTT (port 8883)
- MQTT-broker: `3.75.35.23` (AWS eu-central-1), self-signed cert
- Software-stack: Embedded Linux, Dropbear SSH 2020.81, OpenSSL 1.1.1+
- **Resultat:** Komplett i `docs/connect-bridge/hardware-gateway.md`

### 4. Testet cloud API direkte

- OAuth2 auth fungerer (`POST /oauth/v2/token`)
- `/locations` — returnerer locations
- `/locations/{id}/users` — returnerer brukere
- `/users/me` — returnerer profil
- `/devices/{id}` — eksisterer, krever GUID
- **Resultat:** Auth og brukerdata fungerer

### 5. Paret lås med hub

- Låsen ble fjernet fra ZHA og paret med Connect Bridge
- Appen kan låse/låse opp og viser gateway + Touch Pro
- PIN-koder overlever re-paring (lokal lagring på låsen)

## Hva som IKKE fungerer

### group-devices returnerer `[]`

**Dette er hovedblokkeringen.** `GET /locations/{id}/group-devices` returnerer tom array
selv om appen viser enheter (gateway + Touch Pro) under samme location.

Testet med:

- Fersk OAuth2-token
- Begge location-IDer (HusA og Hus)
- Gammel URL (`api-neutralclone.iotiliti.cloud`)
- Ny URL (`api.customer.prod-neutralclone.onesti.aws.neurosys.pro`)
- Med og uten `X-Company-Id` header

Alle returnerer `[]`. Appen bruker eksakt samme endepunkt (verifisert i dekompilert kode).

**Mulige årsaker:**

1. Server-side tilgangskontroll vi ikke forstår
2. Token mangler et claim/scope som appen sin token har
3. Appen setter opp noe under onboarding som gir device-tilgang
4. Devicene er knyttet til gateway-IDen, ikke location-IDen
5. Det er en race condition — enheter dukker opp etter en polling-syklus

### MITM av appen feilet

Vi prøvde å se faktisk HTTP-trafikk fra appen:

| Metode                           | Resultat                                                                 |
| -------------------------------- | ------------------------------------------------------------------------ |
| **mitmproxy + proxy på telefon** | Appen nekter (stoler ikke på bruker-CA, targetSdk=35)                    |
| **apk-mitm (patche APK)**        | Krasjer — Ezviz SDK NullPointerException + NinePatch drawable-korrupsjon |
| **apk-mitm --skip-patches**      | Krasjer fortsatt (NinePatch)                                             |
| **PCAPdroid**                    | Fanger kun hostnames/IPs, ikke URL-paths (TLS)                           |
| **React Native DevTools**        | Release build, ingen debug-port                                          |
| **adb backup**                   | Appen blokkerer backup (`allowBackup=false`)                             |
| **run-as**                       | Package not debuggable                                                   |

## Hva nestemann må gjøre

### For å knekke group-devices

Du trenger å se hva appen faktisk sender — HTTP method, path, headers, body.
Velg én av disse tilnærmingene:

#### A) Android-emulator med root (anbefalt)

1. Sett opp Android-emulator (x86_64, Google APIs, **ikke** Play Store-image)
2. Emulatorbilder med Google APIs har root via `adb root`
3. Installer mitmproxy CA som system-cert: `adb push cert.pem /system/etc/security/cacerts/`
4. Installer Nimly Connect APK
5. Sett proxy, fang all trafikk
6. **Fordel:** Enklest, ingen patching nødvendig

#### B) Frida-gadget injeksjon

1. Last ned `frida-gadget` for arm64 fra GitHub releases
2. Bruk `objection patchapk` (krever x64-maskin for apktool, eller Docker)
3. Bruk `--skip-resources --ignore-nativelibs` for å unngå NinePatch-krasj
4. Hook `OkHttp3` eller `fetch` for å logge alle requests
5. **Fordel:** Fungerer på ekte enhet, ser request+response

#### C) Manuell smali-patching

1. `apktool d` bare base APK (ikke split APKs)
2. Legg til `networkSecurityConfig` som stoler på bruker-CAs
3. **IKKE** patch OkHttp eller andre klasser
4. `apktool b`, signer, installer sammen med umodifiserte split APKs
5. **Fordel:** Unngår apk-mitm sine destruktive endringer

#### D) Kontakt Onesti direkte

1. Skriv en e-post til Onesti (kontaktinfo på onestiproducts.io)
2. Spør om API-dokumentasjon for integrasjonspartnere
3. Nevn at vi bygger open-source HA-integrasjon
4. **Fordel:** Offisiell støtte, ingen reversing nødvendig

### For å bygge cloud API-integrasjon i HA

Når du har device-ID (GUID):

```python
# PIN-setting via cloud (omgår Zigbee sleepy device)
POST /devices/{deviceId}/access
Authorization: Bearer <token>
{"type": "pin", "code": "1234", "userId": "..."}

# Event-historikk
GET /devices/{deviceId}/event-history
Authorization: Bearer <token>

# Lock/unlock
POST /devices/{deviceId}/lock
Authorization: Bearer <token>
{"action": "lock"}  # eller "unlock"
```

Integrasjonen bør være en **hybrid** — ZHA for lokal kontroll, cloud API for PIN-setting og event-historikk.

## Nyttige filer

| Fil                                             | Innhold                                            |
| ----------------------------------------------- | -------------------------------------------------- |
| `docs/nimly-connect-app/reversing-notes.md`     | Komplett APK-reversing                             |
| `docs/nimly-connect-app/iotiliti-api-spec.yaml` | OpenAPI-spec (uverifisert)                         |
| `docs/nimly-connect-app/app-architecture.md`    | System-arkitektur og white-label                   |
| `docs/connect-bridge/hardware-gateway.md`       | Hub hardware og nettverksanalyse                   |
| `docs/slot-numbering.md`                        | Slot-nummerering usikkerhet                        |
| `docs/debugging.md`                             | Feilsøkingsguide                                   |
| `secrets.md` (gitignored)                       | Alle client secrets, company IDs, test-credentials |
| `reversing/`                                    | APK-filer og dekompilert kode                      |

## Tidslinje

- **2026-03-28:** Dekompilert Nimly Connect, funnet API-endepunkter
- **2026-03-29:** Dekompilert BLE-app, dokumentert ekey-protokoll
- **2026-03-30:** Wireshark boot-capture, paret lås med hub, testet cloud API,
  dekompilert alle white-label-apper, MITM-forsøk feilet, options flow UX forbedret
