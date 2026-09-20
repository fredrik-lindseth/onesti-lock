# EasyAccess Connect Bridge: hardware and network reference

Gateway for Nimly/EasyAccess locks, bridging Zigbee devices to iotiliti.cloud.
Documented so nobody needs to buy the hub to understand the system.

## Brand hierarchy (white-label)

The same hardware is sold under several brands, so one system goes by three
names: the label on the hub says "EasyAccess Easy Living", the Connect Module
in the lock says "E-Life 3.0", and the app is called "Nimly Connect".

| Level       | Entity                                                            | Role                                |
| ----------- | ----------------------------------------------------------------- | ----------------------------------- |
| Hub maker   | Develco Products / Onics A/S                                      | Gateway hardware (Aarhus, Denmark)  |
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

| Field   | Value                                        |
| ------- | -------------------------------------------- |
| Brand   | E-Life                                       |
| Version | 3.0                                          |
| Article | ZMNC010, EAN 5704571842582                   |
| Role    | Zigbee and BLE radio in the lock             |

The module is sold on its own, and the same EAN comes back at every Nordic
retailer checked on 2026-09-20: Copiax 50461903, Staypro 3131023,
Elektroimportøren 5800460, Ahlsell 5868052, Dustin 5011307956, Clas Ohlson
41-8237-1. No second EAN or article number for the same product name turned up
anywhere, so a module revision is not something the trade tracks. You cannot
order a particular one.

### Where "E-Life" comes from

E-Life is Onesti's own name for the module, printed in white silkscreen on the
module board itself. It is not a Zigbee attribute and not something the lock
ever reports: the Basic cluster answers "Onesti Products AS" for
ManufacturerName and the lock model ("NimlyPRO", "EasyFingerTouch",
"easyCodeTouch_v1") for ModelIdentifier, and nothing in the repo's decompiled
apps, in the cloud API or in any vendor manual mentions E-Life at all. Read it
off the board, or not at all.

EasyAccess's own mounting guide photographs the mark: `e-Life` in white on
the black module board, to the right of the RF shield, with a small logo
after it, seated on a green lock mainboard silkscreened `MODULE` at the
connector, `KEY` below it and `PL943_Back05 2020.06.02` along the edge
(`https://easyaccess.no/wp-content/uploads/2021/04/ZigBee-modul-montering.pdf`,
kept in `docs/manuals/`, rendered at 500 dpi and read 2026-09-20). A note
elsewhere in the project's own history put the word on the mainboard; the
close-up says module. Whether the `3.0` on Fredrik's module is a module
generation or just "Zigbee 3.0" is unknown; the 2021 photo shows no version
number after the name at all. The module in that photo has one visible LED,
lit blue, next to the button; the 2024 guide's drawing shows two.

The name also titles the vendor's own Zigbee protocol spec, *E-life Zigbee
Modul User Manual v2.0*, written in Word by Andrea Birkheim on 2021-01-26 and
posted publicly by a customer in
[Z2M#6379](https://github.com/Koenkk/zigbee2mqtt/issues/6379) on 2021-02-20
(direct link:
`https://github.com/Koenkk/zigbee2mqtt/files/6015013/E-life.Zigbee.Modul.User.Manual.v2.0.pdf`).
That document is the only vendor-written description of the Zigbee side we
have, and the `v2.0` is the manual's own version, not the module's. Its
contents are summarised in `docs/zigbee-protocol/elife-module-spec.md`.

### Which silicon

The EUI64 of every Onesti lock seen in public issues from 2021 to 2026 starts
with `f4:ce:36`, which the IEEE registry assigns to **Nordic Semiconductor
ASA**. Fredrik's own lock (`f4:ce:36:88:61:9c:f4:6f`) and the NimlyCodePRO
interview in
[Z2M#31385](https://github.com/Koenkk/zigbee2mqtt/issues/31385) are in the same
range, as are the addresses posted in Z2M issues 14726, 17205, 18508, 19627,
19738, 23551 and 32772, and the EasyCodeTouch in the March 2021 deCONZ sniff
(`f4:ce:36:32:a2:96:09:ab`, `docs/manuals/`). The manufacturer code in the
node descriptor points the same way: 4660 (0x1234) is the default an
unconfigured ZBOSS stack reports, and ZBOSS is the Zigbee stack in Nordic's
nRF Connect SDK, so the vendor never set its own. The only Nordic parts with
an 802.15.4 radio are the nRF52840, the nRF52833 and the nRF5340, and all
three carry a Bluetooth LE radio on the same die. An earlier note here
guessed at a TI CC2530, which has no Bluetooth at all and cannot be it.

So the hardware is very likely able to do BLE whatever the revision, and the
footnote in the Connect Module guide ("Bluetooth is only available on the newer
versions of the module", 231024 edition, see `docs/manuals/README.md`) is more
likely about firmware than about a missing radio. Which exact part it is, and
where the line between "newer" and older actually runs, is still unknown. No
FCC ID, no CSA certificate and no Bluetooth SIG listing exists in public under
any Onesti, Nimly, EasyAccess or ZMNC010 name, searched on 2026-09-20, and
nobody has published a teardown. The one photograph of the board is the
EasyAccess mounting guide above, and the part is under a metal RF shield in it,
so it does not settle which Nordic device it is either.

### What the module tells you about itself over Zigbee

The Basic cluster on endpoint 11 answers the version attributes. Z2M reads
them all at interview; ZHA reads only `SWBuildID`, which is cached as
`4.8.02` in the diagnostics of the Code Pro in zha-device-handlers#5235 and
missing from Fredrik's cache, most likely because his lock was asleep when
asked. From the NimlyCodePRO dump in
[Z2M#31385](https://github.com/Koenkk/zigbee2mqtt/issues/31385):

| Attribute | Name         | Value        |
| --------- | ------------ | ------------ |
| 0x0001    | AppVersion   | 13           |
| 0x0002    | StackVersion | 10           |
| 0x0003    | HWVersion    | 11           |
| 0x0006    | DateCode     | `20240625`   |
| 0x4000    | SWBuildID    | `4.8.01`     |

DateCode is a firmware build date and is the field users quote in upstream
issues. Values seen in the wild, oldest first: `20220614`, `20221114`,
`20221226`, `20230210`, `20230506`, `20230530`, `20240625`. SWBuildID uses the
same `4.x.yy` numbering as the firmware floor the BLE app enforces over GATT
characteristic 0x2A28 (4.6.0, and 4.7.90 for the model query), which makes it
the one Zigbee-side reading that speaks to BLE readiness. That the two version
strings are the same namespace is an assumption, not a verified fact.

One revision marker is already visible without reading anything: attribute
0x0101 carries the last PIN as ASCII digits on older modules and packed BCD,
two digits per byte, on newer ones
([Z2M#13080](https://github.com/Koenkk/zigbee-herdsman-converters/issues/13080),
where the reporter's newer module had DateCode `20240625`). Fredrik's lock
reports three bytes for a six-digit PIN, so it sits on the newer side of that
change.

## Network addresses

| Interface   | MAC address               | OUI                          |
| ----------- | ------------------------- | ---------------------------- |
| Ethernet    | `00:15:BC:27:D0:78`       | Develco (reg. 2005)          |
| WLAN        | `00:15:BC:27:D0:79`       | Develco (WLAN = Ethernet +1) |
| ZigBee IEEE | `00:15:BC:00:2C:11:1D:DE` | Develco                      |

## Zigbee

- **Zigbee 3.0** certified (Certificate ID: ZIG21356ZB331216-24, Dec 2021, spec 3.0.1;
  the certificate is listed on csa-iot.org as "Squid.link Gateway", Onics A/S / Frient A/S)
- Install Code: printed on the label, not reproduced here (see below)
- Role: Zigbee coordinator, pairs and controls the locks
- Gateway-to-lock protocol: Zigbee 3.0, the ZCL Door Lock cluster, the same
  thing ZHA speaks to the lock. Earlier versions of this file called it "CAS
  with AES encryption"; that came from the Ezviz camera SDK's error table in
  the app bundle and had nothing to do with the lock (see
  `docs/nimly-connect-app/reversing-notes.md`).

The install code is the one value off the label that is left out. It is 20 hex
digits, an 8-byte installation code plus its CRC16, one of the lengths Zigbee
allows (6, 8, 12 or 16 bytes and the CRC). The trust center runs it through
AES-MMO to get that device's link key, and that link key is what encrypts the
network key while the device joins. Knowing it does not stop mattering once
pairing is done: someone within radio range can force a rejoin and read the
network key out of the transport frame. It is burned in at manufacture and
cannot be rotated, only replaced along with the hub, so it stays out of a
public repo whether or not this particular hub is powered on. The other
identifiers above are a different matter and stay: the Zigbee IEEE address goes
out in the clear in every frame, the Ethernet MAC is visible to anything on the
same LAN, and the S/N only names the unit to a support desk.

The certificate covers the hub, and it is still live: a lookup by certificate
id on 2026-09-20 returns "Squid.link 2B", Onics A/S / Frient A/S, Zigbee 3.0
(`https://csa-iot.org/csa-iot_products/?p_certificate=ZIG21356ZB331216-24`).

**The lock's Connect Module has no CSA certificate of its own that we can
find.** Searched on 2026-09-20 in the Alliance's certified-products database
(`https://csa-iot.org/csa-iot_products/?p_keywords=<term>`) for `Onesti`,
`Nimly`, `ZMNC010` and `EasyAccess`. All four return "No Entries Found". The
same search form does return results for control terms (`Philips` gives
Signify's EasyAir range, and the certificate lookup above works), so the search
itself is not broken and the negative is real.

What that does and does not mean: the database is keyword-indexed on product
and company name, so a module certified under a contract manufacturer's name,
or under a product name we have not guessed, would not show up. Read it as
"no certificate found under any Onesti or Nimly name", not as "the module is
uncertified". The Connect Module manual says "Zigbee 3.0" and nothing about
certification.

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

**Both TLS certificates were re-checked on 2026-09-20 and are unchanged since
March**, with `openssl s_client -connect <host> | openssl x509 -noout -subject
-issuer -dates`. `boot-v2.onesti.io` still serves `CN=*.onesti.io` from Amazon
RSA 2048 M04, valid 2026-02-03 to 2027-03-04, so it was renewed in February and
the March capture caught the current certificate. `3.75.35.23:8883` still
serves the self-signed `CN=onesti.iotiliti.cloud` from `C=PL, O=Internet
Widgits Pty Ltd`, valid 2024-11-26 to 2034-11-24. The IPs did rotate:
`boot-v2.onesti.io` resolved to `52.29.171.113` on 2026-09-20, which is not in
the list below, while the broker answered on the same address as in March.

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

An earlier edition of this file recommended running both, ZHA for control
and the cloud through the hub for PIN setting and history. That is no longer
the plan: the hub cannot share the lock with ZHA (the lock pairs with one
coordinator), and the cloud tracks were set aside because they put the cloud
back in the path (`docs/feature-parity.md`, `docs/upstream-status.md`). The
hub is documented here so nobody has to buy one to understand the system.
