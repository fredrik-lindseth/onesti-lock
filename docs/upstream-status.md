# Upstream status: what we owe the two converter projects

Two projects decode these locks besides us, and both have open threads that
started here. This file is the thread, so a later session can pick it up
without rereading a GitHub tab that has moved on.

Last updated 2026-09-19.

## zigpy/zha-device-handlers (the ZHA quirk)

**PR 4881, "Improve Nimly lock operation event decoding", open, ours.**

It replaces hex string parsing with bitmask operations, renames source `0x0A`
from `self` to `auto`, returns `unknown` instead of `None` for unexpected
values, adds `NimlyShared` and `NimlyCodePRO` to the model list, and maps
`0x05` to `unattributed`.

Three things are unresolved.

**The PIN exposure question is unanswered.** The quirk builds a
`last_action_pin` sensor from attribute `0x0101`. That attribute is the PIN
itself in BCD plaintext, not an opaque credential id, which supersej
documented in the PR thread. We removed our own equivalent in v1.3.0 for that
reason. TheJulianJES was asked whether it should be removed or masked upstream
and has not answered. The sensor is `entity_registry_enabled_default=False`
there, which is better than what we had, but it is enabled on at least one
real instance (Fredrik's), so the default is not protection.

**matthiasnielsen1 reported that live reports never reach the quirk's
entities.** Decoding works, `lock.*` updates, but `sensor.*_last_action_source`
and its siblings keep the value from startup. Their lead: the attribute is
stored twice in appdb, once with `mfg_code=4660` and once with `mfg_code=None`,
while incoming `Report_Attributes` frames carry no manufacturer code, and the
attribute is declared `is_manufacturer_specific=True`. That is worth chasing.
It does not affect us, because we listen on `cluster.on_event("attribute_report")`
directly rather than through `QuirkBuilder` sensors, which is exactly the
workaround documented in `technical.md`.

**A slot above 255 has never been captured.** We decode the user slot as 16
bits and so does the PR, but nothing observed proves the width. Post the frame
in the PR thread once someone sets a PIN in slot 300 and captures the event.

## Koenkk/zigbee-herdsman-converters (the Zigbee2MQTT converter)

`src/devices/onesti.ts`, converter `nimly_pro_lock_actions`. Read on
2026-08-23 against `master` (266 lines then; line numbers are not repeated
here because the file is small and moves). Searched the same day with `gh` in
both `Koenkk/zigbee-herdsman-converters` and `Koenkk/zigbee2mqtt` for onesti,
nimly, easyCodeTouch and `last_used_pin_code`: no open PR touches the file and
no open issue describes any of the findings below. Nothing has been reported
upstream yet, and none of it has been tested against hardware on our side.

### Findings

**It publishes the PIN in plaintext.** Attribute 257 is read and published as
`last_used_pin_code`, with the comment "Report exactly what the lock sends".
Every Zigbee2MQTT user of these locks has their door codes going to the MQTT
broker, into Home Assistant state, into the recorder, and into any MQTT logger
on the network. This is the same problem we removed in v1.3.0.

**The PIN is decoded as ASCII, but NimlyPRO sends BCD.** Our capture of PIN
"5478" is `b"\x54\x78"`, two bytes for four digits. Through the converter that
becomes `Buffer.from([0x54, 0x78]).toString("ascii")`, which is `"Tx"`. "1234"
becomes `"\x124"`, "9999" two control characters (Node's `ascii` masks the high
bit, so `0x99` turns into `0x19`), "0000" two NUL bytes. The value is not the
PIN, is not stable, and lands escaped in the MQTT payload and in an HA text
entity. PR 11332, which added the block, saw ASCII on its author's locks
("313131313131" before, "141141" after, which is hex of ASCII "111111"), so
both formats exist in the field. Our removed `_decode_pin_code` (commit
`57ed320`) handled both. A fix has to recognise the format instead of assuming
it: a buffer shorter than `minPinLen` (4 on NimlyPRO) cannot be ASCII; else if
every byte is `0x30`-`0x39` it is ASCII digits; else unpack nibbles and require
each to be 0-9. The ambiguity "BCD 3939 looks like ASCII 99" is exactly what
the length check resolves. Strip trailing `0x00` first, since `.trim()` does
not remove NUL.

**Source `0x05` is missing.** The lookup covers `00`, `02`, `03`, `04` and
`0a`. NimlyCodePRO (fw 4.8.02) sends `0x05` for Zigbee commands, auto-relock
and the interior keypad alike, always with slot 0 (`0x05010000`), so
Zigbee2MQTT reports `unknown` for a large share of everyday operations on that
model. The model has been in the converter since PR 11874 (April 2026), which
added only the model string. Use our name `unattributed` so the two projects
agree on the byte, and add it to both enum lists in both definitions
(easyCodeTouch and Nimly), or Zigbee2MQTT rejects the value against the expose.

**`0x0a` is named `self`, not `auto`.** Same rename our ZHA PR does. This one
is breaking: `last_lock_source` is an enum expose whose values sit directly in
users' automations and HA states, and Zigbee2MQTT has no deprecation mechanism
for enum values. Keep it out of the bug-fix PR.

**The capability block is dead code.** The converter reads
`msg.data[18]`, `[23]` and `[24]` for `max_pin_users`, `min_pin_length` and
`max_pin_length`. zigbee-herdsman's `ZclFrameConverter.attributeKeyValue` keys
`msg.data` by attribute *name* whenever the attribute exists in the cluster
definition, and falls back to the numeric id only for unknown attributes. All
three are standard `closuresDoorLock` attributes (`numOfPinUsersSupported`
0x0012, `maxPinLen` 0x0017, `minPinLen` 0x0018), so the numeric keys never
match and the three exposes have never had a value. That is also why 256 and
257 do work: they are not in the cluster definition, so they stay numeric. The
`autoRelockTime` branch in the same function already uses the name correctly.
Read from zigbee-herdsman, not observed on a running Zigbee2MQTT; a unit test
proves it.

**Min and max PIN length are swapped.** The comments say 23 is min and 24 is
max. ZCL and zigbee-herdsman's own definition say `maxPinLen` is 0x0017 and
`minPinLen` is 0x0018. We had the identical mistake and fixed it in `8256a83`,
verified live: 0x0017 returns 8, 0x0018 returns 4. Fixing the keys by name
makes the swap impossible to reintroduce. While there, `max_pin_users` should
become `num_pin_users` (it is a count, not a maximum). Renaming an expose is
normally breaking, but this field has never carried a value, so nobody has an
automation on it.

**The `voltage` branch is dead.** `nimly_pro_lock_actions` is registered on
`closuresDoorLock`, which has no `voltage` attribute. Battery voltage lives on
`genPowerCfg` as `batteryVoltage`, and `fz.battery`, present on both
definitions, already publishes it as `voltage`. Delete the branch.

**`result` is dead code.** `last_action_source` and `last_action_user` are
written to a local `result` object that is never returned. The information
still reaches MQTT as `last_lock_source`, `last_unlock_source`,
`last_lock_user` and `last_unlock_user`. Cosmetic, but it makes the converter
read as if two documented fields exist when they do not.

**Nimly's `configure` never reads the capabilities.** Only the easyCodeTouch
definition tries in its `configure`. Even with the keys fixed, Nimly locks only
get values if the lock reports them unprompted. Copy the same `try` block over.

### Checked and correct, do not raise in the PR

Byte order and slot width match ours: the converter formats the 32-bit value
as an 8-character big-endian hex string, so `substring(0, 2)` is the source
byte, `substring(2, 4)` the action and `substring(4, 8)` the 16-bit slot. Its
comment ("Byte 0: Source ... Bytes 2-3: User ID") is right about hex-string
positions but reads as if it were wire order, which is the reverse. The 16-bit
slot width is unproven in both projects, see the ZHA section.

The model list is complete: `easyCodeTouch_v1`, `EasyCodeTouch`,
`EasyFingerTouch`, `NimlyPRO`, `NimlyCode`, `NimlyTouch`, `NimlyIn`,
`NimlyPRO24`, `NimlyShared`, `NimlyCodePRO`, the same ten as our
`SUPPORTED_MODELS`.

Issue 32469 in `Koenkk/zigbee2mqtt` (Nimly showing 200 % battery) is about
`meta: {battery: {dontDividePercentage: true}}` on both definitions. It is a
firmware split we cannot settle without more units. Leave it alone.

### What the PR needs

Two PRs, so a no on the breaking change does not take the fixes down with it:

1. Bug fixes, nothing breaking: PIN format detection, `0x05` as `unattributed`
   (fills a hole where `unknown` stood), capability keys by name with the
   min/max swap corrected and `max_pin_users` renamed to `num_pin_users`,
   capability reading in Nimly's `configure`, and removal of the dead `voltage`
   branch and the `result` object.
2. `0x0a` from `self` to `auto`, one line plus four enum lists. Mention that
   zha-device-handlers#4881 does the same rename, so the two ecosystems end up
   aligned.

Tooling: `pnpm run check` (biome with `--error-on-warnings`, four spaces, line
width 150, `bracketSpacing: false`; `useNamingConvention` allows snake_case
object keys) and `pnpm run test` (vitest, `--config ./test/vitest.config.mts`).
Tests are per vendor in `test/`, with `mockDevice` from `test/utils.ts` and
`findByDevice` from `src/index`; `test/fromZigbee.test.ts` shows the simplest
pattern, calling `converter.convert(...)` with a `msg` literal. There is no
`test/onesti.test.ts`, so add one covering at least:

- BCD PIN: `{257: Buffer.from([0x54, 0x78])}` gives `"5478"`.
- ASCII PIN: `{257: Buffer.from("141141", "ascii")}` gives `"141141"`
  (regression guard for PR 11332).
- The ambiguity: `{257: Buffer.from([0x39, 0x39])}` with `minPinLen` 4 gives
  `"3939"`, not `"99"`. If the fix cannot do this without state, document the
  choice in the test rather than pretend.
- `{256: 0x05010000}` gives `last_lock_source: "unattributed"`, user `"0"`.
- `{256: 0x02020003}` gives `last_unlock_source: "keypad"`, user `"3"` (a real
  capture from `zigbee-protocol/zigbee-captures.md`, worth citing).
- `{256: 0x0a010000}` for auto.
- `{numOfPinUsersSupported: 50, maxPinLen: 8, minPinLen: 4}` gives
  `{num_pin_users: 50, max_pin_length: 8, min_pin_length: 4}`. This one is the
  whole proof of the dead capability block and fails on today's code.

`test/checkDefinition.test.ts` and `test/index.test.ts` validate every expose,
and catch a missing enum value. Run the whole suite.

The PR text has to say that nobody on this project runs Zigbee2MQTT and
nothing was tested against a lock: it rests on ZCL captures from a NimlyPRO
through ZHA, on the reports in zha-device-handlers#4881, and on reading
zigbee-herdsman. Ask for someone with a NimlyCodePRO to confirm `0x05` and
someone with an ASCII lock to confirm the PIN still decodes. Do not present
the 16-bit slot width as verified.

## What we decided, and why we are not building a second transport

Supporting Zigbee2MQTT inside this integration alongside ZHA was assessed on
2026-08-23. The conclusion was no. The old April plan for a separate
`onesti_lock_z2m` integration is superseded by the same assessment; its
premise that "almost no code is shared" no longer holds, since slot storage,
the activity sensor, suppression, services, options flow and localisation are
transport neutral. If it were built, it would be one `transport/` layer
(`zha.py`, `z2m.py`) behind the same coordinator, with a normalised
`LockEvent` and a `transport` field in the config entry.

What tipped it:

- Writing a PIN over MQTT is fire and forget. Zigbee2MQTT has no response
  topic for a device `/set`; failures only appear as free text in
  `bridge/logging`, which is not a contract. Success cannot be told apart from
  a timeout, so the auto-wake retry has nothing to trigger on and the options
  flow can no longer promise either "done" or "could not reach the lock".
  `onesti.ts` has no retry logic of its own, and herdsman's retries live inside
  the same 7.68-second parent window as zigpy's.
- The converter never publishes the raw `0x0100` value, only its mapped
  fields, and the mapping loses `0x05` (see above).
- Zigbee2MQTT publishes the full cached state on every message from the
  device (`cache_state` defaults to true), so a battery report carries
  unchanged `last_*` fields. An integration would have to diff payloads, and a
  repeated identical event cannot be told from a ride-along. "One HA event per
  physical event" cannot be promised.
- The capability attributes (0x0012/0x0017/0x0018) are not readable via `/get`
  on the Nimly definitions.
- The converter puts `last_used_pin_code` into HA state via MQTT discovery,
  and an integration on top cannot remove it.
- Nobody on this project runs Zigbee2MQTT. The MQTT dump we asked a Z2M user
  for in April 2026 never arrived, so the whole path would ship untested.

Zigbee2MQTT users already have the converter, which gives them everything
except named slots and PIN management from Home Assistant. Fixing the findings
above upstream gives them more, sooner, than a transport we cannot verify.
Revisit only if all three happen: real demand from several Z2M users, a
committed tester with an Onesti lock on Z2M, and the converter fixes landed.

## Getting a dump from a Zigbee2MQTT tester

The upstream PR needs a volunteer with a lock on Zigbee2MQTT. This is what to
ask them for. The device topic is `zigbee2mqtt/<friendly_name>` (the base
topic is configurable, `zigbee2mqtt` is the default; the friendly name is in
the Z2M dashboard under Devices).

```bash
mosquitto_sub -h <broker> [-u <user> -P <password>] -t "zigbee2mqtt/<friendly_name>" -v | tee onesti-mqtt-dump.txt
mosquitto_sub -h <broker> -t "zigbee2mqtt/bridge/info" -C 1 | python3 -m json.tool | grep version
```

MQTT Explorer works too. With the listener running, do these a few seconds
apart and note which action each message belongs to: unlock with a PIN on the
keypad, lock with the keypad, unlock with a fingerprint, lock, unlock with an
RFID tag, lock, unlock and lock from the Z2M dashboard, then let auto-relock
fire. What we want to see per message is `last_unlock_source`,
`last_unlock_user`, `last_lock_source`, `last_lock_user`, `lock_state` and
whether `last_used_pin_code` comes out as digits or garbage. Ask them to
replace `last_used_pin_code` values with `REDACTED` before sending.

## Verifying any of this

```bash
curl -sL https://raw.githubusercontent.com/Koenkk/zigbee-herdsman-converters/master/src/devices/onesti.ts
gh pr view 4881 --repo zigpy/zha-device-handlers --comments
```

Our own decoding is canonical in `zigbee-protocol/zigbee-captures.md` and in
`_SOURCE_MAP` in `custom_components/onesti_lock/__init__.py`. Where a converter
disagrees with a capture, the capture wins.
