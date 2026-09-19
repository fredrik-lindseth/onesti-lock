# EasyAccess Connect Bridge: hardware and network reference

Gateway for Nimly/EasyAccess locks, bridging Zigbee devices to iotiliti.cloud.
Documented so nobody needs to buy the hub to understand the system.

## Brand hierarchy (white-label)

The same hardware is sold under several brands, so one system goes by three
names: the label on the hub says "EasyAccess Easy Living", the Connect Module
in the lock says "E-Life 3.0", and the app is called "Nimly Connect".

| Level       | Entity                                                            | Role                                |
| ----------- | ----------------------------------------------------------------- | ----------------------------------- |
| Chipmaker   | Develco Products / Onics A/S                                      | HW manufacturer (Aarhus, Denmark)   |
| Platform    | Squid.Link 2B                                                     | Gateway platform (MGW211)           |
| Cloud       | iotiliti (Safe4 Security Group)                                   | IoT platform, MQTT broker, REST API |
| White-label | EasyAccess / E-Life / Nimly / Keyfree / Salus / Forebygg / Homely | End-user brands                     |

## Hardware identification

| Field             | Value                                          |
| ----------------- | ---------------------------------------------- |
| Brand             | EasyAccess (Easy Living)                       |
| Manufacturer      | Develco Products / Onics A/S (Aarhus, Denmark) |
| Model             | MGW211-EAS2                                    |
| Platform          | Squid.Link 2B                                  |
| PN                | F0080Z0186                                     |
| HW                | 4.1.0                                          |
| S/N               | 0200 0001 3000 4433                            |
| DHCP Vendor Class | `HomeGate AIO`                                 |
| mDNS Hostname     | `gw-4433` (last 4 digits of S/N)               |

### Connect Module (in the lock)

| Field   | Value                                    |
| ------- | ---------------------------------------- |
| Brand   | E-Life                                   |
| Version | 3.0                                      |
| Role    | Zigbee radio in the lock, pairs with hub |

## Network addresses

| Interface   | MAC address               | OUI                          |
| ----------- | ------------------------- | ---------------------------- |
| Ethernet    | `00:15:BC:27:D0:78`       | Develco (reg. 2005)          |
| WLAN        | `00:15:BC:27:D0:79`       | Develco (WLAN = Ethernet +1) |
| ZigBee IEEE | `00:15:BC:00:2C:11:1D:DE` | Develco                      |

## Zigbee

- **Zigbee 3.0** certified (Certificate ID: ZIG21356ZB331216-24, Dec 2021, spec 3.0.1;
  the certificate is listed on csa-iot.org as "Squid.link Gateway", Onics A/S / Frient A/S)
- Install Code: `8CFD D0A6 0BC1 68B3 A4E2`
- Role: Zigbee coordinator, pairs and controls the locks
- Gateway-to-lock protocol: Zigbee 3.0, the ZCL Door Lock cluster, the same
  thing ZHA speaks to the lock. Earlier versions of this file called it "CAS
  with AES encryption"; that came from the Ezviz camera SDK's error table in
  the app bundle and had nothing to do with the lock (see
  `docs/nimly-connect-app/reversing-notes.md`).

The certificate covers the hub. Whether the lock's Connect Module holds a
certificate of its own has not been checked against the CSA database; its
manual says "Zigbee 3.0" and nothing about certification.

## Power supply (PSU)

| Field          | Value                                   |
| -------------- | --------------------------------------- |
| Model          | YS16-0902000E                           |
| Input          | 100-240V~ 50/60Hz 0.5A                  |
| Output         | 9V DC 2A                                |
| Connector      | Barrel jack, center-positive, 5.5x2.1mm |
| Insulation     | Class II (double insulated)             |
| Certifications | CE, GS (TÜV Rheinland)                  |
| Manufactured   | China, July 2021                        |

Any 9V/2A DC barrel jack adapter with center-positive polarity and a 5.5x2.1mm
plug will do as a replacement.

## Physical

- White plastic box, approx 10x10cm
- 4 rubber feet with screws (PCB underneath)
- USB-A port (unknown purpose, debug/serial?)
- Wall mounting via bracket slots on the back
- Ethernet port (RJ45)
- QR code on the back (likely Install Code or S/N for the app)
- Data Matrix (2D) QR on the box (PN/S/N for inventory management)
- Certifications on the label: CE, RoHS, FCC

## Software stack (from network analysis)

| Component | Version/Detail                                                 |
| --------- | -------------------------------------------------------------- |
| OS        | Embedded Linux ("HomeGate AIO"), likely Yocto/Buildroot        |
| SSH       | Dropbear 2020.81 (ED25519 host key, publickey-only auth)       |
| TLS       | OpenSSL 1.1.1+ or 3.x (supports TLS 1.0–1.3, 31 cipher suites) |
| NTP       | NTPv4 (syncs from 0-3.pool.ntp.org)                            |
| mDNS      | Advertises `gw-{SERIAL}._ssh._tcp.local`                       |
| Webserver | None (port 80/443 closed)                                      |

### SSH access

SSH is open for about 60 seconds during boot and closes once the firmware is
loaded. It takes public keys only (no password login, ED25519 host key), so it
is practically inaccessible unless you can add your own key.

## Network communication

Everything in this section was observed once, in a Wireshark capture of the
hub's boot at the end of March 2026. The IPs rotate and the certificates will
be renewed, so treat the addresses and dates as a snapshot.

### Boot sequence (observed via Wireshark)

1. **DHCP:** obtains IP, hostname `gw-4433`, Vendor Class `HomeGate AIO`
2. **mDNS:** advertises `gw-4433.local` and `gw-4433._ssh._tcp.local` (port 22)
3. **DNS:** `boot-v2.onesti.io` (provisioning endpoint)
4. **NTP:** `0-3.pool.ntp.org` (clock sync)
5. **TLS:** `boot-v2.onesti.io` (HTTPS, TLS 1.3)
6. **MQTT:** persistent connection to the broker (port 8883, TLS 1.3)

Total time from power to MQTT connection: ~50 seconds.

### Cloud endpoints

#### Boot/provisioning

| Field     | Detail                                                                        |
| --------- | ----------------------------------------------------------------------------- |
| Hostname  | `boot-v2.onesti.io`                                                           |
| IPs       | `3.127.252.118`, `52.29.36.20`, `63.179.222.106` (AWS eu-central-1, rotating) |
| Protocol  | HTTPS (TLS 1.3, AES-128-GCM)                                                  |
| TLS cert  | `CN=*.onesti.io`, issuer: Amazon RSA 2048 M04, valid until 2027-03-04         |
| HTTP      | HTTP/2                                                                        |
| `/health` | `200 OK` → `{}` (Hapi/NestJS style)                                           |
| All other | `404`, likely requires gateway ID/token in path or headers                    |

#### MQTT broker (persistent cloud connection)

| Field            | Value                                                                |
| ---------------- | -------------------------------------------------------------------- |
| IP               | `3.75.35.23` (AWS eu-central-1)                                      |
| Port             | 8883 (MQTT over TLS)                                                 |
| Protocol         | TLS 1.3, AES-128-GCM                                                 |
| TLS cert Subject | `CN=onesti.iotiliti.cloud`                                           |
| TLS cert Issuer  | `C=PL, ST=Some-State, O=Internet Widgits Pty Ltd` **(self-signed!)** |
| Cert validity    | 2024-11-26 to 2034-11-24 (10 years)                                  |
| rDNS             | `ec2-3-75-35-23.eu-central-1.compute.amazonaws.com`                  |

The MQTT certificate is self-signed, with OpenSSL's default subject fields and
the country set to Poland. The hub has the CA certificate hardcoded and does not
validate against public CAs, so MITM of MQTT traffic is possible if the CA on
the hub is replaced.

#### REST API (used by the app, not the hub directly)

The hub was never seen talking to the REST API. The app does, at
`api-neutralclone.iotiliti.cloud` for Nimly (Connect v1.27.84) or
`api.customer.prod-neutralclone.onesti.aws.neurosys.pro` (newer builds). The
per-brand URL table is in `docs/nimly-connect-app/reversing-notes.md`, and
`docs/nimly-connect-app/app-architecture.md` has the white-label overview.

### Complete communication chain

```
┌─────────┐    REST API     ┌──────────────────────┐     MQTT      ┌───────────┐   Zigbee 3.0   ┌──────┐
│  Nimly   │ ◄────────────► │  iotiliti.cloud       │ ◄──────────► │  Connect  │ ◄────────────► │ Lock │
│  Connect │    OAuth2/      │  (AWS eu-central-1)   │   TLS 1.3    │  Bridge   │   ZCL Door     │      │
│  App     │    Cognito      │                       │   port 8883  │  (hub)    │   Lock cluster │      │
└─────────┘                 └──────────────────────┘               └───────────┘               └──────┘
                              │
                              │ Boot: boot-v2.onesti.io (HTTPS)
                              │ API:  api-neutralclone.iotiliti.cloud
                              │ MQTT: 3.75.35.23:8883
```

### Firewall requirements (outbound from hub)

| Destination                              | Port | Protocol | Purpose                     |
| ---------------------------------------- | ---- | -------- | --------------------------- |
| `boot-v2.onesti.io`                      | 443  | HTTPS    | Provisioning at boot        |
| `3.75.35.23` (or other AWS eu-central-1) | 8883 | MQTT/TLS | Persistent cloud connection |
| `0-3.pool.ntp.org`                       | 123  | NTP      | Clock sync                  |

The hub only needs these three to function. DNS (port 53) is implicit.

## Firmware update

On first boot (or after factory reset) the hub displays:

> "please wait, the gateway will now run and update to the latest software version before rebooting..."

The update runs from internal flash (no network needed for the update itself)
and reboots automatically after ~5-10 minutes. LED sequence: blinking green →
solid green (power) → solid green (left button) = done. After the reboot the
hub connects to the MQTT broker and reports "gateway online" in the app.

The app can also trigger firmware updates:

> "installing updates - downloading 97%" → "completing - the gateway is installing the update and will do a restart"

## Pairing a lock with the hub

The lock pairs with **one** Zigbee coordinator at a time. If it is paired with
ZHA/zigbee2mqtt, remove it there first:

1. HA → Settings → Devices & Services → ZHA → the lock → ⋮ → **Remove**
2. Wake the lock (press the keypad) before pressing Remove
3. Factory reset the Zigbee module: hold the reset button on the module for **10+ seconds**
4. LED blinks rapidly = pairing mode
5. Open Nimly Connect → add device → "searching for devices"

The hub has limited Zigbee range, and the metal casing around the lock acts as
a Faraday cage. Place the hub as close to the lock as possible during pairing.

## Relevance for the HA integration

The HA integration does not need the hub, since ZHA or zigbee2mqtt talks
directly to the lock. The hub is only needed for:

- The Nimly Connect app
- Cloud API access (iotiliti REST API)
- PIN setting via cloud (bypasses the Zigbee sleepy device timeout)
- Event history via the cloud API

The optimal setup uses both: ZHA for local control (lock/unlock, state
monitoring), and the cloud API via the hub for PIN setting and event history.
