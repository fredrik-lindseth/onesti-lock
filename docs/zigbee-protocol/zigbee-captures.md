# Zigbee captures and protocol reference

Raw Zigbee captures from a NimlyPRO (f4:ce:36:25:5a:2c:72:87), and the protocol
values decoded from them.

The hex frames below were written down from the ZHA debug log in March 2026
and the log was not kept, so the header bytes (frame control, TSN) cannot be
re-checked. The value bytes can: they match the table of observed values at
the end of this file and the captures in `tests/test_event_properties.py`.
Frames with headers straight out of a kept log exist for one other lock, a
NimlyCodePRO, under [Captures from other locks](#captures-from-other-locks).

## DoorLock cluster (0x0101, endpoint 11)

### Attribute 0x0000: Lock State (standard ZCL)

Type: enum8

| Value | Meaning  |
| ----- | -------- |
| 0x01  | Locked   |
| 0x02  | Unlocked |

Raw ZCL frame (lock):

```
08 d2 0a 00 00 30 01
│  │  │  └──┘  │  └─ value: 0x01 (locked)
│  │  │  attrid  └─── type: 0x30 (enum8)
│  │  └─ command: 0x0A (Report_Attributes)
│  └──── TSN: 210
└─────── frame_control: 0x08 (server→client, global command)
```

### Attribute 0x0100: Operation Event (Onesti custom)

Type: bitmap32

Sent on every lock and unlock, in little-endian byte order:

```
Bytes 0-1: user_slot  (uint16 LE) 0 = master credential when the source is
                      keypad/fingerprint/rfid, otherwise no user; 1-999 = slot
Byte 2:    action     0x01 = lock, 0x02 = unlock
Byte 3:    source     see table below
```

Slot width caveat: every capture below has byte 1 = 0x00 because no observed
slot exceeds 255, so the 16-bit read is an assumption, not a captured fact.
It follows the Nimly manual (slots 0-999) and the upstream converter in
[zha-device-handlers#4881](https://github.com/zigpy/zha-device-handlers/pull/4881)
(`value & 0xFFFF`). To confirm on hardware: set a PIN in slot 300 via the
`onesti_lock.set_pin` service, unlock on the keypad, and capture attrid
0x0100. Expected raw value: `0x0202012C` (LE bytes `[2C, 01, 02, 02]`).
Add the capture to the table below once observed.

### Verified source values (byte 3)

Final mapping used in the integration (verified against Z2M converter and raw captures):

| Byte | Source       | Status                                                                 |
| ---- | ------------ | ---------------------------------------------------------------------- |
| 0x00 | Zigbee (RF)  | Inferred                                                               |
| 0x02 | Keypad       | Verified (multiple captures; also a raw NimlyCodePRO frame, below)     |
| 0x03 | Fingerprint  | From Z2M converter; one raw NimlyCodePRO frame (below), a lock on slot 1 |
| 0x04 | RFID         | From Z2M converter                                                     |
| 0x05 | Unattributed | Reported for NimlyCodePRO and NimlyPRO24                               |
| 0x0A | Auto-lock    | Verified (multiple captures)                                           |

Source encoding varies per model/firmware. NimlyCodePRO (fw 4.8.02, reported by
supersej in [zha-device-handlers#4881](https://github.com/zigpy/zha-device-handlers/pull/4881))
sends 0x05 for Zigbee commands, auto-relock and the interior keypad button
alike, always with user slot 0 (payload `0x05010000`), and never sends 0x00 or
0x0A. The payload cannot distinguish the three, hence "unattributed". On the
same model the physical emergency key produces no event at all and does not
update lock_state.

NimlyPRO24 does the same. matthiasnielsen1 reported in the same PR thread
(2026-08-18, firmware string reported as `0x00000000`) a fingerprint unlock as
`0x03020000` (fingerprint, unlock, slot 0) followed by the auto-relock as
`0x05010000`. So 0x05 is not a NimlyCodePRO oddity; the NimlyPRO captured in
this file (0x00 and 0x0A, never 0x05) is the odd one out so far, and which
firmware draws the line is unknown.

An early hypothesis from the first session (1=RF, 3=manual) was wrong. The code
in `events.py` `SOURCE_MAP` is authoritative.

Raw ZCL frame (Ola slot 3 unlock via keypad):

```
08 c1 0a 00 01 1b 03 00 02 02
│  │  │  └──┘  │  └──────────── value bytes (LE): [03, 00, 02, 02]
│  │  │  attrid  └─────────────── type: 0x1b (bitmap32)
│  │  └─ command: 0x0A (Report_Attributes)
│  └──── TSN: 193
└─────── frame_control: 0x08
```

Raw ZCL frame (auto-lock):

```
08 c5 0a 00 01 1b 00 00 01 0a
                   └──────────── [00, 00, 01, 0A] = slot 0, lock, auto
```

### Attribute 0x0101: Last PIN Code (Onesti custom)

Type: LVBytes (octet string)

PIN code in raw bytes, two BCD digits per byte. The integration deliberately
ignores this attribute: decoding it would write real access codes into HA's
recorder, logbook and diagnostics. See the comment in `events.py`.

Raw ZCL frame (PIN "5478", the same report as row 21:59:19 in the table at the
end):

```
08 c2 0a 01 01 41 02 54 78
│  │  │  └──┘  │  │  └──┘── PIN bytes: 0x54, 0x78, two BCD digits each → "5478"
│  │  │  attrid  │  └─────── length: 2 bytes
│  │  │  (0x0101) └────────── type: 0x41 (LVBytes/OctetString)
│  │  └─ command: 0x0A
│  └──── TSN: 194
└─────── frame_control: 0x08
```

### Attribute 0x0023: Auto Relock Time (standard ZCL)

Type: uint32

Value in seconds. 0 = disabled.

```
08 c7 0a 23 00 23 00 00 00 00
            └──┘              └──────── value: 0 (disabled)
            attrid 0x0023
```

### PIN commands (0x0005, 0x0006, 0x0007)

The responses to Set PIN Code (0x0005) and Clear PIN Code (0x0007) have
raised `IndexError` before any payload was available; the command is still
carried out. The source is ZHA, found in code on 2026-09-20: zha 0.0.59's
`Device.issue_cluster_command` reads `response[1]` from a one-field response
(see technical.md), and zha 2.2.2 reads the field by name. Whether the error
still occurs now that commands go to the zigpy cluster directly is untested
on hardware, but nothing in the path indexes the answer any more. Per ZCL, a
Set PIN Code Response carries one status byte: 0 = success, 1 = general
failure, 2 = memory full, 3 = duplicate code. The vendor's 2021 spec
([elife-module-spec.md](elife-module-spec.md)) says the module sends that one
byte as SUCCESS or FAILURE only, with memory full and duplicate code not
implemented. That byte is the confirmation the integration lacks, and
`send()` now reads it. No raw 0x0005 response has been captured from a lock:
the 2021 sniff below has no PIN command, and the NimlyCodePRO log below has
only reports. What a current lock answers, and whether it ever says FAILURE,
is still to be seen on hardware.

Get PIN Code (0x0006) has never been sent to a lock from this project, so
whether its response parses is unknown. A successful response would contain
the PIN in plaintext, the same class of problem as attribute 0x0101.

## Complete event sequence for PIN unlock

When someone enters PIN + # on the keypad, the lock sends this sequence:

```
1. attrid=0x0101 (PIN code)     b"\x54\x78" (BCD: "5478")
2. attrid=0x0000 (lock state)   0x02 (unlocked)
3. attrid=0x0100 (operation)    0x02020003 (slot 3, unlock, keypad)
```

For auto-lock:

```
1. attrid=0x0000 (lock state)   0x01 (locked)
2. attrid=0x0100 (operation)    0x0A010000 (system, lock, auto)
```

## All observed raw values

| Timestamp      | attrid | Raw value              | Decoded                |
| -------------- | ------ | ---------------------- | ---------------------- |
| 28.03 21:50:26 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto     |
| 28.03 21:59:15 | 0x0000 | 0x01                   | locked                 |
| 28.03 21:59:15 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto     |
| 28.03 21:59:19 | 0x0101 | b"\x54\x78"            | PIN: 5478              |
| 28.03 21:59:19 | 0x0000 | 0x02                   | unlocked               |
| 28.03 21:59:21 | 0x0100 | 33685507 (0x02020003)  | slot 3, unlock, keypad |
| 28.03 21:59:26 | 0x0000 | 0x01                   | locked                 |
| 28.03 21:59:27 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto     |
| 28.03 22:33:05 | 0x0100 | 33685507 (0x02020003)  | slot 3, unlock, keypad |
| 28.03 22:33:12 | 0x0000 | 0x01                   | locked                 |
| 28.03 22:33:12 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto     |
| 29.03 09:17:10 | 0x0100 | 33685508 (0x02020004)  | slot 4, unlock, keypad |
| 29.03 11:07:59 | 0x0100 | 33685504 (0x02020000)  | slot 0, unlock, keypad |
| 29.03 11:33:08 | 0x0100 | 33685504 (0x02020000)  | slot 0, unlock, keypad |
| 29.03 11:33:34 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto     |

## Captures from other locks

Three primary sources from other people's locks are kept locally
(`docs/manuals/README.md`, "Captures, logs and code"). What each one answers:

### NimlyCodePRO, firmware 4.8.02, ZHA (August 2026)

A zigpy debug log and a ZHA diagnostics dump from
[zha-device-handlers#5235](https://github.com/zigpy/zha-device-handlers/issues/5235),
a Code Pro nobody here owns, with `sw_build_id` `4.8.02` in the Basic cluster
cache. The log holds six frames in nine seconds, headers included, the only
raw operation events on file whose headers were not reconstructed:

```
22:47:41.668  08 c5 0a 00 00 30 01              lock_state = 1 (locked)
22:47:41.790  08 c6 0a 00 01 1b 01 00 01 03     0x0100 = 0x03010001: slot 1, lock, fingerprint
22:47:42.072  1c 34 12 09 01 01 01 00 41 03 ..  Read Attributes Response for 0x0101, 3 bytes (PIN scrubbed by the uploader)
22:47:49.814  08 c7 0a 00 00 30 02              lock_state = 2 (unlocked)
22:47:49.933  08 c8 0a 00 01 1b 01 00 02 02     0x0100 = 0x02020001: slot 1, unlock, keypad
22:47:50.234  1c 34 12 0a 01 01 01 00 41 03 ..  Read Attributes Response for 0x0101, 3 bytes
```

What it shows:

- Slot 1 holds a user credential on a Code Pro. A fingerprint on slot 1
  locked the door and a keypad code on slot 1 unlocked it, as the Code Pro
  guide's "001-999 user codes" predicts, and this is the first capture that
  shows it. It says nothing about whether ZCL `set_pin_code` accepts slot 1,
  only that the lock reports it.
- The sequence is lock state, then the operation event 120 ms later, and no
  unsolicited 0x0101 report. The 0x0101 frames are answers: the stock quirk's
  stack sends a manufacturer-specific `Read_Attributes([0x0101])` right after
  every 0x0100 report (`1c 34 12` is a manufacturer-specific server-to-client
  frame, manufacturer 0x1234), so on that instance the last PIN was fetched
  after every operation. Which part of ZHA issues the read, and whether it
  depends on the PIN sensor being enabled, was not traced. The NimlyPRO
  captured above sent 0x0101 on its own; the order may differ per firmware,
  or the Code Pro's reporting may not have been configured for it.
- The PIN is packed BCD on this firmware too: 3 bytes for the six-digit code,
  the same encoding as the NimlyPRO's `54 78`.
- The diagnostics dump lists a cluster 0xFEA2 with attributes 0xFF01 to
  0xFF04 (`last_action`, `last_action_source`, `last_action_user`,
  `last_pin_code`). Those are defined by the quirk in that ZHA release, not
  read from the lock; the real cluster has never been read. The same dump
  shows the module's last OTA `QueryNextImage` request with
  `manufacturer_code 0`, `image_type 0`, `current_file_version 0` and
  `hardware_version 52`, so the module does ask for images, and identifies
  itself with zeros when it does.

### EasyCodeTouch, March 2021, deCONZ sniff

`Doorlock.sniff.zip` from [deCONZ#4253](https://github.com/dresden-elektronik/deconz-rest-plugin/issues/4253)
is a Wireshark capture of an EasyCodeTouch at network address 0x6014,
extended address `f4:ce:36:32:a2:96:09:ab`, so the same Nordic OUI as every
lock since. Over five minutes it holds two Unlock Door commands from the
coordinator, three retransmits of a `lock_state` report with the value
`0xFF` (ZCL "undefined", which the vendor spec describes as the state after
power-on), and a Configure Reporting of `lock_state` (min 1 s, max 300 s)
that the lock accepted. There is no attribute 0x0100, no 0x0101, no
Operation Event Notification (0x20), no PIN command and not one
manufacturer-specific frame. `lock.command.ONCE.zip` from
[Z2M#5884](https://github.com/Koenkk/zigbee2mqtt/issues/5884), same lock and
period, is one Lock Door command with no decoded answer. Together with the
2021 vendor spec, which lists neither custom attribute, this is the evidence
that the operation event arrived in a later firmware.

### EasyCode903G2.1, February 2021, Zigbee2MQTT log

`log1.txt` from [Z2M#6551](https://github.com/Koenkk/zigbee2mqtt/issues/6551)
is the Datek/Ember generation, not this module: `ManufacturerName` "Datek
Wireless", endpoint 1 rather than 11, clusters Basic, Power Configuration,
Identify, Groups, Scenes and Door Lock in, Identify and OTA out, no 0xFEA2.
The interview completed; Z2M 1.17.1 published no date code or build id for
it. See [hardware-generations.md](../hardware-generations.md).

## Node descriptor

```json
{
  "logical_type": 2, // EndDevice
  "frequency_band": 8, // 2.4 GHz
  "mac_capability_flags": 136, // EndDevice, battery
  "manufacturer_code": 4660, // 0x1234 (placeholder, not ZCL registered)
  "maximum_buffer_size": 108,
  "maximum_incoming_transfer_size": 127,
  "maximum_outgoing_transfer_size": 127
}
```

## Endpoint 11 clusters

```
Input clusters (server):
  0x0000  Basic
  0x0001  Power Configuration
  0x0003  Identify
  0x0004  Groups
  0x0005  Scenes
  0x0101  Door Lock ← main cluster
  0xFEA2  Manufacturer Specific ("EA v2", contents unknown)

Output clusters (client):
  0x0019  OTA Upgrade
```

The NimlyCodePRO dump above lists the same seven input clusters and the same
output cluster, and no Poll Control (0x0020) on either lock.
