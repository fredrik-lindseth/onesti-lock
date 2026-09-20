# Upstream status: what we owe the two converter projects

Two projects besides us decode these locks, and both have open threads that
started here. This file is the thread, so a later session can pick it up
without rereading a GitHub tab that has moved on.

Last updated 2026-09-20.

## zigpy/zha-device-handlers (the ZHA quirk)

PR 4881, "Improve Nimly lock operation event decoding", open, ours. Checked
2026-09-20: unchanged. The last activity is our own status comment of
2026-09-19, and no maintainer has written since TheJulianJES's review comment
of 2026-04-29 (`.enum()` versus `.sensor()` for the source entity). PR 5345
and issue 5235 are likewise untouched since our comments on the 19th.
Nothing is waiting on us, so the next move is patience, not another comment.

The PR replaces hex string parsing with bitmask operations, renames source
`0x0A` from `self` to `auto`, returns `unknown` instead of `None` for
unexpected values, adds `NimlyShared` and `NimlyCodePRO` to the model list,
and maps `0x05` to `unattributed`.

Four things are unresolved.

The PIN exposure question is unanswered. The quirk builds a `last_action_pin`
sensor from attribute `0x0101`, which is the PIN itself in BCD plaintext, not
a credential id; supersej documented that in the PR thread, and we removed
our own equivalent in v1.3.0. TheJulianJES was asked whether it should be
removed or masked and has not answered. The sensor is
`entity_registry_enabled_default=False` there, better than what we had, but
it is enabled on at least one real instance (Fredrik's), so the default is
not protection. The hardware session of 2026-09-19 showed the test code in
clear text in the sensor's state, and the recorder kept it. The zigpy debug
log on issue 5235 (kept in `docs/manuals/`) adds that on that Code Pro a
manufacturer-specific `Read_Attributes([0x0101])` went out right after every
0x0100 report, so the PIN landed in zigpy's attribute cache on every
operation whatever the sensor's state. Both belong in the thread, but not one
day after our last comment. Save them for the next nudge.

matthiasnielsen1 reported that live reports never reach the quirk's entities.
Tested on a NimlyPRO24 (2026-08-18), which also showed that `0x05` is needed
there: a fingerprint unlock came as `0x03020000` and the auto-relock as
`0x05010000`, so the encoding is not unique to NimlyCodePRO. Decoding works
and `lock.*` updates, but `sensor.*_last_action_source` and its siblings keep
the startup value. Their lead: the attribute is stored twice in appdb, with
`mfg_code=4660` and with `mfg_code=None`, while incoming `Report_Attributes`
frames carry no manufacturer code and the attribute is declared
`is_manufacturer_specific=True`. supersej filed the mechanism as
zigpy/zha-device-handlers#5235 (2026-08-08): ZHA's DoorLock cluster handler
forwards only `lock_state` to entities and drops every other attribute
report on cluster 0x0101, so sensors bound to 0x0100 never see one. It does
not affect us: we listen on `cluster.on_event("attribute_report")` directly,
not through `QuirkBuilder` sensors, which is the workaround in `technical.md`.

PR 5345 (vinnyspb, 2026-09-16) adds NimlyCodePRO to the same model list, a
subset of 4881; whichever lands second gets a small conflict. vinnyspb runs
a real Code Pro and could confirm the `0x05` decoding on a second device.

A slot above 255 has never been captured. We decode the slot as 16 bits, so
does the PR, and nothing observed proves the width. Post the frame in the PR
thread once someone sets a PIN in slot 300 and captures the event.

## Koenkk/zigbee-herdsman-converters (the Zigbee2MQTT converter)

`src/devices/onesti.ts`, converter `nimly_pro_lock_actions`. Read 2026-08-23
against `master`, re-read 2026-09-19 (unchanged since commit `013ebd4` of
2026-05-21). Our fixes landed 2026-09-20.

### PR 13233 is merged

[PR 13233](https://github.com/Koenkk/zigbee-herdsman-converters/pull/13233),
"fix: Onesti Products AS locks: PIN code format, source 0x05, capability
attributes", was merged by Koenkk on 2026-09-20 05:54Z as commit `61b0b4c`
(`gh pr view 13233 -R Koenkk/zigbee-herdsman-converters`, read 2026-09-20).
It touched `src/devices/onesti.ts` and added `test/onesti.test.ts`. No review
comments; the only comment is Koenkk's "Thanks!" at merge. Nothing in it was
tested against a lock on our side, and the PR text says so.

Now in `master`:

- Source `0x05` decodes as `unattributed`, in the lookup and in both
  `last_lock_source` / `last_unlock_source` enum lists on both definitions
  (easyCodeTouch and Nimly). Zigbee2MQTT no longer reports `unknown` for
  NimlyCodePRO's and NimlyPRO24's everyday Zigbee, auto-relock and interior
  keypad operations.
- PIN format detection. A new `decodePinCode()` strips trailing NUL, reads
  the buffer as ASCII digits only when it is at least as long as the lock's
  minimum PIN length, otherwise as packed BCD, and falls back to hex instead
  of the control characters `toString("ascii")` produced. The minimum comes
  from the reported `minPinLen`, then `min_pin_length` in state, then a
  constant 4. Closes issue 13080.
- Capability attributes keyed by name (`numOfPinUsersSupported`, `minPinLen`,
  `maxPinLen`) instead of the numeric ids 18/23/24, which never matched, so
  the three exposes carry a value for the first time. The min/max swap went
  with it, `max_pin_users` is renamed `num_pin_users`, and the Nimly
  definition's `configure` now reads the capabilities in a `try` block like
  easyCodeTouch's.
- Dead code removed: the `voltage` branch (`closuresDoorLock` has no such
  attribute; `fz.battery` already publishes it from `genPowerCfg`) and the
  local `result` object that was never returned.
- `test/onesti.test.ts`: BCD (`[0x54, 0x78]` gives `"5478"`), ASCII
  (`"141141"`, the regression guard for PR 11332), the `39 39` ambiguity with
  `minPinLen` 4 giving `"3939"` not `"99"`, `0x05010000` as unattributed with
  user `"0"`, the keypad capture `0x02020003`, `0x0a010000`, and the
  capability block (`{numOfPinUsersSupported: 50, maxPinLen: 8, minPinLen:
  4}`), which failed on the old code and proved the dead block.

### Still open after the merge

- `0x0a` is still named `self`, not `auto`. Held out of 13233 on purpose:
  `last_lock_source` is an enum expose whose values sit in users' automations
  and Home Assistant states, and Zigbee2MQTT has no deprecation mechanism for
  enum values. A second PR is one line plus four enum lists, and should say
  that zha-device-handlers#4881 does the same rename.
- The DC/battery split. Issue 32772 in `Koenkk/zigbee2mqtt` (2026-08-07, a
  Nimly lock shown as DC-powered) is open and unanswered; issue 32469 (200 %
  battery, `dontDividePercentage`) was closed as stale on 2026-09-09 with no
  fix. The DC half now has an explanation, see the spec section; the battery
  half still looks like a firmware or module split we cannot settle without
  more units.
- `auto_relock_time` is exposed as seconds. Both Nimly definitions expose
  `e.numeric("auto_relock_time").withUnit("s")` from `autoRelockTime`, while
  `easycode_auto_relock` in the same file writes `1` or `0` to it and the
  binary `auto_relock` expose says "Auto relock after 7 seconds". The vendor
  spec says 0x0023 takes 0x00 or 0x01 and is not a time, so the numeric shows
  "1 s" for a seven-second relock. Folding it into the binary is one more
  item for the deferred PR, breaking in the same way.
- 13080 is closed by the merge. No new Onesti or Nimly issue has appeared in
  either Zigbee2MQTT repo since (searched 2026-09-20).
- The plaintext PIN. 13233 made `last_used_pin_code` decode correctly; it did
  not remove or mask it, and whether it should exist at all is unanswered.

### What was wrong, for the record

The reading that produced PR 13233, kept because the details explain the fix.

It publishes the PIN in plaintext. Attribute 257 is read and published as
`last_used_pin_code`, with the comment "Report exactly what the lock sends".
Every Zigbee2MQTT user of these locks has their door codes going to the MQTT
broker, into Home Assistant state, into the recorder, and into any MQTT
logger on the network. The same problem we removed in v1.3.0.

The PIN was decoded as ASCII, but NimlyPRO sends BCD. Our capture of PIN
"5478" is `b"\x54\x78"`, two bytes for four digits. Through
`Buffer.from([0x54, 0x78]).toString("ascii")` that is `"Tx"`; "1234" becomes
`"\x124"`, "9999" two control characters (Node's `ascii` masks the high bit,
so `0x99` turns into `0x19`), "0000" two NUL bytes. PR 11332, which added the
block, saw ASCII on its author's locks (its "before" value "313131313131" is
the hex of ASCII "111111"), and issue 13080 pins the split to the Connect
Module revision, so both formats exist in the field. Our removed
`_decode_pin_code` (commit `57ed320`) handled both. The fix recognises the
format: a buffer shorter than `minPinLen` (4 on NimlyPRO) cannot be ASCII;
else if every byte is `0x30`-`0x39` it is ASCII digits; else unpack nibbles
and require each to be 0-9. The "BCD 3939 looks like ASCII 99" ambiguity is
what the length check resolves. Trailing `0x00` is stripped first, since
`.trim()` does not remove NUL.

Source `0x05` was missing. The lookup covered `00`, `02`, `03`, `04` and
`0a`. NimlyCodePRO (fw 4.8.02) sends `0x05` for Zigbee commands, auto-relock
and the interior keypad alike, always with slot 0 (`0x05010000`), so
Zigbee2MQTT reported `unknown` for much of that model's everyday use. The
model had been in the converter since PR 11874 (April 2026), which added only
the string. We used our name `unattributed` so the two projects agree on the
byte, and added it to both enum lists in both definitions, or Zigbee2MQTT
rejects the value against the expose.

The capability block was dead code. The converter read `msg.data[18]`, `[23]`
and `[24]`. zigbee-herdsman's `ZclFrameConverter.attributeKeyValue` keys
`msg.data` by attribute name whenever the attribute exists in the cluster
definition and falls back to the numeric id only for unknown attributes. All
three are standard `closuresDoorLock` attributes (`numOfPinUsersSupported`
0x0012, `maxPinLen` 0x0017, `minPinLen` 0x0018), so the numeric keys never
matched. That is also why 256 and 257 do work: they are not in the cluster
definition, so they stay numeric. The `autoRelockTime` branch in the same
function already used the name. Read from zigbee-herdsman, not observed on a
running Zigbee2MQTT; the unit test proves it.

Min and max PIN length were swapped. The comments said 23 is min and 24 is
max. ZCL and zigbee-herdsman's definition say `maxPinLen` is 0x0017 and
`minPinLen` 0x0018. We had the identical mistake and fixed it in `8256a83`,
verified live: 0x0017 returns 8, 0x0018 returns 4. Keys by name make the swap
impossible to reintroduce. `max_pin_users` became `num_pin_users` because it
is a count; renaming an expose is normally breaking, but the field had never
carried a value, so nobody had an automation on it.

Nimly's `configure` never read the capabilities. Only easyCodeTouch's tried,
so Nimly locks only got values if the lock reported them unprompted. The same
`try` block was copied over.

### Checked and correct, not raised

Byte order and slot width match ours: the converter formats the 32-bit value
as an 8-character big-endian hex string, so `substring(0, 2)` is the source
byte, `substring(2, 4)` the action and `substring(4, 8)` the 16-bit slot. Its
comment ("Byte 0: Source ... Bytes 2-3: User ID") is right about hex-string
positions but reads as if it were wire order, which is the reverse. The
16-bit slot width is unproven in both projects, see the ZHA section.

The model list is complete: `easyCodeTouch_v1`, `EasyCodeTouch`,
`EasyFingerTouch`, `NimlyPRO`, `NimlyCode`, `NimlyTouch`, `NimlyIn`,
`NimlyPRO24`, `NimlyShared`, `NimlyCodePRO`, the same ten as our
`SUPPORTED_MODELS`.

Issues 32469 and 32772 (above) are a firmware split we cannot settle without
more units. Leave them alone.

### The second PR, not yet opened

`0x0a` from `self` to `auto`, one line plus four enum lists, with the
`auto_relock_time` fold-in, mentioning that zha-device-handlers#4881 does the
same rename so the two ecosystems align. Kept separate so a no on the
breaking change does not take fixes down with it.

Tooling: `pnpm run check` (biome with `--error-on-warnings`, four spaces,
line width 150, `bracketSpacing: false`; `useNamingConvention` allows
snake_case object keys) and `pnpm run test` (vitest, `--config
./test/vitest.config.mts`). Tests are per vendor in `test/`, with
`mockDevice` from `test/utils.ts` and `findByDevice` from `src/index`;
`test/onesti.test.ts` now exists and shows the pattern.
`test/checkDefinition.test.ts` and `test/index.test.ts` validate every expose
and catch a missing enum value. Run the whole suite.

The PR text has to say that nobody on this project runs Zigbee2MQTT and
nothing was tested against a lock: it rests on ZCL captures from a NimlyPRO
through ZHA, on the reports in zha-device-handlers#4881, and on reading
zigbee-herdsman. Ask for someone with a NimlyCodePRO to confirm `0x05` and
someone with an ASCII lock to confirm the PIN still decodes. Do not present
the 16-bit slot width as verified.

## What the vendor's 2021 spec is worth upstream

`zigbee-protocol/elife-module-spec.md` reads the *E-life Zigbee Modul User
Manual v2.0* that a customer attached to
[Koenkk/zigbee2mqtt#6379](https://github.com/Koenkk/zigbee2mqtt/issues/6379) in
2021. Anyone can download that PDF, which makes it the first thing we have
that an upstream maintainer can check without owning a lock. Assessed
2026-09-20.

Worth sending: the DC power source. The spec documents Basic attribute
PowerSource 0x0007 with value 0x04, "DC source", on a module that runs on
three AA cells. So a Nimly lock really does report DC, and
`Koenkk/zigbee2mqtt#32772` is not a Zigbee2MQTT misreading. `onesti.ts`
already compensates with `device.powerSource = "Battery"` in `configure` on
both Nimly definitions, and did before the report, so a device still shown as
DC was most likely interviewed without that `configure` completing. That
gives the reporter something to try (re-configure from the Z2M dashboard) and
the maintainers something to close on. A short comment on 32772, not a PR.

Worth sending, bundled: AutoRelockTime is boolean. Belongs in the deferred
breaking PR with the `self` to `auto` rename, with the spec as evidence.

Nothing to send: the one-byte command response. The spec says every Lock,
Unlock, Set PIN and Clear PIN response carries one status byte, FAILURE 0x00
or SUCCESS 0x01, and that memory-full and duplicate-code statuses are
deliberately not implemented. That is the standard one-field ZCL response,
which zigpy parses fine. The `IndexError` came from zha and is already fixed
there: zha 0.0.59's `Device.issue_cluster_command` checks `response[1] is not
ZclStatus.SUCCESS`, which assumes the two-field Default Response, and zha
2.2.2 reads `getattr(response, "status", None)` with a comment saying why
(read 2026-09-20). Home Assistant 2025.6 ships the old line and 2026.9 the
new one; our `send()` reads the field by name on both. The spec only confirms
the lock was never the problem.

Not worth sending: 0xFEA2 is "EA v2". The spec names the cluster and says
nothing else, no attributes, no commands. A naming question closed for us,
nothing for a converter to implement.

Not worth sending: the 50 PIN users and the 4-8 digit range. Both projects
read those off the lock now, which beats a document from 2021.

Not worth sending: the operation notification table. Command 0x20 with its
own source encoding (0x00 keypad, 0x02 manual, 0x03 RFID, 0xFF other) is a
different channel from attribute 0x0100, and our lock has never been seen to
send it. Posting it would invite someone to mix the two encodings.

## Findings from our own hardware that do not go upstream yet

The radio is Nordic, and manufacturer code 4660 is a ZBOSS default. The IEEE
prefix `f4:ce:36` belongs to Nordic Semiconductor, and 0x1234 is what an
unconfigured ZBOSS stack reports (`connect-bridge/hardware-gateway.md`).
Neither changes anything a converter does.

Basic reports `dateCode`, `hwVersion` and `swBuildId`, and ZHA reads only the
last. Z2M picks them all up at interview; ZHA's cache on the Code Pro in issue
5235 holds `sw_build_id` `4.8.02` and nothing else of the set, which is ZHA
core behaviour, not the quirk's. It matters only if the DC or the 200 %
battery split turns out to follow a firmware version: then `swBuildId`
(4.x.yy on the modules seen) is the field to ask reporters for, and ZHA users
can find it in their diagnostics download. Keep it for the next reporter on
32469.

The 2021 sniff and spec have no 0x0100 at all. The deCONZ#4253 capture of an
EasyCodeTouch on the Nordic OUI (kept in `docs/manuals/`) has lock state
reports and no manufacturer-specific frame in five minutes, and the spec
lists neither custom attribute. Both converters key everything on 0x0100, so
a lock on that firmware pairs and never reports who. Nobody has reported one;
if someone does, that is the first thing to ask.

Source 0x0A may be Zigbee-initiated rather than auto-lock, and the evidence
is too thin to send. Every 0x0100 report our lock produced after the
2026-09-19 re-pairing arrived 0.2-1.2 s after a `lock_door` or `unlock_door`
response, source 0x0A, including `0x0A020000` (unlock), which no auto-relock
would produce. That is six reports from one session on one lock, with no
keypad report to compare against, because keypad events had stopped arriving.
It also sits against the March captures in
`zigbee-protocol/zigbee-captures.md`, where `0x0A010000` arrived six seconds
after a keypad unlock with no command from Home Assistant, which is what
auto-relock looks like. The honest reading is that 0x0A may mean "no user to
attribute this to" on NimlyPRO, the role 0x05 plays on newer firmware, rather
than auto-lock specifically. Both `SOURCE_MAP` and the Z2M converter would
need changing if so. Do not raise it before a session where a keypad event and
a Zigbee command are captured minutes apart on a lock that reports properly.

## Another implementation: aridder/nimly-manager

A second Home Assistant integration for these locks appeared in August 2026:
[`aridder/nimly-manager`](https://github.com/aridder/nimly-manager), MIT,
Norwegian, five commits, last pushed 2026-08-10. It sits on Zigbee2MQTT (one
device topic through HA's MQTT integration, never Zigbee itself) and adds an
admin panel for fingerprint slots. It cites our
`docs/nimly-ble-app/ble-protocol.md`, our README limitations and our
`zigbee-captures.md`. Read 2026-09-20 at commit `b47b09d`, of which
`docs/manuals/` keeps a snapshot (one-star, one-person repo).

Its "guided local enrollment" is not a Zigbee enrollment. The name reads like
a fingerprint command over Zigbee; the code sends nothing.
`start_fingerprint_enrollment` creates an in-memory session and returns
keypad instructions (`###`, master finger, `NNN*`, three reads) the user
performs at the lock. `confirm_fingerprint_enrollment` only moves the session
state. Verification is passive: `runtime.observe_mqtt_state` watches for a
`locked` to `unlocked` transition whose `last_unlock_source` is fingerprint
and whose `last_unlock_user` equals the chosen slot, then fires
`nimly_fingerprint_enrollment_verified`. That is our attribute `0x0100`
event, decoded by the Z2M converter instead of by us. Their
`docs/fingerprint-enrollment.md` says so: BLE `0x57`/`0x58` exist, "dagens
kjente Zigbee- og Zigbee2MQTT-kontrakt har ingen tilsvarende kommando", and
their matrix in `docs/zigbee-door-lock.md` lists "Fingerprint
enrollment/delete" as "nei / UNKNOWN". An independent reading confirming that
enrolment stays on BLE.

What is new there is a UX idea we lack: name the person and the slot in HA
before the user programmes the finger on the keypad, then let the next
fingerprint unlock from that slot confirm it and write the name. That works
on ZHA today with nothing new on the wire, since the confirming event is the
one `events.py` already decodes.

Their RFID position is the one our vendor spec contradicts.
`zigbee-door-lock.md` tabulates ZCL `0x16`/`0x17`/`0x18` from zigbee-herdsman
and marks RFID create/read/delete "EXTENSION + PHYSICAL TEST". The E-life
spec (`zigbee-protocol/elife-module-spec.md`) says the module implements
lock, unlock, set PIN and clear PIN and nothing else, and documents Set/Clear
RFID responses without a command to produce them. A physical test is the only
proof either way; the spec says what to expect.

Their tester runs a Touch Pro on Zigbee2MQTT, firmware `4.7.79`. No issue or
commit shows an end-to-end enrolment being run, and the two merged PRs are
both `codex/*` branches. Their BLE section, dated 2026-08-09, is the useful
part: a read-only scan during physical lock and unlock saw no Nimly service
and no `0xFD00` service data, on two adapters, but the device appeared at once
(`name "Dør"`, service data 10 bytes where the reversed protocol describes 8)
the moment Add device was opened in the official BLE app. If that holds, the
module does not advertise in normal operation and BLE discovery has to be
provoked, which is the question our own BLE work is blocked on.

## What we decided, and why we are not building a second transport

Supporting Zigbee2MQTT alongside ZHA was assessed on 2026-08-23. No. The old
April plan for a separate `onesti_lock_z2m` integration is superseded by the
same assessment; its premise that "almost no code is shared" no longer
holds, since slot storage, the activity sensor, suppression, services,
options flow and localisation are transport neutral. If built, it would be
one `transport/` layer (`zha.py`, `z2m.py`) behind the same coordinator, with
a normalised `LockEvent` and a `transport` field in the config entry.

What tipped it:

- Writing a PIN over MQTT is fire and forget. Zigbee2MQTT has no response
  topic for a device `/set`; failures only appear as free text in
  `bridge/logging`, which is not a contract. Success cannot be told from a
  timeout, so the auto-wake retry has nothing to trigger on and the options
  flow can no longer promise "done" or "could not reach the lock".
  `onesti.ts` has no retry of its own, and herdsman's retries live inside the
  same 7.68-second parent window as zigpy's.
- The converter never publishes the raw `0x0100` value, only mapped fields,
  and the mapping lost `0x05` (fixed since).
- Zigbee2MQTT publishes the full cached state on every message from the
  device (`cache_state` defaults to true), so a battery report carries
  unchanged `last_*` fields. An integration would have to diff payloads, and
  a repeated identical event cannot be told from a ride-along. "One HA event
  per physical event" cannot be promised.
- The capability attributes (0x0012/0x0017/0x0018) are not readable via `/get`
  on the Nimly definitions.
- The converter puts `last_used_pin_code` into HA state via MQTT discovery,
  and an integration on top cannot remove it.
- Nobody on this project runs Zigbee2MQTT. The MQTT dump we asked a Z2M user
  for in April 2026 never arrived, so the path would ship untested.

Zigbee2MQTT users have the converter, which gives them everything except
named slots and PIN management from Home Assistant. Fixing it upstream gives
them more, sooner, than a transport we cannot verify. Revisit only if all
three happen: real demand from several Z2M users, a committed tester with an
Onesti lock on Z2M, and the converter fixes landed.

## Getting a dump from a Zigbee2MQTT tester

The upstream work needs a volunteer with a lock on Zigbee2MQTT. Ask for this.
The device topic is `zigbee2mqtt/<friendly_name>` (base topic configurable,
`zigbee2mqtt` by default; the friendly name is in the Z2M dashboard under
Devices).

```bash
mosquitto_sub -h <broker> [-u <user> -P <password>] -t "zigbee2mqtt/<friendly_name>" -v | tee onesti-mqtt-dump.txt
mosquitto_sub -h <broker> -t "zigbee2mqtt/bridge/info" -C 1 | python3 -m json.tool | grep version
```

MQTT Explorer works too. With the listener running, a few seconds apart,
noting which action each message belongs to: unlock with a PIN on the keypad,
lock with the keypad, unlock with a fingerprint, lock, unlock with an RFID
tag, lock, unlock and lock from the Z2M dashboard, then let auto-relock fire.
Per message we want `last_unlock_source`, `last_unlock_user`,
`last_lock_source`, `last_lock_user`, `lock_state` and whether
`last_used_pin_code` comes out as digits or garbage. Ask them to replace
`last_used_pin_code` values with `REDACTED` before sending.

## Verifying any of this

```bash
curl -sL https://raw.githubusercontent.com/Koenkk/zigbee-herdsman-converters/master/src/devices/onesti.ts
gh pr view 4881 --repo zigpy/zha-device-handlers --comments
gh pr view 13233 --repo Koenkk/zigbee-herdsman-converters --comments
```

Our decoding is canonical in `zigbee-protocol/zigbee-captures.md` and in
`SOURCE_MAP` in `custom_components/onesti_lock/events.py`. Where a converter
disagrees with a capture, the capture wins.
