# Onesti Lock

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/onesti-lock.svg)](https://github.com/fredrik-lindseth/onesti-lock/releases)

Home Assistant integration for Onesti/Nimly smart locks via ZHA.

Manages PIN codes, identifies **who** unlocked the door and **how** (keypad, RFID, fingerprint), and gives you full local control — no cloud, no hub, no subscription.

## Features

- **User identification** — "Kari låste opp med kode", "Fredrik låste opp med RFID"
- **PIN code management** — set, change and clear codes via HA UI or services
- **Name any slot** — RFID tags, fingerprints, PINs — all get human-readable names
- **Activity sensor** — real-time events for automations and notifications
- **Slot sensors** — see who has access at a glance (10 sensor entities)
- **Auto-wake** — automatically wakes sleepy locks before sending commands
- **Progress feedback** — spinner UI while PIN commands are sent to the lock
- **Blueprints included** — connectivity alerts, goodnight lock, unlock notifications
- **100% local** — no cloud, no internet, no extra hardware
- **4 languages** — Norwegian, English, Swedish, Danish

## Supported devices

All Onesti Products AS locks with Zigbee Connect Module (ZMNC010):

| Zigbee model | Product | Verified |
|--------------|---------|----------|
| NimlyPRO | Nimly Touch Pro | Yes — tested with PIN, RFID, fingerprint |
| NimlyPRO24 | Nimly Touch Pro (2024) | Supported |
| NimlyCode | Nimly Code | Supported |
| NimlyTouch | Nimly Touch | Supported |
| NimlyIn | Nimly InDoor | Supported |
| NimlyShared | Nimly Shared | Supported |
| easyCodeTouch_v1 | EasyAccess EasyCodeTouch | Supported |
| EasyCodeTouch | EasyAccess EasyCodeTouch | Supported |
| EasyFingerTouch | EasyAccess EasyFingerTouch | Supported |

These are all the same hardware by **Onesti Products AS** — different branding, identical Zigbee module. Sold under Nimly, EasyAccess, Keyfree, Salus, Homely, Forebygg, and other brands.

## Installation

### Via HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/fredrik-lindseth/onesti-lock` as Integration
3. Install "Onesti Lock"
4. Restart Home Assistant

### Manual

1. Copy `custom_components/onesti_lock` to your `config/custom_components/`
2. Restart Home Assistant

## Setup

1. Pair the lock with ZHA (the lock's Zigbee Connect Module must be installed)
2. **Settings → Devices & Services → Add Integration → Onesti Lock**
3. Select your lock from the list
4. Done — slot sensors and activity sensor appear automatically

## Managing access

### PIN codes (via UI)

**Settings → Devices & Services → Onesti Lock → Configure**

- **Sett PIN-kode** — select slot, enter name and 4-8 digit code
- **Fjern PIN-kode** — select user to remove
- **Navngi bruker** — assign a name to any slot (for RFID, fingerprint, etc.)
- **Vis brukerslots** — overview of all slots

### PIN codes (via services)

```yaml
service: onesti_lock.set_pin
data:
  slot: 3
  name: "Kari"
  code: "5478"
```

| Service | Description |
|---------|-------------|
| `onesti_lock.set_pin` | Set PIN code with name for a slot |
| `onesti_lock.clear_pin` | Remove PIN code from a slot |
| `onesti_lock.set_name` | Set name without changing credentials |
| `onesti_lock.clear_slot` | Remove all credentials and name |

### RFID and fingerprint

RFID tags and fingerprints must be enrolled via the physical lock (using master code + keypad sequences — see your lock's manual). Once enrolled, you can **name the slot** via this integration so events show "Fredrik" instead of "Slot 1".

## Slot numbering

From the Nimly/EasyAccess manual:

| Slots | Purpose |
|-------|---------|
| 000 | First master code (factory: `123` — **change immediately**) |
| 001-002 | Additional master codes (optional) |
| 003-999 | User codes, RFID tags, fingerprints |

## Entities

Per configured lock:

- `sensor.*_slot_3` through `sensor.*_slot_12` — slot occupant name, `has_pin`/`has_rfid` attributes
- `sensor.*_siste_aktivitet` — last activity ("Kari låste opp med kode", "Auto-lås")

The activity sensor fires `onesti_lock_activity` events for use in automations.

## Blueprints

Three automation blueprints are included:

- **Connectivity alert** — notify when the lock goes offline or comes back
- **Goodnight lock** — lock the door automatically at a set time
- **Unlock notification** — notify when someone unlocks, with user and method

## Limitations

1. **PIN verification** — the lock returns a malformed ZCL response. The command reaches the lock, but we can't confirm success programmatically. Always test the code on the keypad.

2. **Sleepy device** — the lock sleeps aggressively to save battery. Commands may timeout on first attempt. The integration auto-wakes and retries, but place a Zigbee router near the door for best results.

3. **Attribute reporting after battery change** — the lock may stop sending activity events after a battery change. Try "Reconfigure" in ZHA (wake the lock first by entering a code). If that fails, remove and re-pair the lock.

4. **RFID/fingerprint enrollment** — can only be done via the physical keypad or BLE app, not via Zigbee.

5. **Slot state drift** — if PINs are changed via the physical keypad or another app, the integration's slot data may be out of sync. Use "View slots" to check.

## Why this instead of the Nimly app?

|  | Nimly App + Hub | **This integration** |
|--|----------------|---------------------|
| **Extra hardware** | Connect Bridge (~1500 kr) | Any Zigbee coordinator |
| **Cloud dependency** | Yes — iotiliti.cloud (AWS) | **None — 100% local** |
| **Automations** | Requires "PRO Hub" upsell | **Full HA automations** |
| **User identification** | Cloud event history | **Real-time in HA** |
| **Privacy** | All events to AWS | **Everything stays local** |
| **Cost** | Hub + cloud account | **Free and open source** |

## Alternative approaches (and why they don't work)

If you're researching how to integrate these locks, here's what we've tried:

- **Standard ZHA** — shows lock/unlock state, but cannot identify _who_ unlocked or _how_. Custom attribute 0x0100 is not decoded.
- **Zigbee2MQTT** — has better support via `onesti.ts` converter, but still limited user identification.
- **Nimly Connect app** — requires Connect Bridge hub, routes through iotiliti cloud, no HA automations without PRO Hub.
- **Nimly BLE app** — direct BLE to lock, but no Home Assistant integration and must be near the lock.
- **Cloud API (iotiliti)** — we've reverse-engineered the full REST API, but device listing is blocked (see `docs/cloud-api-status.md`).

## Documentation

| Document | Content |
|----------|---------|
| [Debugging guide](docs/debugging.md) | LED indicators, troubleshooting, debug logging |
| [Technical details](docs/technical.md) | Event decoding, coordinator, auto-wake |
| [Slot numbering](docs/slot-numbering.md) | Zigbee vs BLE vs cloud slot mapping |
| [Cloud API status](docs/cloud-api-status.md) | Reverse engineering progress and next steps |

## License

MIT License
