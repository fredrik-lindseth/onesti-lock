# Nimly PRO

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/nimly-touch-pro-integration.svg)](https://github.com/fredrik-lindseth/nimly-touch-pro-integration/releases)

Home Assistant integration for PIN code management and activity tracking on Nimly Touch Pro smart locks.

## Why this integration?

ZHA handles basic lock control for Nimly (lock/unlock, battery, volume, auto-lock). **This integration adds what ZHA doesn't provide:**

- PIN code management with user names (slot → name mapping)
- Activity tracking ("Fredrik låste opp med kode")
- Services for programmatic PIN administration
- Sensor entities per slot showing who has access

## Supported devices

| Model | Manufacturer | Status |
|-------|-------------|--------|
| NimlyPRO | Onesti Products AS | Supported |
| NimlyPRO24 | Onesti Products AS | Supported |

## Installation

### Via HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/fredrik-lindseth/nimly-touch-pro-integration` as Integration
3. Install "Nimly PRO"
4. Restart Home Assistant

### Manual

1. Copy `custom_components/nimly_pro` to your `config/custom_components/`
2. Restart Home Assistant

## Setup

1. **Settings → Devices & Services → Add Integration → Nimly PRO**
2. Select your lock from the list
3. Done — slot sensors and activity sensor are created automatically

**Prerequisite:** ZHA must be configured and the lock paired before setup.

## Services

| Service | Description |
|---------|-------------|
| `nimly_pro.set_pin` | Set PIN code with name for a slot |
| `nimly_pro.clear_pin` | Remove PIN code from a slot |
| `nimly_pro.set_name` | Change slot name without changing PIN |
| `nimly_pro.clear_slot` | Remove all credentials and name from a slot |

### Set PIN code

```yaml
service: nimly_pro.set_pin
data:
  slot: 3        # User slots: 3-199 (0-2 reserved for master codes)
  name: "Fredrik"
  code: "0927"
```

### Clear PIN code

```yaml
service: nimly_pro.clear_pin
data:
  slot: 3
```

## Entities

Per configured lock:

- `sensor.*_slot_3` through `sensor.*_slot_12` — shows slot occupant ("Fredrik" or "Ledig")
- `sensor.*_siste_aktivitet` — last lock activity with user name

Slot sensors include `has_pin` and `has_rfid` as attributes.

## Important: Slot numbering

Per the Nimly manual:
- **Slots 0-2**: Reserved for master codes (programming codes)
- **Slots 3-199**: User codes

The default factory master code is `123`. **Change it immediately** — anyone with the manual can use it.

## Important: Lock must be awake

Nimly is battery-powered and sleeps to conserve power. To send PIN commands:

1. **Wake the lock** — press a button on the keypad, or send a lock/unlock command from HA
2. **Run the service within a few seconds**

If you get "Kunne ikke nå låsen", the lock was asleep.

## Known Nimly ZHA quirks

- **Response parsing error:** Nimly returns an unexpected response format for PIN commands, causing `IndexError: tuple index out of range` in zigpy. The command still reaches the lock — this integration catches the error silently.
- **Activity tracking:** ZHA's `last_action_user` and `last_action_source` sensors don't reliably update on keypad events. The activity sensor tracks lock state changes (locked/unlocked) but may not identify which user unlocked.
- **ZHA device chain:** The Door Lock cluster lives on the deepest zigpy device object (CustomDeviceV2), not the ZHA wrapper layers. This integration walks the chain automatically.

## Alternatives considered

| Integration | Why not |
|------------|---------|
| [Keymaster](https://github.com/FutureTense/keymaster) | Z-Wave only — does not support ZHA/Zigbee locks |
| [Lock Code Manager](https://github.com/raman325/lock_code_manager) | Requires lock entity to expose code management feature (`supported_features`). ZHA's Nimly lock entity has `supported_features: 0` |
| [Zigbee Lock Manager](https://github.com/Fiercefish1/Zigbee-Lock-Manager) | Abandoned (last update Sep 2024). YAML-only UI, no config flow, generates input helpers manually |

None of these work with Nimly over ZHA due to the quirky response format and lack of `supported_features` on the lock entity.

## Technical details

Nimly Touch Pro uses the **ZCL Door Lock Cluster (0x0101)**. This integration sends ZCL commands directly to the cluster via ZHA/zigpy, with error handling for the Nimly response quirk.

The ZHA object chain for accessing clusters:
```
ZHADeviceProxy → Device (clusters empty) → CustomDeviceV2 (clusters here)
```

## License

MIT License
