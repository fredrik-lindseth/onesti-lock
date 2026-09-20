# EasyAccess Connect Bridge: hardware and network reference

The vendor's gateway between the locks and iotiliti.cloud, written up so
nobody has to buy one to understand the system.

## Two hubs, and this file is about the older one

Onesti has sold two gateways, and "bridge" has meant both at different times.
Everything below this section describes the first one.

| | Connect Gateway | Connect Bridge |
| --- | --- | --- |
| What it is | Ethernet box, Develco Squid.link 2B, MGW211 | Plug-in unit for a wall socket, 120x45x65 mm |
| Sold as | EasyAccess Connect Bridge / EasyConnect, Nimly Connect Gateway | Nimly Connect Bridge |
| To the house | Ethernet, or WLAN | Wi-Fi 2.4 GHz, set up over Bluetooth |
| To the lock | Zigbee 3.0 | Zigbee 3.0 |
| Locks | No stated limit | Two |
| Status on nimly.se | "Utgången produkt", discontinued | Current |

The unit documented here was returned to the vendor. The serial number, the
network snapshot and the SSH behaviour below were read while it was on the
bench and cannot be re-measured. The Connect Gateway page on nimly.se is the
one that says discontinued (read 2026-09-20). The Connect Bridge page has the
wall plug, the two-lock limit and the green/red backlight, and its
installation guide is dated 17 June 2026
(`https://nimly.se/wp-content/uploads/2026/06/SE-Connect-Bridge-Installation-Guide-17062026-online.pdf`,
not yet in the `docs/manuals/` source table). The Connect Module guide writes
"Connect Gateway/Bridge" and leaves it there.

The Nimly Connect app knows both as `develco-gateway` and `nimly-gateway`,
on one shared driver, also called `develco`, with one feature set: `wlan.set`
(ssid, password, encryption), `power`, `status` (firmware version and
update) and `scan.turnOn` to open joining. A block of policy separates them,
quoted under "What else can join it". The app tells them apart by serial
number: `02000005` at the start is the Connect Bridge, anything else the
Connect Gateway. The unit here began `02000001`. The split is a single
`startsWith`, with no third prefix and no third registry entry. Model number
works the same way: `EGW01` is the Connect Bridge, anything else the Connect
Gateway. A list of gateways without "certified mode" names `EGW01` and
`MGW101-S402`, and two more lists sort the Connect Gateway's own SKUs by
cellular backup, `MGW101-DP03/DP06/DP09`, `MGW101-EAS1` through `EAS4` and
`MGW101-KEY1/KEY2` without a SIM against `MGW101-S402` with eSIM only. The
`EAS` and `KEY` suffixes match EasyAccess and Keyfree. `MGW211` appears
nowhere in the app.

The Connect Bridge entry is recent. Of the thirteen white-label builds in
`reversing/apks/`, only 1.27.23 and newer carry `nimly-gateway`, `EGW01` and
the `02000005` prefix; 1.25.62 and older know `develco-gateway` alone. The
same builds gained the two screens that set the Bridge's Wi-Fi over
Bluetooth, `NimlyGatewayWifiProvisioningBleScan` and
`…Networks`. `storeGatewaySaga` opens them only when the registered gateway's
model id is the Nimly one; the Connect Gateway is wired and skips them.

## Brand hierarchy (white-label)

One system, three names: the label on the hub says "EasyAccess Easy Living",
the module in the lock says "E-Life 3.0", and the app is "Nimly Connect".

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

| Field   | Value                            |
| ------- | -------------------------------- |
| Brand   | E-Life                           |
| Version | 3.0                              |
| Article | ZMNC010, EAN 5704571842582       |
| Role    | Zigbee and BLE radio in the lock |

The module is sold on its own, under the same EAN at every Nordic retailer
checked on 2026-09-20: Copiax 50461903, Staypro 3131023, Elektroimportøren
5800460, Ahlsell 5868052, Dustin 5011307956, Clas Ohlson 41-8237-1. No second
EAN or article number turned up, so the trade does not track module
revisions. You cannot order a particular one.

### Where "E-Life" comes from

E-Life is Onesti's name for the module, printed in white silkscreen on the
module board. It is not a Zigbee attribute: the Basic cluster answers "Onesti
Products AS" for ManufacturerName and the lock model ("NimlyPRO",
"EasyFingerTouch", "easyCodeTouch_v1") for ModelIdentifier, and neither the
decompiled apps, the cloud API nor any vendor manual mentions E-Life. Read it
off the board, or not at all.

EasyAccess's mounting guide photographs the mark: `e-Life` in white on the
black module board, right of the RF shield, with a small logo after it, on a
green lock mainboard silkscreened `MODULE` at the connector, `KEY` below and
`PL943_Back05 2020.06.02` along the edge
(`https://easyaccess.no/wp-content/uploads/2021/04/ZigBee-modul-montering.pdf`,
kept in `docs/manuals/`, rendered at 500 dpi and read 2026-09-20). An older
note in this project put the word on the mainboard; the close-up says module.
Whether the `3.0` on Fredrik's module is a module generation or just "Zigbee
3.0" is unknown; the 2021 photo shows no version after the name. That module
has one visible LED, lit blue, next to the button; the 2024 guide's drawing
shows two.

The name also titles the vendor's Zigbee spec, *E-life Zigbee Modul User
Manual v2.0*, written in Word by Andrea Birkheim on 2021-01-26 and posted by a
customer in [Z2M#6379](https://github.com/Koenkk/zigbee2mqtt/issues/6379) on
2021-02-20
(`https://github.com/Koenkk/zigbee2mqtt/files/6015013/E-life.Zigbee.Modul.User.Manual.v2.0.pdf`).
It is the only vendor-written description of the Zigbee side we have, and
`v2.0` is the manual's version, not the module's. Summarised in
`docs/zigbee-protocol/elife-module-spec.md`.

### Which silicon

The EUI64 of every Onesti lock seen in public issues from 2021 to 2026 starts
with `f4:ce:36`, which the IEEE registry assigns to Nordic Semiconductor ASA.
Fredrik's lock (`f4:ce:36:88:61:9c:f4:6f`), the NimlyCodePRO interview in
[Z2M#31385](https://github.com/Koenkk/zigbee2mqtt/issues/31385), the addresses
in Z2M issues 14726, 17205, 18508, 19627, 19738, 23551 and 32772, and the
EasyCodeTouch in the March 2021 deCONZ sniff (`f4:ce:36:32:a2:96:09:ab`,
`docs/manuals/`) are all in that range. The node descriptor agrees: 4660
(0x1234) is the manufacturer code an unconfigured ZBOSS stack reports, and
ZBOSS is the Zigbee stack in Nordic's nRF Connect SDK, so the vendor never
set its own. The only Nordic parts with an 802.15.4 radio are the nRF52840,
nRF52833 and nRF5340, and all three have Bluetooth LE on the same die. An
earlier note here guessed at a TI CC2530, which has no Bluetooth and cannot
be it.

So the hardware can very likely do BLE whatever the revision, and the
footnote in the Connect Module guide ("Bluetooth is only available on the
newer versions of the module", 231024 edition, `docs/manuals/README.md`) is
more likely about firmware than a missing radio. Which part it is, and where
"newer" begins, is unknown. No FCC ID, CSA certificate or Bluetooth SIG
listing exists in public under any Onesti, Nimly, EasyAccess or ZMNC010 name
(searched 2026-09-20), and nobody has published a teardown. The one board
photo is the mounting guide above, and the part is under an RF shield in it.

### What the module tells you about itself over Zigbee

The Basic cluster on endpoint 11 answers the version attributes. Z2M reads
them all at interview; ZHA reads only `SWBuildID`, cached as `4.8.02` in the
Code Pro diagnostics in zha-device-handlers#5235 and missing from Fredrik's
cache, most likely because his lock was asleep when asked. From the
NimlyCodePRO dump in [Z2M#31385](https://github.com/Koenkk/zigbee2mqtt/issues/31385):

| Attribute | Name         | Value      |
| --------- | ------------ | ---------- |
| 0x0001    | AppVersion   | 13         |
| 0x0002    | StackVersion | 10         |
| 0x0003    | HWVersion    | 11         |
| 0x0006    | DateCode     | `20240625` |
| 0x4000    | SWBuildID    | `4.8.01`   |

DateCode is a firmware build date and the field users quote upstream. Seen so
far, oldest first: `20220614`, `20221114`, `20221226`, `20230210`,
`20230506`, `20230530`, `20240625`. SWBuildID uses the same `4.x.yy` scheme
as the firmware floor the BLE app enforces over GATT characteristic 0x2A28
(4.6.0, and 4.7.90 for the model query), which makes it the one Zigbee-side
reading that says anything about BLE readiness. That the two version strings
share a namespace is an assumption.

One revision marker needs no read at all: attribute 0x0101 carries the last
PIN as ASCII digits on older modules and packed BCD on newer ones
([Z2M#13080](https://github.com/Koenkk/zigbee-herdsman-converters/issues/13080),
where the newer module had DateCode `20240625`). Fredrik's lock sends three
bytes for a six-digit PIN, so it is on the newer side.

## Network addresses

| Interface   | MAC address               | OUI                          |
| ----------- | ------------------------- | ---------------------------- |
| Ethernet    | `00:15:BC:27:D0:78`       | Develco (reg. 2005)          |
| WLAN        | `00:15:BC:27:D0:79`       | Develco (WLAN = Ethernet +1) |
| ZigBee IEEE | `00:15:BC:00:2C:11:1D:DE` | Develco                      |

## Zigbee

Zigbee 3.0 certified: certificate ZIG21356ZB331216-24, Dec 2021, spec 3.0.1,
listed on csa-iot.org as "Squid.link Gateway", Onics A/S / Frient A/S. The
lookup still returns it on 2026-09-20
(`https://csa-iot.org/csa-iot_products/?p_certificate=ZIG21356ZB331216-24`).
The hub is the Zigbee coordinator, and it speaks the ZCL Door Lock cluster to
the lock, the same thing ZHA does. Earlier versions of this file called that
"CAS with AES encryption"; the term came from the Ezviz camera SDK's error
table in the app bundle and has nothing to do with the lock
(`docs/nimly-connect-app/reversing-notes.md`).

The install code on the label is the one value left out. It is 20 hex
digits, an 8-byte code plus CRC16 (Zigbee allows 6, 8, 12 or 16 bytes plus
CRC). The trust center hashes it with AES-MMO into the device's link key,
which encrypts the network key during the join. It keeps mattering after
pairing: someone in radio range can force a rejoin and read the network key
out of the transport frame. It is burned in at manufacture and can only be
replaced with the hub, so it stays out of a public repo whether or not this
unit is powered on. The other identifiers stay: the Zigbee IEEE goes out in
the clear in every frame, the Ethernet MAC is visible on the LAN, and the S/N
only names the unit to a support desk.

The lock's Connect Module has no CSA certificate we can find. The Alliance's
database (`https://csa-iot.org/csa-iot_products/?p_keywords=<term>`) returns
"No Entries Found" for `Onesti`, `Nimly`, `ZMNC010` and `EasyAccess`
(2026-09-20). Control terms work (`Philips` gives Signify's EasyAir range, and
the certificate lookup above resolves), so the negative is real. It is also
narrow: the index is keyed on product and company name, so a module certified
under a contract manufacturer or an unguessed product name would not show.
Read it as "no certificate under any Onesti or Nimly name", not "uncertified".
The module manual says "Zigbee 3.0" and nothing about certification.

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

Any 9V/2A center-positive 5.5x2.1mm adapter will do as a replacement.

## Physical

White plastic box, about 10x10 cm, four rubber feet with screws over the
PCB, bracket slots on the back for wall mounting. Ports: RJ45 Ethernet and a
USB-A of unknown purpose (debug or serial?). A QR code on the back, likely
the install code or S/N for the app, and a Data Matrix on the box with PN and
S/N. Label certifications: CE, RoHS, FCC.

## Software stack (from network analysis)

| Component | Version/Detail                                                 |
| --------- | -------------------------------------------------------------- |
| OS        | Embedded Linux ("HomeGate AIO"), likely Yocto/Buildroot        |
| SSH       | Dropbear 2020.81 (ED25519 host key, publickey-only auth)       |
| TLS       | OpenSSL 1.1.1+ or 3.x (supports TLS 1.0-1.3, 31 cipher suites) |
| NTP       | NTPv4 (syncs from 0-3.pool.ntp.org)                            |
| mDNS      | Advertises `gw-{SERIAL}._ssh._tcp.local`                       |
| Webserver | None (port 80/443 closed)                                      |

SSH is open for about 60 seconds during boot and closes once the firmware is
loaded. Public keys only, so it is out of reach unless you can add your own.

## Network communication

Observed once, in a Wireshark capture of the hub's boot at the end of March
2026. IPs rotate and certificates get renewed, so the addresses and dates are
a snapshot.

Both TLS certificates were re-checked on 2026-09-20 with `openssl s_client
-connect <host> | openssl x509 -noout -subject -issuer -dates` and are
unchanged. `boot-v2.onesti.io` serves `CN=*.onesti.io` from Amazon RSA 2048
M04, valid 2026-02-03 to 2027-03-04, so the March capture caught the current
certificate. `3.75.35.23:8883` serves the self-signed
`CN=onesti.iotiliti.cloud` from `C=PL, O=Internet Widgits Pty Ltd`, valid
2024-11-26 to 2034-11-24. The IPs did rotate: `boot-v2.onesti.io` resolved to
`52.29.171.113` on 2026-09-20, which is not in the list below, while the
broker answered on the March address.

### Boot sequence

1. DHCP: IP, hostname `gw-4433`, Vendor Class `HomeGate AIO`
2. mDNS: advertises `gw-4433.local` and `gw-4433._ssh._tcp.local` (port 22)
3. DNS: `boot-v2.onesti.io`
4. NTP: `0-3.pool.ntp.org`
5. TLS: `boot-v2.onesti.io` (HTTPS, TLS 1.3)
6. MQTT: persistent connection to the broker (port 8883, TLS 1.3)

About 50 seconds from power to the MQTT connection.

### Boot/provisioning endpoint

| Field     | Detail                                                                        |
| --------- | ----------------------------------------------------------------------------- |
| Hostname  | `boot-v2.onesti.io`                                                           |
| IPs       | `3.127.252.118`, `52.29.36.20`, `63.179.222.106` (AWS eu-central-1, rotating) |
| Protocol  | HTTPS (TLS 1.3, AES-128-GCM), HTTP/2                                          |
| TLS cert  | `CN=*.onesti.io`, issuer Amazon RSA 2048 M04, valid until 2027-03-04          |
| `/health` | `200 OK` with `{}` (Hapi/NestJS style)                                        |
| All other | `404`, likely needs a gateway ID or token in path or headers                  |

### MQTT broker

| Field            | Value                                                            |
| ---------------- | ---------------------------------------------------------------- |
| IP               | `3.75.35.23` (AWS eu-central-1)                                  |
| Port             | 8883 (MQTT over TLS 1.3, AES-128-GCM)                            |
| TLS cert Subject | `CN=onesti.iotiliti.cloud`                                       |
| TLS cert Issuer  | `C=PL, ST=Some-State, O=Internet Widgits Pty Ltd` (self-signed)  |
| Cert validity    | 2024-11-26 to 2034-11-24                                         |
| rDNS             | `ec2-3-75-35-23.eu-central-1.compute.amazonaws.com`              |

The certificate is self-signed with OpenSSL's default subject fields and the
country set to Poland. The hub carries the CA hardcoded and does not check
public CAs, so replacing the CA on the hub would allow a MITM of the MQTT
traffic.

### REST API

The hub was never seen talking to the REST API. The app does, at
`api-neutralclone.iotiliti.cloud` for Nimly (Connect v1.27.84) or
`api.customer.prod-neutralclone.onesti.aws.neurosys.pro` (newer builds). The
per-brand table is in `docs/nimly-connect-app/reversing-notes.md`, the
white-label overview in `docs/nimly-connect-app/app-architecture.md`.

### The whole chain

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

Plus DNS. Nothing else is needed.

## Firmware update

On first boot, or after a factory reset, the hub shows "please wait, the
gateway will now run and update to the latest software version before
rebooting...". The update runs from internal flash, needs no network, and
reboots after 5-10 minutes. LEDs: blinking green, then solid green (power),
then solid green (left button) when done. After the reboot the hub connects
to MQTT and the app shows "gateway online".

The app can also trigger an update: "installing updates - downloading 97%",
then "completing - the gateway is installing the update and will do a
restart".

## Pairing a lock with the hub

The lock pairs with one Zigbee coordinator at a time. If it is on ZHA or
Zigbee2MQTT, remove it there first:

1. HA → Settings → Devices & Services → ZHA → the lock → ⋮ → Remove
2. Wake the lock (press the keypad) before pressing Remove
3. Factory reset the module: hold its reset button for 10+ seconds
4. Rapid LED blink means pairing mode
5. Open Nimly Connect → add device → "searching for devices"

The hub has short Zigbee range and the lock body shields the radio, so put the
hub as close to the lock as possible while pairing.

## What else can join it

Three owner claims were checked on 2026-09-20: that the hub takes nothing but
Onesti locks, that Home Assistant cannot reach it, and that there is a "pro
hub" you cannot buy. The first is app and firmware policy, not a hardware
limit. The second holds. The third is a product that does not exist.

The hardware is a general gateway. Onics (Develco Products' current name)
lists the Squid.link 2B with Zigbee 3.0, Z-Wave Plus, Bluetooth and BLE,
sub-GHz Wireless M-Bus and 2.4 GHz WLAN on the device side, and Ethernet,
WLAN or LTE towards the house (`https://onics.com/products/squid-link-2b`,
read 2026-09-20). They sell the platform into alarm, care, insurance and
metering.

The app is what narrows it. The Nimly Connect bundle carries a vendor list
that is not a lock list: Develco, Frient, Climax, Datek, Namron, ELKO,
Schneider Electric, IKEA of Sweden, OSRAM, Heiman, D-Link, Aeotec, Reolink,
Fireangel and Safe4 next to Onesti, Nimly, EasyAccess, Danalock, ID Lock,
ASSA ABLOY and Dormakaba, with device-type groups for bulbs, motion, window,
vibration and air-quality sensors, sirens, smart plugs and alarm zones. That
is the Safe4 alarm platform shipped whole inside a door-lock app.

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
`isDeviceTypeWhitelistedForVendorOnGateway`,
`isAccessTypeLimitReachedOnGateway` and `isLocationTypeSupportedByGateway`,
each of which allows when the field is absent. So the newer Connect Bridge is
fenced to Nimly-branded devices, two locks and three smart plugs, with alarm
and event log off, while the older Connect Gateway has no fence in the app
and those flags on.

Nobody has tried it. No one in the archive reports adding a third-party
Zigbee device to either hub, and no vendor page or manual invites it: the
product texts describe both hubs only as a way to run the locks from the app,
and the Connect Bridge page states the two-lock limit. The smart-plug
allowance is the one place the vendor's own configuration admits to something
that is not a lock. Read the table as where the restriction lives, not as a
promise that an IKEA bulb will join.

## Talking to it from Home Assistant

It cannot be done, and as of 2026-09-20 nobody has reported doing it.

Nothing local is offered: no web server (80 and 443 closed), no local REST,
no local MQTT. The only listening service is SSH, open for about 60 seconds at
boot and public-key only. The decompiled Nimly Connect bundle has no mDNS, no
Bonjour, no LAN discovery and no local address of any kind. Every path is
phone → iotiliti cloud → MQTT → hub → Zigbee.

Onics documents a "RESTful API for gateway configuration and control" in the
Squid Smart App layer
(`https://onics.com/gateway-software/squid-platform-software`, read
2026-09-20). Whether that is reachable on the LAN or only from the operator's
backend is not stated, and the closed ports say Onesti's firmware does not put
it on the network. Untested either way.

Two people in the Home Assistant thread asked whether the gateway could be
integrated instead of the lock, in November 2023 and December 2024. Neither
got an answer. A third asked on the Homey forum, and the app author replied
that the Homey app talks Zigbee to the lock because the gateway offers no
cloud path. Searches of the Home Assistant, Homey, openHAB and Hubitat forums
and of GitHub for the hub, `MGW211`, Squid.link and iotiliti return nothing.
Two Swedish forums and Reddit could not be searched, so this is "not found",
not "proven absent".

That is why the hub is not an option for this integration: the lock joins one
Zigbee network at a time, so it cannot be shared with ZHA, and the hub cannot
be reached without the vendor's cloud.

## The "pro hub"

No such product. Nothing called "Connect Bridge Pro", "Connect Gateway Pro"
or "Nimly hub Pro" exists on nimly.se, nimly.no or easyaccess.no, at any
Nordic retailer, in any manual, in the app or anywhere the 105 archived
sources reach. In the shop "Pro" belongs to lock models, Touch Pro and Code
Pro; inside the app it is also what the discontinued Connect Gateway is
called. The app's gateway registry holds exactly two entries, both above.

Four nearby things could be mistaken for it:

- The older hub is the more capable one, and the one you cannot buy. The
  Connect Gateway has alarm, automation and event log and no device limits;
  the Connect Bridge that replaced it is capped at two locks with those off,
  and nimly.se marks the Connect Gateway "utgången produkt". An owner told
  that the better hub exists, then unable to order it, has it right, with the
  tiers the opposite way round from a usual "pro" model. The app's two
  install texts are `proGateway`, "PRO Gateway", power and an Ethernet cable,
  and `nimlyBundleGateway`, "nimly Connect Bridge", a QR code and a wall
  socket. One string names a capability the Bridge lacks: "This access will
  have unlimited validity. You must have a PRO gateway to be able to create
  time-limited access."
- `NimlyGatewayWifiPro`, which turns up in a string dump of the Homely build
  next to model ids. It is a cut-off `NimlyGatewayWifiProvisioningBleScan`,
  a screen name, not a model. The full string table has only the two route
  names, and the code uses them as navigation targets.
- Homey Pro. A real hub from another company, and one of the third-party
  systems Nimly's Connect Module page points at. Not sold by Nimly, which
  explains not finding it in their shop.
- Squid.link 2X. Onics sells a higher tier than the 2B, with more memory and
  a Matter-ready update path. Nothing ties it to Onesti: no Nimly or
  EasyAccess product is built on it, and none is announced.

## Relevance for the HA integration

The integration does not need the hub; ZHA talks to the lock directly. The
hub is only needed for the Nimly Connect app, the iotiliti REST API, PIN
setting via the cloud (which sidesteps the sleepy-device timeout) and event
history via the cloud.

An earlier edition recommended running both, ZHA for control and the cloud
for PIN setting and history. That plan is dropped: the lock pairs with one
coordinator, so the hub cannot share it with ZHA, and the cloud tracks were
set aside because they put the cloud back in the path
(`docs/feature-parity.md`, `docs/upstream-status.md`).
