# EasyAccess Connect Bridge: hardware and network reference

Gateway for Nimly/EasyAccess locks, bridging Zigbee devices to iotiliti.cloud.
Documented so nobody needs to buy the hub to understand the system.

## Two hubs, and this file is about the older one

Onesti has sold two gateways, and "bridge" has meant both of them at different
times. Everything below the next section describes the first one.

| | Connect Gateway | Connect Bridge |
| --- | --- | --- |
| What it is | Ethernet box, Develco Squid.link 2B, MGW211 | Plug-in unit for a wall socket, 120x45x65 mm |
| Sold as | EasyAccess Connect Bridge / EasyConnect, Nimly Connect Gateway | Nimly Connect Bridge |
| To the house | Ethernet, or WLAN | Wi-Fi 2.4 GHz, set up over Bluetooth |
| To the lock | Zigbee 3.0 | Zigbee 3.0 |
| Locks | No stated limit | Two |
| Status on nimly.se | "Utgången produkt", discontinued | Current |

Fredrik's unit is the first one. The Nimly product page for the Connect
Gateway is the one that says discontinued, read 2026-09-20; the Connect Bridge
page is the one with the wall plug, the two-lock limit and the green/red
backlight, and its installation guide is dated 17 June 2026
(`https://nimly.se/wp-content/uploads/2026/06/SE-Connect-Bridge-Installation-Guide-17062026-online.pdf`,
not yet in the `docs/manuals/` source table). The vendor's own Connect Module guide hedges by writing
"Connect Gateway/Bridge" and leaving it there.

The Nimly Connect app carries both, and calls them `develco-gateway` and
`nimly-gateway`. They share one driver, also called `develco`, and one feature
set: `wlan.set` with ssid/password/encryption, `power`, `status` with
firmware version and update, and `scan.turnOn` to open joining. What separates
them is a block of policy, quoted under "What else can join it" below. The app
picks between them by serial number: one beginning `02000005` is the Connect
Bridge, anything else the Connect Gateway. Fredrik's begins `02000001`.

The app also knows one model number per hub: `EGW01` is the Connect Bridge,
and a list of gateways without "certified mode" names `EGW01` and
`MGW101-S402`. `MGW211` appears nowhere in the app.

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

## What else can join it

Three owners' claims about the hub were checked on 2026-09-20: that it takes
nothing but Onesti locks, that Home Assistant cannot reach it, and that there
is a "pro hub" you cannot buy. The first is a firmware and app policy, not a
hardware limit. The second holds. The third is a product that does not exist.

The hardware is a general gateway. Onics, which is what Develco Products is
called now, lists the Squid.link 2B with Zigbee 3.0, Z-Wave Plus, Bluetooth
and BLE, sub-GHz Wireless M-Bus and 2.4 GHz WLAN on the device side, and
Ethernet, WLAN or LTE towards the house
(`https://onics.com/products/squid-link-2b`, read 2026-09-20). Their own
description of the family is that it bridges "wireless devices across
communication protocols and brands", and they sell the platform into alarm,
care, insurance and metering, where the devices are not door locks.

What narrows it is the app. The Nimly Connect bundle carries a vendor list of
its own, and it is not a lock list: Develco, Frient, Climax, Datek, Namron,
ELKO, Schneider Electric, IKEA of Sweden, OSRAM, Heiman, D-Link, Aeotec,
Reolink, Fireangel and Safe4 stand next to Onesti, Nimly, EasyAccess,
Danalock, ID Lock, ASSA ABLOY and Dormakaba. Next to it sit device-type
groups for bulbs, motion, window, vibration and air-quality sensors, sirens,
smart plugs and alarm zones. That is the Safe4 alarm platform, shipped whole
inside a door-lock app.

Each gateway model then gets a policy object, and this is where the two hubs
part:

| Policy field | Connect Gateway (`develco-gateway`) | Connect Bridge (`nimly-gateway`) |
| --- | --- | --- |
| `vendor` | Onesti Products AS | nimly |
| `alarmSupported` | true | false |
| `automationSupported` | true | false |
| `eventLogSupported` | true | false |
| `enabledVendors` | not set | nimly only |
| `hiddenVendors` | not set | EasyAccess |
| `doorLocksLimit` | not set | 2 |
| `smartplugsLimit` | not set | 3 |
| `doorLockAccessTypeLimits` | not set | 20 each of PIN, tag, finger |
| `locationTypeBlacklist` | not set | apartment buildings |
| `doorLockRulesDisabled` | not set | true |

The app reads those through `isVendorEnabledOnGateway`,
`isDeviceTypeWhitelistedForVendorOnGateway`, `isAccessTypeLimitReachedOnGateway`
and `isLocationTypeSupportedByGateway`, and each one returns "allowed" when the
field is absent. So the newer Connect Bridge is fenced by name to Nimly-branded
devices, two locks and three smart plugs, with the alarm and event-log half of
the platform switched off, while the older Connect Gateway has no fence in the
app at all and the alarm, automation and event-log flags on.

Which does not mean anyone has done it. Nobody in the archive has reported
adding a third-party Zigbee device to either hub, and no vendor page or manual
invites it: Nimly's own product texts describe both hubs only as a way to run
your locks from the Nimly Connect app, and the Connect Bridge page names the
two-lock limit outright. The smart-plug allowance is the one place the vendor's
own configuration admits to something that is not a lock. Read the table as
where the restriction lives, not as a promise that an IKEA bulb will join.

## Talking to it from Home Assistant

It cannot be done, and as of 2026-09-20 nobody has reported doing it.

Nothing local is offered. No web server (ports 80 and 443 closed), no local
REST, no local MQTT; the only listening service is SSH, and that is open for
about 60 seconds at boot and takes public keys only. The app does not help
either: the decompiled Nimly Connect bundle contains no mDNS, no Bonjour, no
LAN discovery and no local address of any kind. Every path from the phone to
the lock goes phone → iotiliti cloud → MQTT → hub → Zigbee.

Onics documents the Squid.link platform as having a "RESTful API for gateway
configuration and control" in its Squid Smart App layer
(`https://onics.com/gateway-software/squid-platform-software`, read
2026-09-20). Whether that is reachable on the LAN or only from the operator's
own backend is not stated, and the closed ports on this unit say Onesti's
firmware does not put it on the network. Untested either way.

Two people in the Home Assistant thread asked directly whether the gateway
could be integrated instead of the lock, in November 2023 and December 2024.
Neither got an answer. A third asked the same on the Homey forum, and the app
author's reply was that the Nimly app for Homey talks Zigbee to the lock,
because no cloud path through the gateway is offered. Searches of the Home
Assistant, Homey, openHAB and Hubitat forums and of GitHub for the hub, for
`MGW211`, for Squid.link and for iotiliti return nothing at all. Two Swedish
forums and Reddit could not be searched, so this is "not found", not "proven
absent".

That is also why the hub is not an option for this integration. It cannot be
shared with ZHA, since the lock joins one Zigbee network at a time, and it
cannot be reached without the vendor's cloud.

## The "pro hub"

No such product. There is no "Connect Bridge Pro", "Connect Gateway Pro" or
"Nimly hub Pro" on nimly.se, nimly.no or easyaccess.no, at any Nordic
retailer, in any manual, in the app or anywhere the 105 archived sources
reach. The word "pro" in this family belongs to lock models, Touch Pro and
Code Pro. The app's own gateway registry holds exactly two entries, both
covered above.

Three things nearby could be mistaken for it, and are worth naming so the
question does not come back:

- **The older hub is the more capable one, and it is the one you cannot
  buy.** The Connect Gateway carries alarm, automation and event log and no
  device limits, the Connect Bridge that replaced it is capped at two locks
  with those features off, and nimly.se marks the Connect Gateway
  "utgången produkt". An owner told that the better hub exists, and then
  unable to order it, has the situation exactly right, only with the tiers
  the other way round from how a "pro" model usually works.
- **Homey Pro.** A real hub, from a different company, and one of the
  third-party systems Nimly's own Connect Module page points at. "Buy a pro
  hub and get more out of the lock" is a fair description of it, and it is
  not sold by Nimly, which would explain not finding it in their shop.
- **Squid.link 2X.** Onics does sell a higher tier than the 2B, with more
  memory and a Matter-ready update path. Nothing ties it to Onesti: no
  Nimly or EasyAccess product is built on it, and nobody has announced one.

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
