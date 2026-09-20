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
| NimlyCodePRO        | `f4:ce:36`          | Nordic Semiconductor ASA (Trondheim, NO) | not named in this issue | `20240625` | 11        | `4.8.01`  | [Z2M#31385](https://github.com/Koenkk/zigbee2mqtt/issues/31385), 2026-03-13 |
| Nimly Doorlock (generic `definition`) | not stated in issue | — (no device dump; bug report only) | not named in this issue | `20240625` | not stated | not stated | [zigbee-herdsman-converters#13080](https://github.com/Koenkk/zigbee-herdsman-converters/issues/13080), 2026-09-02 |
| **EasyCode903G2.1** | **`00:0d:6f`**      | **Ember Corporation** (acquired by Silicon Labs in 2012; Boston, MA, US) | **Dream V1.0** (per reporter) | not read (ZCL Basic cluster never interviewed; device is `supported: false`) | not read | not read | [Z2M#6551](https://github.com/Koenkk/zigbee2mqtt/issues/6551), 2021-03-03 |

[^zha]: ZHA never reads the Basic cluster's version attributes (`AppVersion`,
    `HWVersion`, `DateCode`, `SWBuildID`); only Z2M reads them at device
    interview. Fredrik's lock is on ZHA, so these values have never been
    captured for it, even though the attributes exist on the module (see the
    Basic cluster table in `docs/connect-bridge/hardware-gateway.md`).

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
attachment to Fredrik's own lock, is consistent with one generation on the
`f4:ce:36` Nordic block.

`EasyCode903G2` (no trailing `.1`) is a different string: it is the
`ModelIdentifier` default documented in Onesti's own 2021 module spec
(`docs/zigbee-protocol/elife-module-spec.md`), next to `easyCodeTouch_v1`, for
a device whose `ManufacturerName` the same spec documents as "Onesti Products
AS". Nobody has reported a lock answering it yet, but it passes the
integration's manufacturer filter and is listed in `SUPPORTED_MODELS` on that
basis. Whether it maps to a still-sold product, and whether it is the same
hardware family as `EasyCode903G2.1` under a coincidentally similar name, is
unknown.
