# Observed locks: model string, radio and firmware per report

A running log of individual locks seen in public issues and on Fredrik's own
door, one row per report. The point is that a new lock or a new issue can be
filled in as a new row without rewriting the rest: pull the Zigbee model
string, the IEEE prefix (first three bytes of the EUI64, the manufacturer's
OUI block), and whatever Basic cluster attributes (`DateCode`, `HWVersion`,
`SWBuildID`) the report happens to include, and cite the issue number and
date.

The OUI is what actually separates hardware generations, not the firmware
DateCode: everything below with `ManufacturerName` "Onesti Products AS" and
Basic cluster `HWVersion` 11 sits on the `f4:ce:36` block, and the DateCode
values seen there (`20220614` through `20240625`) are firmware builds on the
same radio, not a hardware change. `EasyCode903G2.1` is the one report on a
different OUI, a different `ManufacturerName`, and a module the Onesti/E-Life
line never mentions.

OUI lookups below are from [IEEE's public MA-L registry](https://standards-oui.ieee.org/),
cross-checked on 2026-09-20 against two independent mirrors
(`maclookup.app`, `macvendors.com`), which agreed. `docs/connect-bridge/hardware-gateway.md`
has the fuller writeup of the Nordic silicon question (which exact part) and
a longer list of `f4:ce:36` sightings; this table exists for the report-level
detail (dateCode, hwVersion, swBuildId) and to keep the odd-one-out report on
record.

| Model string       | IEEE prefix (OUI) | OUI holder (IEEE registry)              | Module name           | DateCode   | HWVersion | SWBuildID | Source |
| ------------------ | ------------------ | ---------------------------------------- | ---------------------- | ---------- | --------- | --------- | ------ |
| NimlyPRO            | `f4:ce:36`          | Nordic Semiconductor ASA (Trondheim, NO) | E-Life 3.0 (silkscreen) | not read[^zha] | not read[^zha] | not read[^zha] | Fredrik's own lock, `f4:ce:36:88:61:9c:f4:6f` (also documented in `docs/connect-bridge/hardware-gateway.md`) |
| easyCodeTouch_v1    | not stated in issue | — (no device dump; manual attachment only) | E-Life Zigbee Modul v2.0 (manual title) | `20201211` or newer (manual's documented default, not a live report) | 11 or higher (manual's documented default) | not set as of 2021 (manual) | [Z2M#6379](https://github.com/Koenkk/zigbee2mqtt/issues/6379), 2021-02-20 |
| EasyCodeTouch (model string not in the capture) | `f4:ce:36` | Nordic Semiconductor ASA (Trondheim, NO) | not visible | not read | not read | not read | [deCONZ#4253](https://github.com/dresden-elektronik/deconz-rest-plugin/issues/4253) sniff, 2021-03-07, `f4:ce:36:32:a2:96:09:ab`; no 0x0100/0x0101 traffic at all in five minutes (`docs/zigbee-protocol/zigbee-captures.md`) |
| NimlyCodePRO        | `f4:ce:36`          | Nordic Semiconductor ASA (Trondheim, NO) | not named in this issue | `20240625` | 11        | `4.8.01`  | [Z2M#31385](https://github.com/Koenkk/zigbee2mqtt/issues/31385), 2026-03-13 |
| NimlyCodePRO        | redacted by ZHA in the dump | — | not named in this issue | not read | not read (OTA query carries `hardware_version 52`, a different field) | `4.8.02` | [zha-device-handlers#5235](https://github.com/zigpy/zha-device-handlers/issues/5235), 2026-08-07, ZHA diagnostics kept in `docs/manuals/` |
| Nimly Doorlock (generic `definition`) | not stated in issue | — (no device dump; bug report only) | not named in this issue | `20240625` | not stated | not stated | [zigbee-herdsman-converters#13080](https://github.com/Koenkk/zigbee-herdsman-converters/issues/13080), 2026-09-02 |
| **EasyCode903G2.1** | **`00:0d:6f`**      | **Ember Corporation** (acquired by Silicon Labs in 2012; Boston, MA, US) | **Dream V1.0** (per reporter) | not in the log (interview completed, but Z2M 1.17.1 published no date code for it) | not in the log | not in the log | [Z2M#6551](https://github.com/Koenkk/zigbee2mqtt/issues/6551), 2021-03-03, log kept in `docs/manuals/` |

[^zha]: ZHA does not read `AppVersion`, `HWVersion` or `DateCode`, which is
    why Fredrik's ZHA cache has none of them; Z2M reads the whole set at
    interview. `SWBuildID` (0x4000) is the exception: the ZHA diagnostics of
    the Code Pro in zha-device-handlers#5235 have it cached as `4.8.02`, so
    something in ZHA or its quirk does ask for it, and Fredrik's cache lacks
    it most likely because the lock was asleep when it was asked. An earlier
    edition of this footnote said ZHA never reads any of them.

## What `EasyCode903G2.1` actually is

[Z2M#6551](https://github.com/Koenkk/zigbee2mqtt/issues/6551) is a lock the
reporter calls "Easyfinger" (linking to
`https://easyaccess.no/product/easyfinger-v2/`), running a Zigbee module the
reporter names "Dream V1.0". Over Zigbee it answers `ManufacturerName`
**"Datek Wireless"**, not "Onesti Products AS", and `ModelIdentifier`
`EasyCode903G2.1`. Its IEEE address `00:0d:6f:00:0c:71:f2:cb` sits in the
`00:0d:6f` block, IEEE-registered to **Ember Corporation**, absorbed into
Silicon Labs in 2012 — a different silicon vendor from the Nordic
Semiconductor part (`f4:ce:36`) every other row above, and every sighting
catalogued in `docs/connect-bridge/hardware-gateway.md`, uses.

The Z2M log attached to that issue (`log1.txt`, kept in `docs/manuals/`)
shows the interview completing on **endpoint 1**, not 11, with Basic, Power
Configuration, Identify, Groups, Scenes and Door Lock as input clusters,
Identify and OTA as output clusters, and no manufacturer-specific cluster.
The Onesti module sits on endpoint 11 and carries 0xFEA2 ("EA v2" in the
vendor spec), so the two differ in layout as well as in silicon.

That manufacturer name is also why this integration would never find such a
lock: `zha.py`'s `iter_onesti_locks()` only offers ZHA devices whose
`ManufacturerName` equals `MANUFACTURER` ("Onesti Products AS", `const.py`).
A "Datek Wireless" device fails that filter before the model string is even
looked at, whatever `SUPPORTED_MODELS` contains. No Z2M or ZHA converter has
ever added support for `EasyCode903G2.1` either; the 2021 issue has no
follow-up.

This looks like an older or third-party OEM Zigbee module EasyAccess used
before standardising on Onesti's own E-Life module, rather than a variant of
the hardware this integration targets. Treat it as a different, unsupported
product line, not as evidence that Onesti locks come in two Zigbee
generations: every confirmed Onesti Products AS report, from 2021's manual
attachment to Fredrik's own lock, is consistent with one hardware generation
on the `f4:ce:36` Nordic block.

## One hardware generation, more than one firmware

The firmware on the Nordic module has changed in ways that matter to this
integration. `SWBuildID` is the handle, not `DateCode`: the user reports in
[community-reports.md](community-reports.md#firmware-versions-people-report)
put builds 4.7.79, 4.7.98 and 4.8.01 all on DateCode `20240625`, and the
build ladder people quote runs 4.5.24, 4.5.26, 4.7.78, 4.7.79, 4.7.98,
4.8.01, 4.8.02. Every newer build reached a user as a replacement module in
the post, never over the air. What has changed along that ladder:

- The 2021 vendor spec (`docs/zigbee-protocol/elife-module-spec.md`) lists
  no attribute 0x0100 or 0x0101, and the March 2021 deCONZ sniff of a lock on
  the same OUI shows five minutes of lock-state reports with no
  manufacturer-specific frame at all. The operation event this integration
  decodes arrived in a later firmware. Which build first carries it is not
  known. The author of the ZHA quirk that decodes 0x0100 ran build 4.5.26
  before upgrading (community-reports.md), so it is there from 4.5.x at the
  latest; the sniffed 2021 lock's build is unknown.
- Bluetooth on the module was "under development" in the summer of 2022
  according to EasyAccess support, as relayed by a user
  (community-reports.md), which is the earliest date anyone has put on the
  guide's "newer versions of the module". A separate, older Bluetooth
  accessory for the EasyCode line was a plain GPIO bridge with no protocol at
  all, so "Bluetooth module" in old forum posts is not this module.
- Attribute 0x0101 carries the last PIN as ASCII digits on older firmware and
  packed BCD on newer (Z2M#13080); Fredrik's NimlyPRO and the Code Pro in
  zha-device-handlers#5235 (build `4.8.02`) both send BCD.
- The source byte in 0x0100 differs: Fredrik's NimlyPRO sends `0x00` and
  `0x0A`, the Code Pro on `4.8.02` and a NimlyPRO24 send `0x05` for the same
  situations (`docs/zigbee-protocol/zigbee-captures.md`).

A lock on 2021-era firmware would pair, expose a Door Lock cluster and be
offered by the config flow, and then never produce an activity event. No
such report has come in, but nothing in the code would tell such a user what
is wrong.

`EasyCode903G2` (no trailing `.1`) is a different string: it is the
`ModelIdentifier` default documented in Onesti's own 2021 module spec
(`docs/zigbee-protocol/elife-module-spec.md`), next to `easyCodeTouch_v1`, for
a device whose `ManufacturerName` the same spec documents as "Onesti Products
AS". Nobody has reported a lock answering it yet, but it passes the
integration's manufacturer filter and is listed in `SUPPORTED_MODELS` on that
basis. Whether it maps to a still-sold product, and whether it is the same
hardware family as `EasyCode903G2.1` under a coincidentally similar name, is
unknown.
