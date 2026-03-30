# Onesti Lock — Zigbee Captures & Protocol Reference

Rå Zigbee-fangster fra NimlyPRO (f4:ce:36:25:5a:2c:72:87) på HA Leirnes, 28-29. mars 2026.

## DoorLock Cluster (0x0101, endpoint 11)

### Attributt 0x0000 — Lock State (standard ZCL)

Type: enum8

| Verdi | Betydning |
|-------|-----------|
| 0x01 | Locked |
| 0x02 | Unlocked |

Rå ZCL frame (lock):
```
08 d2 0a 00 00 30 01
│  │  │  └──┘  │  └─ value: 0x01 (locked)
│  │  │  attrid  └─── type: 0x30 (enum8)
│  │  └─ command: 0x0A (Report_Attributes)
│  └──── TSN: 210
└─────── frame_control: 0x08 (server→client, global command)
```

### Attributt 0x0100 — Operation Event (Onesti custom)

Type: bitmap32

Sendes ved hver lås/opplåsing. Little-endian byte-rekkefølge:

```
Byte 0: user_slot  — 0 = system/auto, 3-199 = brukerslot
Byte 1: reserved   — alltid 0x00
Byte 2: action     — 0x01 = lock, 0x02 = unlock
Byte 3: source     — 0x01 = RF, 0x02 = keypad, 0x03 = manual, 0x0A = auto
```

Ukjente source-verdier (ikke observert ennå): fingeravtrykk, RFID/NFC.

Rå ZCL frame (Fredrik slot 3 unlock via keypad):
```
08 c1 0a 00 01 1b 03 00 02 02
│  │  │  └──┘  │  └──────────── value bytes (LE): [03, 00, 02, 02]
│  │  │  attrid  └─────────────── type: 0x1b (bitmap32)
│  │  └─ command: 0x0A (Report_Attributes)
│  └──── TSN: 193
└─────── frame_control: 0x08
```

Rå ZCL frame (auto-lock):
```
08 c5 0a 00 01 1b 00 00 01 0a
                   └──────────── [00, 00, 01, 0A] = slot 0, lock, auto
```

### Attributt 0x0101 — Last PIN Code (Onesti custom)

Type: LVBytes (octet string)

PIN-kode i rå bytes — to BCD-siffer per byte.

Rå ZCL frame (PIN "0927"):
```
08 c2 0a 01 01 41 02 09 27
│  │  │  └──┘  │  │  └──┘── PIN bytes: 0x09=09, 0x27=27 → "0927"
│  │  │  attrid  │  └─────── length: 2 bytes
│  │  │  (0x0101) └────────── type: 0x41 (LVBytes/OctetString)
│  │  └─ command: 0x0A
│  └──── TSN: 194
└─────── frame_control: 0x08
```

### Attributt 0x0023 — Auto Relock Time (standard ZCL)

Type: uint32

Verdi i sekunder. 0 = disabled.

```
08 c7 0a 23 00 23 00 00 00 00
            └──┘              └──────── value: 0 (disabled)
            attrid 0x0023
```

## Komplett event-sekvens for PIN-opplåsing

Når noen taster PIN + # på keypadet, sender låsen denne sekvensen:

```
1. attrid=0x0101 (PIN code)     — b"\x09\x27" (BCD: "0927")
2. attrid=0x0000 (lock state)   — 0x02 (unlocked)
3. attrid=0x0100 (operation)    — 0x02020003 (slot 3, unlock, keypad)
```

For auto-lock:
```
1. attrid=0x0000 (lock state)   — 0x01 (locked)
2. attrid=0x0100 (operation)    — 0x0A010000 (system, lock, auto)
```

## Alle observerte rå-verdier

| Tidspunkt | attrid | Raw value | Decoded |
|-----------|--------|-----------|---------|
| 28.03 21:50:26 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto |
| 28.03 21:59:15 | 0x0000 | 0x01 | locked |
| 28.03 21:59:15 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto |
| 28.03 21:59:19 | 0x0101 | b"\x09\x27" | PIN: 0927 |
| 28.03 21:59:19 | 0x0000 | 0x02 | unlocked |
| 28.03 21:59:21 | 0x0100 | 33685507 (0x02020003) | slot 3, unlock, keypad |
| 28.03 21:59:26 | 0x0000 | 0x01 | locked |
| 28.03 21:59:27 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto |
| 28.03 22:33:05 | 0x0100 | 33685507 (0x02020003) | slot 3, unlock, keypad |
| 28.03 22:33:12 | 0x0000 | 0x01 | locked |
| 28.03 22:33:12 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto |
| 29.03 09:17:10 | 0x0100 | 33685508 (0x02020004) | slot 4, unlock, keypad |
| 29.03 11:07:59 | 0x0100 | 33685504 (0x02020000) | slot 0, unlock, keypad |
| 29.03 11:33:08 | 0x0100 | 33685504 (0x02020000) | slot 0, unlock, keypad |
| 29.03 11:33:34 | 0x0100 | 167837696 (0x0A010000) | system, lock, auto |

## Node Descriptor

```json
{
  "logical_type": 2,          // EndDevice
  "frequency_band": 8,        // 2.4 GHz
  "mac_capability_flags": 136, // EndDevice, battery
  "manufacturer_code": 4660,   // 0x1234 (placeholder, not ZCL registered)
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
