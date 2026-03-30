# EasyAccess Connect Bridge — Hardware & Network Reference

Gateway for Nimly/EasyAccess locks. Bridges Zigbee devices to iotiliti.cloud.
Goal: document everything so nobody needs to buy this hub to understand the system.

## Brand hierarchy (white-label)

The same hardware is sold under multiple brands:

| Level           | Entity                                                            | Role                                 |
| --------------- | ----------------------------------------------------------------- | ------------------------------------ |
| **Chipmaker**   | Develco Products / Onics A/S                                      | HW manufacturer (Aarhus, Denmark)    |
| **Platform**    | Squid.Link 2B                                                     | Gateway platform (MGW211)            |
| **Cloud**       | iotiliti (Safe4 Security Group)                                   | IoT platform, MQTT broker, REST API  |
| **White-label** | EasyAccess / E-Life / Nimly / Keyfree / Salus / Forebygg / Homely | End-user brands                      |

Labels on hardware say "EasyAccess Easy Living". The Connect Module in the lock says "E-Life 3.0".
The app is called "Nimly Connect". All the same system.

## Hardware identification

| Field                 | Value                                          |
| --------------------- | ---------------------------------------------- |
| **Brand**             | EasyAccess (Easy Living)                       |
| **Manufacturer**      | Develco Products / Onics A/S (Aarhus, Denmark) |
| **Model**             | MGW211-EAS2                                    |
| **Platform**          | Squid.Link 2B                                  |
| **PN**                | F0080Z0186                                     |
| **HW**                | 4.1.0                                          |
| **S/N**               | 0200 0001 3000 4433                            |
| **DHCP Vendor Class** | `HomeGate AIO`                                 |
| **mDNS Hostname**     | `gw-4433` (last 4 digits of S/N)               |

### Connect Module (in the lock)

| Field       | Value                                    |
| ----------- | ---------------------------------------- |
| **Brand**   | E-Life                                   |
| **Version** | 3.0                                      |
| **Role**    | Zigbee radio in the lock, pairs with hub |

## Network addresses

| Interface   | MAC address               | OUI                          |
| ----------- | ------------------------- | ---------------------------- |
| Ethernet    | `00:15:BC:27:D0:78`       | Develco (reg. 2005)          |
| WLAN        | `00:15:BC:27:D0:79`       | Develco (WLAN = Ethernet +1) |
| ZigBee IEEE | `00:15:BC:00:2C:11:1D:DE` | Develco                      |

## Zigbee

- **Zigbee 3.0** certified (Certificate ID: ZIG21356ZB331216-24, Dec 2021, spec 3.0.1)
- Install Code: `8CFD D0A6 0BC1 68B3 A4E2`
- Role: Zigbee Coordinator — pairs and controls locks via Zigbee
- Gateway-to-lock protocol: CAS (Command and Status) with AES encryption

Note: The **hub** is Zigbee 3.0 certified, but the Nimly **lock** (easyCodeTouch) is _not_ certified.

## Power supply (PSU)

| Field              | Value                                    |
| ------------------ | ---------------------------------------- |
| **Model**          | YS16-0902000E                            |
| **Input**          | 100-240V~ 50/60Hz 0.5A                   |
| **Output**         | 9V DC 2A                                 |
| **Connector**      | Barrel jack, center-positive, 5.5x2.1mm  |
| **Insulation**     | Class II (double insulated)              |
| **Certifications** | CE, GS (TÜV Rheinland)                   |
| **Manufactured**   | China, July 2021                         |

**Replacement:** Any 9V/2A DC barrel jack adapter with center-positive polarity and 5.5x2.1mm plug.

## Physical

- White plastic box, approx 10x10cm
- 4 rubber feet with screws (PCB underneath)
- USB-A port (unknown purpose — debug/serial?)
- Wall mounting via bracket slots on the back
- Ethernet port (RJ45)
- QR code on the back (likely Install Code or S/N for the app)
- Data Matrix (2D) QR on the box (PN/S/N for inventory management)

## Certifications

- CE, RoHS, FCC
- Zigbee 3.0 (ZIG21356ZB331216-24)

---

## Software stack (from network analysis)

| Component     | Version/Detail                                                    |
| ------------- | ----------------------------------------------------------------- |
| **OS**        | Embedded Linux ("HomeGate AIO"), likely Yocto/Buildroot           |
| **SSH**       | Dropbear 2020.81 (ED25519 host key, publickey-only auth)          |
| **TLS**       | OpenSSL 1.1.1+ or 3.x (supports TLS 1.0–1.3, 31 cipher suites)  |
| **NTP**       | NTPv4 (syncs from 0-3.pool.ntp.org)                               |
| **mDNS**      | Advertises `gw-{SERIAL}._ssh._tcp.local`                          |
| **Webserver** | None (port 80/443 closed)                                         |

### SSH access

SSH is open during boot (~60 sec), but closes after firmware is loaded.
Requires publickey auth — no password login. ED25519 host key.
Practically inaccessible without adding your own key.

---

## Network communication

### Boot sequence (observed via Wireshark)

1. **DHCP** — obtains IP, hostname `gw-4433`, Vendor Class `HomeGate AIO`
2. **mDNS** — advertises `gw-4433.local` and `gw-4433._ssh._tcp.local` (port 22)
3. **DNS** → `boot-v2.onesti.io` (provisioning endpoint)
4. **NTP** → `0-3.pool.ntp.org` (clock sync)
5. **TLS** → `boot-v2.onesti.io` (HTTPS, TLS 1.3)
6. **MQTT** → persistent connection to MQTT broker (port 8883, TLS 1.3)

Total time from power to MQTT connection: ~50 seconds.

### Cloud endpoints

#### Boot/provisioning

| Field         | Detail                                                                       |
| ------------- | ---------------------------------------------------------------------------- |
| **Hostname**  | `boot-v2.onesti.io`                                                          |
| **IPs**       | `3.127.252.118`, `52.29.36.20`, `63.179.222.106` (AWS eu-central-1, rotating) |
| **Protocol**  | HTTPS (TLS 1.3, AES-128-GCM)                                                 |
| **TLS cert**  | `CN=*.onesti.io`, issuer: Amazon RSA 2048 M04, valid until 2027-03-04         |
| **HTTP**      | HTTP/2                                                                       |
| **`/health`** | `200 OK` → `{}` (Hapi/NestJS style)                                          |
| **All other** | `404` — likely requires gateway ID/token in path or headers                   |

#### MQTT broker (persistent cloud connection)

| Field                | Value                                                                |
| -------------------- | -------------------------------------------------------------------- |
| **IP**               | `3.75.35.23` (AWS eu-central-1)                                      |
| **Port**             | 8883 (MQTT over TLS)                                                 |
| **Protocol**         | TLS 1.3, AES-128-GCM                                                 |
| **TLS cert Subject** | `CN=onesti.iotiliti.cloud`                                           |
| **TLS cert Issuer**  | `C=PL, ST=Some-State, O=Internet Widgits Pty Ltd` **(self-signed!)** |
| **Cert validity**    | 2024-11-26 to 2034-11-24 (10 years)                                  |
| **rDNS**             | `ec2-3-75-35-23.eu-central-1.compute.amazonaws.com`                  |

**Security note:** The MQTT certificate is self-signed with OpenSSL defaults from Poland.
The hub has the CA certificate hardcoded and does not validate against public CAs.
This means MITM of MQTT traffic is possible if the CA on the hub is replaced.

#### REST API (used by the app, not the hub directly)

| Brand                | API URL                           |
| -------------------- | --------------------------------- |
| **Nimly/EasyAccess** | `api-neutralclone.iotiliti.cloud` |
| Keyfree              | `api-keyfree.iotiliti.cloud`      |
| Salus                | `api-salus.iotiliti.cloud`        |
| Forebygg             | `api-forebygg.iotiliti.cloud`     |
| Homely               | `api.homely.no`                   |

See `docs/nimly-connect-app/reversing-notes.md` for complete API documentation.
See `docs/nimly-connect-app/app-architecture.md` for complete white-label overview.

### Complete communication chain

```
┌─────────┐    REST API     ┌──────────────────────┐     MQTT      ┌───────────┐   Zigbee/CAS   ┌──────┐
│  Nimly   │ ◄────────────► │  iotiliti.cloud       │ ◄──────────► │  Connect  │ ◄────────────► │ Lock │
│  Connect │    OAuth2/      │  (AWS eu-central-1)   │   TLS 1.3    │  Bridge   │   AES-encr.    │      │
│  App     │    Cognito      │                       │   port 8883  │  (hub)    │                │      │
└─────────┘                 └──────────────────────┘               └───────────┘               └──────┘
                              │
                              │ Boot: boot-v2.onesti.io (HTTPS)
                              │ API:  api-neutralclone.iotiliti.cloud
                              │ MQTT: 3.75.35.23:8883
```

### Firewall requirements (outbound from hub)

| Destination                                 | Port | Protocol  | Purpose                     |
| ------------------------------------------- | ---- | --------- | --------------------------- |
| `boot-v2.onesti.io`                         | 443  | HTTPS     | Provisioning at boot        |
| `3.75.35.23` (or other AWS eu-central-1)    | 8883 | MQTT/TLS  | Persistent cloud connection |
| `0-3.pool.ntp.org`                          | 123  | NTP       | Clock sync                  |

The hub only needs these three to function. DNS (port 53) is implicit.

---

## Firmware update

On first boot (or after factory reset) the hub displays:

> "please wait, the gateway will now run and update to the latest software version before rebooting..."

The update:

1. Runs from internal flash (does not need network for the update itself)
2. Reboots automatically after ~5-10 minutes
3. LED sequence: blinking green → solid green (power) → solid green (left button) = done
4. After reboot the hub connects to MQTT broker and reports "gateway online" in the app

The app can also trigger firmware updates:

> "installing updates - downloading 97%" → "completing - the gateway is installing the update and will do a restart"

---

## Pairing a lock with the hub

The lock can only be paired with **one** Zigbee coordinator at a time.
If the lock is paired with ZHA/zigbee2mqtt, it must be removed first:

1. HA → Settings → Devices & Services → ZHA → the lock → ⋮ → **Remove**
2. Wake the lock (press keypad) before pressing Remove
3. Factory reset Zigbee module: hold the reset button on the module for **10+ seconds**
4. LED blinks rapidly = pairing mode
5. Open Nimly Connect → add device → "searching for devices"

**Important:** The hub has limited Zigbee range. Metal casing around the lock (Faraday cage) weakens signal. Place the hub as close to the lock as possible during pairing.

---

## Relevance for the HA integration

This hub is **not required** for the HA integration — ZHA/zigbee2mqtt communicates directly with the lock.
The hub is only needed for:

- The Nimly Connect app
- Cloud API access (iotiliti REST API)
- PIN setting via cloud (bypasses Zigbee sleepy device timeout)
- Event history via cloud API

### Hybrid strategy

Optimal setup uses **both**:

- **ZHA** for local control (lock/unlock, state monitoring)
- **Cloud API** via the hub for PIN setting and event history (bypasses sleepy device issues)
