# Onesti Lock

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/nimly-touch-pro-integration.svg)](https://github.com/fredrik-lindseth/nimly-touch-pro-integration/releases)

Home Assistant integration for PIN code management and activity tracking on Onesti/Nimly smart locks via ZHA. Identifies **who** unlocked the door and **how** — something no other ZHA integration has achieved for these locks.

## What works

- **"Frode låste opp med kode"** — activity sensor identifies user and method (keypad, RFID, manual, auto-lock)
- **PIN code management** — set and clear PIN codes via UI (Settings → Configure) or services
- **Slot→name mapping** — "Slot 4: Frode (PIN aktiv)" persisted across restarts
- **Options flow UI** — manage PINs without Developer Tools (Norwegian + English)
- **Slot sensors** — 10 sensor entities showing who has access
- **HA events** — `onesti_lock_activity` event fired for automations ("send notification when someone unlocks")

## How user identification works

Onesti locks send a custom attribute report (`attrid 0x0100`) on the Door Lock cluster for every lock/unlock event. This bitmap32 encodes user slot, action, and source — but no existing integration decoded it.

This integration listens for these reports via `cluster.on_event("attribute_report", ...)` and decodes the bitmap:

```
Byte 0: user_slot (0 = system, 3+ = user)
Byte 1: reserved
Byte 2: action (1 = lock, 2 = unlock)
Byte 3: source (1 = RF, 2 = keypad, 3 = manual, 10 = auto)
```

Standard ZHA approaches (`last_action_user`, `zha_event`, `add_listener`) don't work for these locks — see [Technical details](#why-standard-approaches-dont-work) below.

## Known limitations

- **PIN verification** — Nimly returns a malformed ZCL response causing `IndexError` in zigpy. The command reaches the lock, but we can't confirm success programmatically. Test the code on the keypad.

## Supported devices

All Onesti Products AS locks with Zigbee Connect Module:

| Zigbee model | Brand name | Status |
|-------|-------------|--------|
| NimlyPRO | Nimly Touch Pro | Verified |
| NimlyPRO24 | Nimly Touch Pro 24 | Supported |
| easyCodeTouch_v1 | EasyAccess / EasyCodeTouch | Supported |
| EasyCodeTouch | EasyAccess | Supported |
| EasyFingerTouch | EasyAccess | Supported |

These are all the same hardware with different branding.

## Installation

### Via HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/fredrik-lindseth/nimly-touch-pro-integration` as Integration
3. Install "Onesti Lock"
4. Restart Home Assistant

### Manual

1. Copy `custom_components/onesti_lock` to your `config/custom_components/`
2. Restart Home Assistant

## Setup

1. **Settings → Devices & Services → Add Integration → Onesti Lock**
2. Select your lock from the list
3. Done — slot sensors and activity sensor are created automatically

**Prerequisite:** ZHA must be configured and the lock paired.

## Managing PIN codes

### Via UI (recommended)

**Settings → Devices & Services → Onesti Lock → Configure**

Menu options:
- **Sett PIN-kode** — select slot, enter name and 4-8 digit code
- **Fjern PIN-kode** — select active user to remove
- **Vis brukerslots** — overview of all slots

### Via services

```yaml
service: onesti_lock.set_pin
data:
  slot: 3        # User slots: 3-199 (0-2 reserved for master codes)
  name: "Fredrik"
  code: "0927"
```

| Service | Description |
|---------|-------------|
| `onesti_lock.set_pin` | Set PIN code with name for a slot |
| `onesti_lock.clear_pin` | Remove PIN code from a slot |
| `onesti_lock.set_name` | Change slot name without changing PIN |
| `onesti_lock.clear_slot` | Remove all credentials and name from a slot |

## Entities

Per configured lock:

- `sensor.*_slot_3` through `sensor.*_slot_12` — shows slot occupant ("Fredrik" or "Ledig"), with `has_pin` and `has_rfid` attributes
- `sensor.*_siste_aktivitet` — last lock activity ("Frode låste opp med kode", "Auto-lås")

## Important: Slot numbering

Per the Nimly/EasyAccess manual:
- **Slots 0-2**: Reserved for master codes (programming codes)
- **Slots 3-199**: User codes
- **PIN entry**: code followed by `#` on the keypad

The default factory master code is `123`. **Change it immediately** — anyone with the manual can use it.

## Important: Lock must be awake

These locks are battery-powered and sleep. To send PIN commands:

1. **Wake the lock** — press the keypad, or send a lock/unlock from HA
2. **Run the command within a few seconds**

## Alternatives considered

| Integration | Why not |
|------------|---------|
| [Keymaster](https://github.com/FutureTense/keymaster) | Z-Wave only — no Zigbee support |
| [Lock Code Manager](https://github.com/raman325/lock_code_manager) | Requires `supported_features` on lock entity. ZHA reports `supported_features: 0` for these locks |
| [Zigbee Lock Manager](https://github.com/Fiercefish1/Zigbee-Lock-Manager) | Abandoned (last update Sep 2024). No config flow, doesn't handle Onesti response quirk |

## Technical details

### Why standard approaches don't work

We tested 6 different approaches before finding one that works. The lock sends event data, but ZHA/zigpy doesn't expose it through standard APIs:

| Approach | Result |
|----------|--------|
| ZHA `last_action_user` sensor | Never updates on keypad use — stale from last HA command |
| `zha_event` bus events | `operation_event_notification` (0x0020) never received |
| `add_listener` + `attribute_updated` | Suppressed by zigpy for unknown attributes (`_suppress_attribute_update_event`) |
| `add_listener` + `handle_cluster_request` | Only for cluster commands, not general commands like Report_Attributes |
| `add_listener` + `general_command` | Not dispatched to listeners for Report_Attributes |
| **`cluster.on_event("attribute_report")`** | **Works — catches all attribute reports including custom 0x0100** |

### Operation event format

Onesti locks report `attrid 0x0100` as bitmap32 (little-endian) on every lock/unlock:

```
Byte 0: user_slot (0 = system, 3+ = user code slot)
Byte 1: reserved (0)
Byte 2: action (1 = lock, 2 = unlock)
Byte 3: source (1 = RF, 2 = keypad, 3 = manual, 10 = auto)
```

`attrid 0x0101` contains the PIN code in BCD encoding.

### ZHA device chain

The Door Lock cluster lives on the deepest zigpy device object:

```
ZHADeviceProxy (depth 0, no endpoints)
  → Device (depth 1, empty in_clusters)
    → CustomDeviceV2 (depth 2, clusters here)
```

### Nimly response quirk

PIN commands return a malformed ZCL response causing `IndexError: tuple index out of range` in zigpy. The command reaches the lock — the error is in response parsing only. This integration catches the error silently.

### Slot data persistence

User→slot mapping stored in config entry options (`.storage`), survives restarts.
- **Slot data persistence**: stored in config entry options (`.storage`), survives restarts

## License

MIT License
