# Nimly PRO

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/nimly-touch-pro-integration.svg)](https://github.com/fredrik-lindseth/nimly-touch-pro-integration/releases)

Home Assistant integration for PIN code management and activity tracking on Nimly Touch Pro smart locks via ZHA.

## What works

- **PIN code management** — set and clear PIN codes via UI (Settings → Configure) or services
- **Slot→name mapping** — "Slot 3: Ola (PIN aktiv)" persisted across restarts
- **Lock/unlock detection** — activity sensor updates on every lock state change
- **Options flow UI** — manage PINs without Developer Tools (Norwegian + English)
- **Slot sensors** — 10 sensor entities showing who has access

## What doesn't work (ZHA limitation)

- **User identification** — ZHA's `last_action_user` sensor does not reliably update when someone unlocks with PIN/fingerprint/RFID. We detect *that* someone unlocked, but not *who*.
- **Source identification** — ZHA's `last_action_source` stays "stuck" on the last HA-sent command. We can't tell if unlock was via keypad, key, or RFID.
- **PIN verification** — Nimly returns a malformed ZCL response causing `IndexError` in zigpy. The command reaches the lock, but we can't confirm success programmatically. Test the code on the keypad.

These are ZHA/zigpy limitations, not bugs in this integration. The [HA community thread](https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634) confirms that `last_action_user` worked initially for some users but stopped after weeks.

## What we tried

During development we tested several approaches to get user/source identification working:

| Approach | Result |
|----------|--------|
| Listen for `zha_event` bus events | No `operation_event_notification` events received from Nimly |
| Listen for `last_action` sensor state changes | Sensor never updates on physical keypad/key use |
| Listen for `lock.dorlasen` state changes | Works — detects locked↔unlocked transitions |
| Read `last_action_user` after lock state change | Always returns stale value (last HA command, not keypad user) |
| `get_pin_code` ZCL command (0x06) | Crashes zigpy with `tuple index out of range` — same Nimly response quirk |

The root cause is that Nimly's Zigbee firmware doesn't send `operation_event_notification` (ZCL command 0x0020) reliably over ZHA. The lock state attribute updates, but the event details (who, how) don't propagate.

## Possible paths forward

1. **Zigbee2MQTT** — community reports better event support for Nimly via Z2M. Would require replacing ZHA with Z2M as Zigbee coordinator.
2. **Nimly firmware update** — Onesti may improve event reporting in future firmware. Check for OTA updates.
3. **Quirk contribution** — a custom zigpy quirk for NimlyPRO could potentially fix the response parsing and event handling. See [zigpy/zha-device-handlers#3095](https://github.com/zigpy/zha-device-handlers/issues/3095).

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

**Prerequisite:** ZHA must be configured and the lock paired.

## Managing PIN codes

### Via UI (recommended)

**Settings → Devices & Services → Nimly PRO → Configure**

Menu options:
- **Sett PIN-kode** — select slot, enter name and 4-8 digit code
- **Fjern PIN-kode** — select active user to remove
- **Vis brukerslots** — overview of all slots

### Via services

```yaml
service: nimly_pro.set_pin
data:
  slot: 3        # User slots: 3-199 (0-2 reserved for master codes)
  name: "Ola"
  code: "5478"
```

| Service | Description |
|---------|-------------|
| `nimly_pro.set_pin` | Set PIN code with name for a slot |
| `nimly_pro.clear_pin` | Remove PIN code from a slot |
| `nimly_pro.set_name` | Change slot name without changing PIN |
| `nimly_pro.clear_slot` | Remove all credentials and name from a slot |

## Entities

Per configured lock:

- `sensor.*_slot_3` through `sensor.*_slot_12` — shows slot occupant ("Ola" or "Ledig"), with `has_pin` and `has_rfid` attributes
- `sensor.*_siste_aktivitet` — last lock activity ("Låste opp via HA", "Låste")

## Important: Slot numbering

Per the Nimly manual:
- **Slots 0-2**: Reserved for master codes (programming codes)
- **Slots 3-199**: User codes

The default factory master code is `123`. **Change it immediately** — anyone with the manual can use it to program new codes.

## Important: Lock must be awake

Nimly is battery-powered and sleeps. To send PIN commands:

1. **Wake the lock** — press the keypad, or send a lock/unlock from HA
2. **Run the command within a few seconds**

## Alternatives considered

| Integration | Why not for Nimly |
|------------|---------|
| [Keymaster](https://github.com/FutureTense/keymaster) | Z-Wave only — does not support ZHA/Zigbee locks at all |
| [Lock Code Manager](https://github.com/raman325/lock_code_manager) | Requires `supported_features` on lock entity. ZHA's Nimly lock has `supported_features: 0`, so LCM can't find it |
| [Zigbee Lock Manager](https://github.com/Fiercefish1/Zigbee-Lock-Manager) | Abandoned (last update Sep 2024). YAML-only, no config flow, generates input helpers manually |

None of these handle Nimly's ZCL response quirk (`IndexError` in zigpy) which must be caught for PIN commands to work.

## Technical details

- **ZCL Door Lock Cluster** (0x0101) on endpoint 11
- **ZHA object chain**: `ZHADeviceProxy` → `Device` (clusters empty) → `CustomDeviceV2` (clusters here). This integration walks the chain automatically.
- **Nimly response quirk**: PIN commands (set/clear/get) return a malformed response causing `IndexError: tuple index out of range` in zigpy's `foundation.py`. The command reaches the lock successfully — the error is in response parsing only. This integration catches the error and treats it as success.
- **Slot data persistence**: stored in config entry options (`.storage`), survives restarts

## License

MIT License
