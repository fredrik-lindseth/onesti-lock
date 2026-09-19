# Onesti Lock

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/onesti-lock.svg)](https://github.com/fredrik-lindseth/onesti-lock/releases)

Home Assistant integration for Onesti/Nimly smart locks paired through ZHA.

The lock reports every event on a custom Zigbee attribute that no other ZHA integration decodes. This integration decodes it, so Home Assistant knows who locked or unlocked the door and how (keypad, RFID, fingerprint). It also manages PIN codes from the HA interface, gives every slot a human-readable name, and includes an activity sensor, events for automations and three automation blueprints.

The vendor's own route to the same data is the Nimly Connect app, which needs a Connect Bridge gateway and sends every lock event through the iotiliti cloud before you can act on it. This integration talks to the lock over the Zigbee network you already run, so events stay on your own hardware and reach automations as they happen. The cloud side is described in [docs/nimly-connect-app/app-architecture.md](docs/nimly-connect-app/app-architecture.md).

Requires ZHA and Home Assistant 2024.12 or newer. Zigbee2MQTT is not supported; it has its own converter for these locks (see [docs/technical.md](docs/technical.md)).

## Supported devices

All Onesti Products AS locks with Zigbee Connect Module (ZMNC010):

| Zigbee model     | Product                    | Verified                                 |
| ---------------- | -------------------------- | ---------------------------------------- |
| NimlyPRO         | Nimly Touch Pro            | Yes, tested with PIN, RFID, fingerprint  |
| NimlyPRO24       | Nimly Touch Pro (2024)     | Supported                                |
| NimlyCode        | Nimly Code                 | Supported                                |
| NimlyCodePRO     | Nimly Code Pro             | Supported                                |
| NimlyTouch       | Nimly Touch                | Supported                                |
| NimlyIn          | Nimly InDoor               | Supported                                |
| NimlyShared      | Nimly Shared               | Supported                                |
| easyCodeTouch_v1 | EasyAccess EasyCodeTouch   | Supported                                |
| EasyCodeTouch    | EasyAccess EasyCodeTouch   | Supported                                |
| EasyFingerTouch  | EasyAccess EasyFingerTouch | Supported                                |

These are all the same hardware by **Onesti Products AS**, different branding on an identical Zigbee module. Sold under Nimly, EasyAccess, Keyfree, Salus, Homely, Forebygg, and other brands.

The table is not the whole list of what you can set up. Setup offers any ZHA device from Onesti Products AS that exposes a Door Lock cluster, since a Connect Module sometimes reports a sibling model name rather than the lock it sits on. A model string outside the table still works, and the integration writes a warning to the log when it sees one. Please report that model string as an issue so it can be added here.

NimlyCodePRO (firmware 4.8) reports the same source code for Zigbee commands, auto-relock and the interior keypad, so those events get the source `unattributed` and the activity sensor reads plain "Locked" or "Unlocked". An unattributed lock with no user slot is treated as auto-relock and leaves the activity sensor alone, so an unlock with a code stays visible.

## Installation

### Via HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fredrik-lindseth&repository=onesti-lock&category=integration)

That button adds this repository to HACS. Install "Onesti Lock" and restart Home Assistant. To do it by hand instead: HACS → Integrations → ⋮ → Custom repositories, add `https://github.com/fredrik-lindseth/onesti-lock` as Integration.

### Manual

1. Copy `custom_components/onesti_lock` to your `config/custom_components/`
2. Restart Home Assistant

## Setup

Pair the lock with **ZHA** first. The lock's Zigbee Connect Module must be installed.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=onesti_lock)

Or go to **Settings → Devices & Services → Add Integration → Onesti Lock**. Select your lock from the list, and the slot sensors and activity sensor appear automatically.

## Managing access

### PIN codes (via UI)

**Settings → Devices & Services → Onesti Lock → Configure**

- **Set PIN code**: select slot, enter name and a 4-8 digit code
- **Clear PIN code**: select the user to remove
- **Name a user slot**: assign a name to any slot from 0 to 999, master slots included (for RFID, fingerprint, the master code, etc.). An empty name removes it.
- **View user slots**: overview of the master slots and the first user slots
- **Settings**: how many slots from 0 up are master codes on this lock (1-3, default 3). The Set PIN list starts after them, and `set_pin`, `clear_pin` and `clear_slot` refuse them. Set it to 1 on a Code Pro, which has only one master slot. Slot 0 is never written, whatever the setting.

Names live in Home Assistant only and never reach the lock, which is why every slot can be named. When someone unlocks with the master code, fingerprint or key tag on slot 0, the activity sensor and the `onesti_lock_activity` event use the name you gave slot 0, or "Master" if it has none.

Menu labels follow the Home Assistant server language.

### PIN codes (via services)

```yaml
service: onesti_lock.set_pin
data:
  slot: 3
  name: "Kari"
  code: "5478"
```

| Service                  | Description                           | Slots accepted         |
| ------------------------ | ------------------------------------- | ---------------------- |
| `onesti_lock.set_pin`    | Set PIN code with name for a slot     | first user slot to N-1 |
| `onesti_lock.clear_pin`  | Remove PIN code from a slot           | first user slot to 999 |
| `onesti_lock.set_name`   | Set name without changing credentials | 0-999                  |
| `onesti_lock.clear_slot` | Remove all credentials and name       | first user slot to 999 |

The first user slot is the Settings value: 3 by default, 1 or 2 if you lowered it. `set_pin` also refuses slot numbers above what the lock reports it can hold (NumberOfPINUsersSupported, N above; NimlyPRO and NimlyCodePRO report 50, so the highest usable slot is 49). Until the lock has reported its capacity, 999 is the ceiling. `clear_pin` and `clear_slot` go all the way to 999, so a slot that was filled before the limit was known can still be emptied. `set_name` takes any slot, since it only touches Home Assistant.

### RFID and fingerprint

RFID tags and fingerprints must be enrolled via the physical lock (using master code and keypad sequences, see your lock's manual). Once enrolled, you can **name the slot** via this integration so events show "Fredrik" instead of "Slot 3".

## Slot numbering

The manuals disagree between models, so the numbering is per model:

| Model          | Master codes                       | User codes | Source                                                                                                                        |
| -------------- | ---------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Touch Pro, PRO | 000 (factory `123`), 001-002 extra | 003-999    | [Touch Pro manual (nimly.se, 2024)](https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf)  |
| Code           | 000 (factory `123`), 001-002 extra | 003-999    | [Code installation guide (nimly.se, 2022)](https://nimly.se/wp-content/uploads/2023/11/EN-Code-Installation-Guide-130922.pdf) |
| Code Pro       | 000 (factory `123`)                | 001-999    | [Code Pro product guide (nimly.se, 2026)](https://nimly.se/wp-content/uploads/2026/04/EN-Code-Pro-Product-Guide-120126.pdf)   |

Change the factory code straight away. The manuals say master codes cannot be deleted, only overwritten, and the master code also opens the door (the Code Pro can be set to use it for programming only). Fingerprints and key tags have their own ranges in each manual (the Touch Pro takes user fingerprints on 003-199), so check yours before naming those slots.

The lock does not tell the models apart over Zigbee: a Code Pro has reported itself as NimlyTwist ([#5](https://github.com/fredrik-lindseth/onesti-lock/issues/5)). That is why the number of master slots is a setting and not detected. The default of 3 is the safe choice on every model; lower it to 1 on a Code Pro to use slots 1 and 2 for users.

How Zigbee, BLE and cloud slot numbers relate is documented in [docs/slot-numbering.md](docs/slot-numbering.md).

## Entities

Per configured lock:

- `sensor.*_slot_3` through `sensor.*_slot_12`: slot occupant name, with `has_pin` and `has_rfid` attributes
- `sensor.*_last_activity`: last activity, for example "Kari unlocked with code"

Entity IDs are generated from the server language at creation time, so a lock set up on a Norwegian server gets `sensor.*_siste_aktivitet` and keeps it.

When the lock has reported its capabilities, the activity sensor also exposes `num_pin_users`, `min_pin_length` and `max_pin_length` as attributes.

The integration fires an `onesti_lock_activity` event for every decoded lock operation, including auto-lock. Payload and automation examples are in [docs/technical.md](docs/technical.md).

Versions 1.1.0 through 1.2.0 exposed the last used PIN code as a state attribute, which wrote real access codes into the recorder database. Current versions do not read that attribute at all. If you ran those versions, follow the cleanup steps in [docs/debugging.md](docs/debugging.md#6-cleanup-after-versions-110-through-120).

## Blueprints

Three automation blueprints are included:

- **Connectivity alert**: notify when the lock goes offline or comes back
- **Goodnight lock**: lock the door automatically at a set time
- **Unlock notification**: notify when someone unlocks, with user and method

## Languages

English, Norwegian (bokmål), Swedish and Danish. Sensor states, entity names, options flow labels and service errors follow the Home Assistant server language (Settings > System > General), not the per-user frontend language. Reload the integration after upgrading or after changing the server language.

To add a language, copy `custom_components/onesti_lock/translations/en.json` and translate it, including the `runtime` section.

## Limitations

1. **Zigbee2MQTT is not supported.** Z2M's `onesti.ts` converter decodes the same attribute and gives you raw slot numbers, but no named users, no readable activity messages and no PIN management UI. A feature comparison is in [docs/technical.md](docs/technical.md#comparison-with-zigbee2mqtt). If you already use Z2M, use the converter; cross-protocol setups are not supported.

2. **PIN verification**: the lock returns a malformed ZCL response. The command reaches the lock, but we can't confirm success programmatically. Always test the code on the keypad.

3. **Sleepy device**: the lock sleeps aggressively to save battery, so commands may time out on the first attempt. The integration auto-wakes and retries, but the auto-wake works by sending a **lock command** to the lock. If the door is unlocked when you set or clear a PIN, the door will physically lock; if the door is standing open, the bolt is driven out into the air. Close the door before managing PIN codes, or wake the lock yourself first by turning the thumb-turn. Also place a Zigbee router right next to the door, since the metal casing acts as a Faraday cage.

4. **Attribute reporting after battery change**: the lock may stop sending activity events after a battery change. Try "Reconfigure" in ZHA (wake the lock first by entering a code). If that fails, remove and re-pair the lock.

5. **RFID/fingerprint enrollment**: can only be done via the physical keypad or BLE app, not via Zigbee.

6. **Slot state drift**: if PINs are changed via the physical keypad or another app, the integration's slot data may be out of sync. Use "View user slots" to check.

7. **No OTA firmware updates**: the Zigbee module does not support over-the-air updates.

## Documentation

| Document                                     | Content                                        |
| -------------------------------------------- | ---------------------------------------------- |
| [Debugging guide](docs/debugging.md)         | LED indicators, troubleshooting, debug logging |
| [Technical details](docs/technical.md)       | Event decoding, coordinator, auto-wake         |
| [Slot numbering](docs/slot-numbering.md)     | Zigbee vs BLE vs cloud slot mapping            |
| [Cloud API status](docs/cloud-api-status.md) | Reverse engineering progress and next steps    |

Bugs and questions go to the [issue tracker](https://github.com/fredrik-lindseth/onesti-lock/issues).

## License

MIT License
