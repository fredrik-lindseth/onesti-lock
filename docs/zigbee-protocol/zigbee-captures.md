# Onesti Lock — Zigbee Captures & Protocol Reference

Raw Zigbee captures from NimlyPRO (f4:ce:36:25:5a:2c:72:87).

## DoorLock Cluster (0x0101, endpoint 11)

### Attribute 0x0000 — Lock State (standard ZCL)

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

### Attribute 0x0100 — Operation Event (Onesti custom)

Type: bitmap32

Sent on every lock/unlock. Little-endian byte order:

```
Byte 0: user_slot  — 0 = system/auto, 3-199 = user slot
Byte 1: reserved   — always 0x00
Byte 2: action     — 0x01 = lock, 0x02 = unlock
Byte 3: source     — 0x01 = RF, 0x02 = keypad, 0x03 = manual, 0x0A = auto
```

Unknown source values (not yet observed): fingerprint, RFID/NFC.

### Verified source values (byte 3)

Final mapping used in the integration (verified against Z2M converter and raw captures):

| Byte | Source      | Status                        |
| ---- | ----------- | ----------------------------- |
| 0x00 | Zigbee (RF) | Inferred                      |
| 0x02 | Keypad      | Verified (multiple captures)  |
| 0x03 | Fingerprint | From Z2M converter            |
| 0x04 | RFID        | From Z2M converter            |
| 0x0A | Auto-lock   | Verified (multiple captures)  |

Note: Session notes (2026-03-28) contain an early hypothesis with different values (1=RF, 3=manual). The code in `__init__.py` `_SOURCE_MAP` is authoritative.

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

### Attribute 0x0101 — Last PIN Code (Onesti custom)

Type: LVBytes (octet string)

PIN code in raw bytes — two BCD digits per byte.

Raw ZCL frame (PIN "5478"):

```
08 c2 0a 01 01 41 02 09 27
│  │  │  └──┘  │  │  └──┘── PIN bytes: 0x54=54, 0x78=78 → "5478"
│  │  │  attrid  │  └─────── length: 2 bytes
│  │  │  (0x0101) └────────── type: 0x41 (LVBytes/OctetString)
│  │  └─ command: 0x0A
│  └──── TSN: 194
└─────── frame_control: 0x08
```

### Attribute 0x0023 — Auto Relock Time (standard ZCL)

Type: uint32

Value in seconds. 0 = disabled.

```
08 c7 0a 23 00 23 00 00 00 00
            └──┘              └──────── value: 0 (disabled)
            attrid 0x0023
```

## Complete event sequence for PIN unlock

When someone enters PIN + # on the keypad, the lock sends this sequence:

```
1. attrid=0x0101 (PIN code)     — b"\x54\x78" (BCD: "5478")
2. attrid=0x0000 (lock state)   — 0x02 (unlocked)
3. attrid=0x0100 (operation)    — 0x02020003 (slot 3, unlock, keypad)
```

For auto-lock:

```
1. attrid=0x0000 (lock state)   — 0x01 (locked)
2. attrid=0x0100 (operation)    — 0x0A010000 (system, lock, auto)
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

## Node Descriptor

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

## Endpoint 11 Clusters

```
Input clusters (server):
  0x0000 — Basic
  0x0001 — Power Configuration
  0x0003 — Identify
  0x0004 — Groups
  0x0005 — Scenes
  0x0101 — Door Lock ← main cluster
  0xFEA2 — Manufacturer Specific (unknown)

Output clusters (client):
  0x0019 — OTA Upgrade
```
