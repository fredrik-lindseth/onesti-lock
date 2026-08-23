# Upstream status: what we owe the two converter projects

Two projects decode these locks besides us, and both have open threads that
started here. This file is the thread, so a later session can pick it up
without rereading a GitHub tab that has moved on.

Last updated 2026-08-23.

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
2026-08-23 against `master`. Nothing has been reported upstream yet.

**It publishes the PIN in plaintext.** Lines 36 to 52 read attribute 257 and
publish it as `last_used_pin_code`, with the comment "Report exactly what the
lock sends". Every Zigbee2MQTT user of these locks has their door codes going
to the MQTT broker, into Home Assistant state, into the recorder, and into any
MQTT logger on the network. This is the same problem we removed in v1.3.0.
The converter also assumes ASCII and does not handle BCD, which is the format
NimlyPRO actually sends, so the published value is often garbage as well as
sensitive.

**Source `0x05` is missing.** The lookup covers `00`, `02`, `03`, `04` and
`0a`. NimlyCodePRO sends `0x05` for Zigbee commands, auto-relock and the
interior keypad alike, so Zigbee2MQTT reports `unknown` for a large share of
everyday operations on that model. `0x0a` is also named `self` rather than
`auto`, the same naming our PR fixes on the ZHA side.

**`result` is dead code.** `last_action_source` and `last_action_user` are
written to a local `result` object that is never returned. The information
still reaches MQTT, because lines 77 to 83 copy it into `attributes` as
`last_lock_source`, `last_unlock_source`, `last_lock_user` and
`last_unlock_user`. Cosmetic, but it makes the converter read as if two
documented fields exist when they do not.

## What we decided, and why we are not building a second transport

Supporting Zigbee2MQTT inside this integration alongside ZHA was assessed on
2026-08-23. The conclusion was no. The assessment is in
`plans/2026-08-23-vurdering-z2m.md`.

The blocker is that writing a PIN over MQTT is fire and forget. Zigbee2MQTT
has no response topic for a device `/set`, so success cannot be told apart
from a timeout. The auto-wake retry has nothing to trigger on, and the options
flow can no longer promise either "done" or "could not reach the lock". On top
of that, nobody on this project runs Zigbee2MQTT, so the whole path would ship
untested.

Zigbee2MQTT users already have the converter, which gives them everything
except named slots and PIN management from Home Assistant. Fixing the three
findings above upstream gives them more, sooner, than a transport we cannot
verify. That is the work to do: one PR to zigbee-herdsman-converters.

## Verifying any of this

```bash
curl -sL https://raw.githubusercontent.com/Koenkk/zigbee-herdsman-converters/master/src/devices/onesti.ts
gh pr view 4881 --repo zigpy/zha-device-handlers --comments
```

Our own decoding is canonical in `zigbee-protocol/zigbee-captures.md` and in
`_SOURCE_MAP` in `custom_components/onesti_lock/__init__.py`. Where a converter
disagrees with a capture, the capture wins.
