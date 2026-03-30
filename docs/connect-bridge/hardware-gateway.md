# EasyAccess Connect Bridge — Hardware & Network Reference

Gateway for Nimly/EasyAccess låser. Bridges Zigbee-enheter til iotiliti.cloud.
Mål: dokumentere alt slik at ingen trenger å kjøpe denne hubben for å forstå systemet.

## Merke-hierarki (white-label)

Samme hardware selges under flere merker:

| Nivå            | Aktør                                                             | Rolle                                |
| --------------- | ----------------------------------------------------------------- | ------------------------------------ |
| **Chipmaker**   | Develco Products / Onics A/S                                      | HW-produsent (Aarhus, Danmark)       |
| **Plattform**   | Squid.Link 2B                                                     | Gateway-plattformen (MGW211)         |
| **Sky**         | iotiliti (Safe4 Security Group)                                   | IoT-plattform, MQTT-broker, REST API |
| **White-label** | EasyAccess / E-Life / Nimly / Keyfree / Salus / Forebygg / Homely | Sluttbruker-merkevarer               |

Klistremerkene på hardware sier "EasyAccess Easy Living". Connect-modulen i låsen sier "E-Life 3.0".
Appen heter "Nimly Connect". Alt er samme system.

## Hardware-identifikasjon

| Felt                  | Verdi                                          |
| --------------------- | ---------------------------------------------- |
| **Merke**             | EasyAccess (Easy Living)                       |
| **Produsent**         | Develco Products / Onics A/S (Aarhus, Danmark) |
| **Modell**            | MGW211-EAS2                                    |
| **Plattform**         | Squid.Link 2B                                  |
| **PN**                | F0080Z0186                                     |
| **HW**                | 4.1.0                                          |
| **S/N**               | 0200 0001 3000 4433                            |
| **DHCP Vendor Class** | `HomeGate AIO`                                 |
| **mDNS Hostname**     | `gw-4433` (siste 4 siffer av S/N)              |

### Connect-modul (i låsen)

| Felt        | Verdi                                  |
| ----------- | -------------------------------------- |
| **Merke**   | E-Life                                 |
| **Versjon** | 3.0                                    |
| **Rolle**   | Zigbee-radio i låsen, pares med hubben |

## Nettverksadresser

| Interface   | MAC-adresse               | OUI                          |
| ----------- | ------------------------- | ---------------------------- |
| Ethernet    | `00:15:BC:27:D0:78`       | Develco (reg. 2005)          |
| WLAN        | `00:15:BC:27:D0:79`       | Develco (WLAN = Ethernet +1) |
| ZigBee IEEE | `00:15:BC:00:2C:11:1D:DE` | Develco                      |

## Zigbee

- **Zigbee 3.0** sertifisert (Certificate ID: ZIG21356ZB331216-24, des 2021, spec 3.0.1)
- Install Code: `8CFD D0A6 0BC1 68B3 A4E2`
- Rollen: Zigbee Coordinator — parer og styrer låser via Zigbee
- Gateway-til-lås protokoll: CAS (Command and Status) med AES-kryptering

Merk: **Hubben** er Zigbee 3.0-sertifisert, men Nimly-**låsen** (easyCodeTouch) er _ikke_ sertifisert.

## Strømforsyning (PSU)

| Felt                | Verdi                                   |
| ------------------- | --------------------------------------- |
| **Modell**          | YS16-0902000E                           |
| **Input**           | 100-240V~ 50/60Hz 0.5A                  |
| **Output**          | 9V DC 2A                                |
| **Kontakt**         | Barrel jack, center-positive, 5.5x2.1mm |
| **Isolasjon**       | Class II (dobbeltissolert)              |
| **Sertifiseringer** | CE, GS (TÜV Rheinland)                  |
| **Produsert**       | Kina, juli 2021                         |

**Erstatning:** Enhver 9V/2A DC barrel jack adapter med center-positive polaritet og 5.5x2.1mm plugg.

## Fysisk

- Hvit plastboks, ca 10x10cm
- 4 gummifot-skruer (brett under)
- USB-A port (ukjent formål — debug/seriell?)
- Veggmontering via brakett-spor på baksiden
- Ethernet-port (RJ45)
- QR-kode på baksiden (sannsynligvis Install Code eller S/N for appen)
- Data Matrix (2D) QR på esken (PN/S/N for lagerstyring)

## Sertifiseringer

- CE, RoHS, FCC
- Zigbee 3.0 (ZIG21356ZB331216-24)

---

## Software-stack (fra nettverksanalyse)

| Komponent     | Versjon/Detalj                                                   |
| ------------- | ---------------------------------------------------------------- |
| **OS**        | Embedded Linux ("HomeGate AIO"), sannsynligvis Yocto/Buildroot   |
| **SSH**       | Dropbear 2020.81 (ED25519 host key, publickey-only auth)         |
| **TLS**       | OpenSSL 1.1.1+ eller 3.x (støtter TLS 1.0–1.3, 31 cipher suites) |
| **NTP**       | NTPv4 (syncer fra 0-3.pool.ntp.org)                              |
| **mDNS**      | Annonserer `gw-{SERIAL}._ssh._tcp.local`                         |
| **Webserver** | Ingen (port 80/443 lukket)                                       |

### SSH-tilgang

SSH er åpen under boot (~60 sek), men lukkes etter at firmware er lastet.
Krever publickey-auth — ingen passord-login. ED25519 host key.
Praktisk utilgjengelig uten å legge inn egen nøkkel.

---

## Nettverkskommunikasjon

### Boot-sekvens (observert via Wireshark)

1. **DHCP** — henter IP, hostname `gw-4433`, Vendor Class `HomeGate AIO`
2. **mDNS** — annonserer `gw-4433.local` og `gw-4433._ssh._tcp.local` (port 22)
3. **DNS** → `boot-v2.onesti.io` (provisioning-endepunkt)
4. **NTP** → `0-3.pool.ntp.org` (klokkesynk)
5. **TLS** → `boot-v2.onesti.io` (HTTPS, TLS 1.3)
6. **MQTT** → persistent forbindelse til MQTT-broker (port 8883, TLS 1.3)

Total tid fra strøm til MQTT-tilkobling: ~50 sekunder.

### Sky-endepunkter

#### Boot/provisioning

| Endepunkt     | Detalj                                                                       |
| ------------- | ---------------------------------------------------------------------------- |
| **Hostname**  | `boot-v2.onesti.io`                                                          |
| **IP-er**     | `3.127.252.118`, `52.29.36.20`, `63.179.222.106` (AWS eu-central-1, roterer) |
| **Protokoll** | HTTPS (TLS 1.3, AES-128-GCM)                                                 |
| **TLS-cert**  | `CN=*.onesti.io`, issuer: Amazon RSA 2048 M04, gyldig til 2027-03-04         |
| **HTTP**      | HTTP/2                                                                       |
| **`/health`** | `200 OK` → `{}` (Hapi/NestJS-stil)                                           |
| **Alt annet** | `404` — trenger sannsynligvis gateway-ID/token i path eller headers          |

#### MQTT-broker (persistent sky-forbindelse)

| Felt                 | Verdi                                                                |
| -------------------- | -------------------------------------------------------------------- |
| **IP**               | `3.75.35.23` (AWS eu-central-1)                                      |
| **Port**             | 8883 (MQTT over TLS)                                                 |
| **Protokoll**        | TLS 1.3, AES-128-GCM                                                 |
| **TLS-cert Subject** | `CN=onesti.iotiliti.cloud`                                           |
| **TLS-cert Issuer**  | `C=PL, ST=Some-State, O=Internet Widgits Pty Ltd` **(self-signed!)** |
| **Cert gyldig**      | 2024-11-26 til 2034-11-24 (10 år)                                    |
| **rDNS**             | `ec2-3-75-35-23.eu-central-1.compute.amazonaws.com`                  |

**Sikkerhetsmerknad:** MQTT-sertifikatet er self-signed med OpenSSL default-verdier fra Polen.
Hubben har CA-sertifikatet hardkodet og validerer ikke mot public CA.
Dette betyr at MITM av MQTT-trafikken er mulig dersom man erstatter CA-en på hubben.

#### REST API (brukt av appen, ikke hubben direkte)

| Merke                | API URL                           |
| -------------------- | --------------------------------- |
| **Nimly/EasyAccess** | `api-neutralclone.iotiliti.cloud` |
| Keyfree              | `api-keyfree.iotiliti.cloud`      |
| Salus                | `api-salus.iotiliti.cloud`        |
| Forebygg             | `api-forebygg.iotiliti.cloud`     |
| Homely               | `api.homely.no`                   |

Se `docs/nimly-connect-app/reversing-notes.md` for komplett API-dokumentasjon.
Se `docs/nimly-connect-app/app-architecture.md` for komplett white-label-oversikt.

### Komplett kommunikasjonskjede

```
┌─────────┐    REST API     ┌──────────────────────┐     MQTT      ┌───────────┐   Zigbee/CAS   ┌──────┐
│  Nimly   │ ◄────────────► │  iotiliti.cloud       │ ◄──────────► │  Connect  │ ◄────────────► │ Lås  │
│  Connect │    OAuth2/      │  (AWS eu-central-1)   │   TLS 1.3    │  Bridge   │   AES-krypt.   │      │
│  App     │    Cognito      │                       │   port 8883  │  (hub)    │                │      │
└─────────┘                 └──────────────────────┘               └───────────┘               └──────┘
                              │
                              │ Boot: boot-v2.onesti.io (HTTPS)
                              │ API:  api-neutralclone.iotiliti.cloud
                              │ MQTT: 3.75.35.23:8883
```

### Brannmur-krav (utgående fra hubben)

| Destinasjon                                 | Port | Protokoll | Formål                     |
| ------------------------------------------- | ---- | --------- | -------------------------- |
| `boot-v2.onesti.io`                         | 443  | HTTPS     | Provisioning ved boot      |
| `3.75.35.23` (eller andre AWS eu-central-1) | 8883 | MQTT/TLS  | Persistent sky-forbindelse |
| `0-3.pool.ntp.org`                          | 123  | NTP       | Klokkesynk                 |

Hubben trenger kun disse tre for å fungere. DNS (port 53) er implisitt.

---

## Firmware-oppdatering

Ved første boot (eller etter factory reset) viser hubben:

> "please wait, the gateway will now run and update to the latest software version before rebooting..."

Oppdateringen:

1. Kjører fra intern flash (trenger ikke nett for selve oppdateringen)
2. Reboooter automatisk etter ~5-10 minutter
3. LED-sekvens: blinkende grønt → fast grønt (power) → fast grønt (venstre knapp) = ferdig
4. Etter reboot kobler hubben til MQTT-broker og rapporterer "gateway online" i appen

Appen kan også trigge firmware-oppdatering:

> "installing updates - downloading 97%" → "completing - the gateway is installing the update and will do a restart"

---

## Paring av lås med hub

Låsen kan kun være paret med **én** Zigbee-koordinator om gangen.
Hvis låsen er paret med ZHA/zigbee2mqtt, må den fjernes derfra først:

1. HA → Settings → Devices & Services → ZHA → Dørlåsen → ⋮ → **Remove**
2. Vekk låsen (trykk keypad) før du trykker Remove
3. Factory-reset Zigbee-modulen: hold reset-knappen på modulen i **10+ sekunder**
4. LED blinker raskt = paringsmodus
5. Åpne Nimly Connect → legg til enhet → "searching for devices"

**Viktig:** Hubben har begrenset Zigbee-rekkevidde. Metallboks rundt låsen (Faraday-bur) svekker signalet. Plasser hubben så nær låsen som mulig under paring.

---

## Relevans for HA-integrasjonen

Denne hubben er **ikke nødvendig** for HA-integrasjonen — ZHA/zigbee2mqtt snakker direkte med låsen.
Hubben er kun nødvendig for:

- Nimly Connect-appen
- Cloud API-tilgang (iotiliti REST API)
- PIN-setting via cloud (omgår Zigbee sleepy device timeout)
- Event-historikk via cloud API

### Hybrid-strategi

Optimal oppsett bruker **begge**:

- **ZHA** for lokal kontroll (lock/unlock, tilstandsovervåking)
- **Cloud API** via hubben for PIN-setting og event-historikk (omgår sleepy device-problemer)
