# <img src="images/icon.svg" alt="" width="32" align="top"> Onesti Lock

[![CI](https://github.com/fredrik-lindseth/onesti-lock/actions/workflows/ci.yml/badge.svg)](https://github.com/fredrik-lindseth/onesti-lock/actions/workflows/ci.yml)
[![HACS validation](https://github.com/fredrik-lindseth/onesti-lock/actions/workflows/validate.yml/badge.svg)](https://github.com/fredrik-lindseth/onesti-lock/actions/workflows/validate.yml)
[![Hassfest](https://github.com/fredrik-lindseth/onesti-lock/actions/workflows/hassfest.yml/badge.svg)](https://github.com/fredrik-lindseth/onesti-lock/actions/workflows/hassfest.yml)
[![Coverage](https://codecov.io/gh/fredrik-lindseth/onesti-lock/branch/main/graph/badge.svg)](https://codecov.io/gh/fredrik-lindseth/onesti-lock)
[![Release](https://github.com/fredrik-lindseth/onesti-lock/actions/workflows/release.yml/badge.svg)](https://github.com/fredrik-lindseth/onesti-lock/actions/workflows/release.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/onesti-lock.svg)](https://github.com/fredrik-lindseth/onesti-lock/releases)
[![SLSA Build L2](https://slsa.dev/images/gh-badge-level2.svg)](SECURITY.md)

Home Assistant integration for Onesti/Nimly smart locks paired through ZHA. Onesti Products AS makes the locks and sells them as [Nimly](https://nimly.io) and under several other brands.

The lock reports every event on a custom Zigbee attribute. ZHA's stock quirk exposes it as raw numbers at most, and an open upstream report says those entities do not update live. This integration decodes it into who locked or unlocked the door, by the name you gave the slot, and how (keypad, RFID, fingerprint).

The vendor's own route to the same data is the Nimly Connect app, which needs a Connect Bridge gateway and sends every lock event through the iotiliti cloud ([docs/nimly-connect-app/app-architecture.md](docs/nimly-connect-app/app-architecture.md)). This integration talks to the lock over the Zigbee network you already run, so events stay on your own hardware.

Requires ZHA and Home Assistant 2025.6 or newer. Zigbee2MQTT is not supported, see [Limitations](#limitations).

## Why this, when the lock is already in ZHA

ZHA alone gives you a working lock: the lock entity you lock and unlock with, the battery level, and whatever sensors its quirk adds. What it does not give you is who opened the door, or any way to manage the codes. That is what this integration adds:

- **Who and how.** The operation event on attribute 0x0100 is decoded into the name you gave the slot and the method used, keypad, RFID or fingerprint, instead of raw numbers.
- **Slot names that stay put.** Names are stored in Home Assistant, survive restarts and updates, and the master slots sit below a floor that nothing here writes a PIN to.
- **PIN management in the UI.** Set, clear and name slots under Configure. The options flow sends the command straight to the lock, so the code does not land in the recorder the way an action call does.
- **Codes kept out of the log.** The integration never reads the attribute where the lock reports the last used PIN, and it masks digit runs in the error text it logs. What it cannot cover is in [Security](#security).
- **A lock that sleeps.** A command that times out wakes the lock and is retried, and the answer is told apart as delivered, refused by the lock, or never reached.
- **Activity worth looking back at.** The activity sensor survives a restart, and system relocking is kept off it, so "Kari unlocked with code" is not overwritten two seconds later.
- **An event and blueprints.** Every decoded operation fires `onesti_lock_activity`, and three blueprints are ready to import.
- **When there is more than one, and when it breaks.** Further locks are offered as discoveries from ZHA, a repair issue appears if ZHA stops delivering events, and the diagnostics download holds no PIN, no address and no slot names.

One thing to know about the stock quirk: it has a last PIN code sensor of its own. It is disabled by default, but if it is enabled, the code last typed on the door sits in clear text in Home Assistant's state and recorder.

## Supported devices

All Onesti Products AS locks with the Connect Module (ZMNC010, the Zigbee and Bluetooth radio module; only its Zigbee side is used here):

| Zigbee model     | Product                    | Status                                        |
| ---------------- | -------------------------- | --------------------------------------------- |
| NimlyPRO         | Nimly Touch Pro            | Tested by maintainer (PIN, RFID, fingerprint) |
| NimlyCodePRO     | Nimly Code Pro             | Reported working by users (#4, #5)            |
| NimlyPRO24       | Nimly Touch Pro (2024)     | Assumed                                       |
| NimlyCode        | Nimly Code                 | Assumed                                       |
| NimlyTouch       | Nimly Touch                | Assumed                                       |
| NimlyIn          | Nimly InDoor               | Assumed                                       |
| NimlyShared      | Nimly Shared               | Assumed                                       |
| easyCodeTouch_v1 | EasyAccess EasyCodeTouch   | Assumed                                       |
| EasyCodeTouch    | EasyAccess EasyCodeTouch   | Assumed                                       |
| EasyFingerTouch  | EasyAccess EasyFingerTouch | Assumed                                       |
| EasyCode903G2    | Unknown                    | Vendor-documented, not yet reported by a user |

"Assumed" means nobody has reported on that model yet. The locks are the same Onesti hardware with the same Zigbee module, sold under Nimly, EasyAccess, Keyfree, Salus, Homely, Forebygg and other brands, so they are expected to work. If yours does, or does not, say so in an [issue](https://github.com/fredrik-lindseth/onesti-lock/issues).

`EasyCode903G2` comes from Onesti's own 2021 Zigbee spec for the module, not from a user report, and its market product name is unknown. It is not the `EasyCode903G2.1` seen once on a lock with a different manufacturer name and different Zigbee silicon, which no integration or converter supports; see [docs/hardware-generations.md](docs/hardware-generations.md).

The table does not limit what you can set up. A Connect Module sometimes reports a sibling model name rather than the lock it sits on (a Code Pro has shown up as NimlyTwist), so setup offers any ZHA device from Onesti Products AS with a Door Lock cluster and logs a warning for a model string it does not know. Please report that string too.

A lock without the Zigbee Connect Module cannot be used, since the integration only reaches the lock through ZHA. Neither can a lock paired with Zigbee2MQTT.

## Installation

### Via HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fredrik-lindseth&repository=onesti-lock&category=integration)

The button adds this repository to HACS. Install "Onesti Lock" and restart Home Assistant. To add it by hand, go to HACS → ⋮ (top right) → Custom repositories and add `https://github.com/fredrik-lindseth/onesti-lock` as Integration.

### Manual

1. Copy `custom_components/onesti_lock` to your `config/custom_components/`
2. Restart Home Assistant

## Setup

You need a Zigbee coordinator running ZHA, and the lock needs its Zigbee Connect Module (ZMNC010). The module is an accessory sold separately from the lock, and some older modules report the wrong model string ([#4](https://github.com/fredrik-lindseth/onesti-lock/issues/4)).

Pair the module with ZHA first. The lock sleeps to save battery, so pairing only works if you reset the module and then keep the radio awake with a PIN and `#` on the keypad while ZHA searches. The steps are in [Pairing with ZHA after reset](docs/debugging.md#pairing-with-zha-after-reset), and [Module not discovered during pairing](docs/debugging.md#module-not-discovered-during-pairing) covers the usual problems.

A lock that is already paired with Zigbee2MQTT has to move. Remove it in Z2M, reset the module and pair it with ZHA as above. The PIN codes are stored in the lock and survive re-pairing.

Then add the integration:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=onesti_lock)

Or go to **Settings → Devices & Services → Add Integration → Onesti Lock**. The form asks for one thing, **Lock**: pick your lock from the list, where each entry shows the model and the IEEE address ZHA gave it. The list only holds locks that are already paired with ZHA, so there is nothing to look up beforehand. The sensors show up on their own. The master slot setting and the PIN codes are set afterwards, under [Managing access](#managing-access).

If the Zigbee Connect Module is later replaced, the lock is the same lock but its Zigbee address is not. Use **Reconfigure** on the entry and pick the new module: the names, the PIN status and every sensor stay as they are.

This is only needed for the first lock. After that, pairing an Onesti lock with ZHA is enough: it turns up under **Discovered** on the integrations page with its model and IEEE address, and you either set it up from there or press Ignore. Home Assistant does not load a custom integration that has no config entry, which is why the first one cannot be found this way. Telling two locks apart in services and automations is covered under [Multiple locks](docs/user-guide.md#multiple-locks).

Removing the integration again is described in the [user guide](docs/user-guide.md#removing-the-integration). Clear the codes that should stop working first: they live on the lock, and removing the integration leaves them there.

## What you get

Each lock gets ten slot sensors showing the name on the slot and whether it has a PIN, an activity sensor that reads like "Kari unlocked with code" and survives a restart, and three diagnostic sensors with the lock's PIN capacity and code length, off by default. The lock entity and the battery stay with ZHA. Every decoded operation also fires an `onesti_lock_activity` event with the slot, the name, the action and the source, which is what automations trigger on. Nothing is polled: the lock reports on its own, and the integration sends nothing on a timer. The attributes, the event payload and automation examples are in the [user guide](docs/user-guide.md#entities).

Four actions, `onesti_lock.set_pin`, `clear_pin`, `set_name` and `clear_slot`, do from automations and scripts what the Configure menu does by hand, and reach every slot rather than the ten listed ones. Fields and limits are under [From services](docs/user-guide.md#from-services).

Strings come in English, Norwegian (bokmål), Swedish and Danish, following the Home Assistant server language ([Languages](docs/user-guide.md#languages)).

## Managing access

**Settings → Devices & Services → Onesti Lock → Configure**

- **Set PIN code**: pick a slot, enter a name and a code.
- **Clear PIN code**: lists only the slots that have a PIN code, and removes the code. The name stays.
- **Name a user slot**: name any slot from 0 to 999, master slots included, for RFID tags, fingerprints, the master code and so on. An empty name removes it.
- **View user slots**: the master slots and the ten user slots.
- **Settings**: how many slots from 0 up hold master codes on this lock (1-3, default 3). User slots start after them, and nothing in Home Assistant writes a PIN to them. A Code Pro has only one master slot, so set it to 1 there. Slot 0 is never written, whatever the setting.

Set PIN code and View user slots cover the ten slots from the first user slot. Use the `set_pin` action for anything higher. The PIN length is whatever the lock reports, 4-8 digits until it has, and a code the lock refuses is reported as refused, not as unreachable.

Names live in Home Assistant and the codes on the lock. Tags and fingerprints are enrolled at the lock and named here, so events show "Fredrik" instead of "Slot 3" ([Managing access](docs/user-guide.md#managing-access) in the user guide has the details).

Slot 0 is the master code on every model, and on all but the Code Pro slots 1 and 2 are master codes too, which is what the Settings value is for. Which slots the manuals give to fingerprints and key tags, and why to change the factory code first, is in [docs/slot-numbering.md](docs/slot-numbering.md).

## Blueprints

HACS installs the integration but not the blueprints. Import each one you want from its button, or copy the link on its name and paste it under **Settings → Automations & Scenes → Blueprints → Import Blueprint**.

- [**Unlock notification**](https://raw.githubusercontent.com/fredrik-lindseth/onesti-lock/main/blueprints/automation/unlock_activity_notify.yaml) tells you who unlocked and how. It reads the activity sensor, so it needs this integration.<br>
  [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Ffredrik-lindseth%2Fonesti-lock%2Fmain%2Fblueprints%2Fautomation%2Funlock_activity_notify.yaml)
- [**Connectivity alert**](https://raw.githubusercontent.com/fredrik-lindseth/onesti-lock/main/blueprints/automation/lock_connectivity_alert.yaml) notifies you when the lock goes offline or comes back. It uses ZHA's lock entity and works without this integration.<br>
  [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Ffredrik-lindseth%2Fonesti-lock%2Fmain%2Fblueprints%2Fautomation%2Flock_connectivity_alert.yaml)
- [**Goodnight lock**](https://raw.githubusercontent.com/fredrik-lindseth/onesti-lock/main/blueprints/automation/goodnight_lock.yaml) locks the door at a set time. It also uses ZHA's lock entity only.<br>
  [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Ffredrik-lindseth%2Fonesti-lock%2Fmain%2Fblueprints%2Fautomation%2Fgoodnight_lock.yaml)

Imported blueprints are copies that nothing updates. The unlock notification and connectivity alert from v1.3.0 and earlier did not pass their inputs on to their templates, so if you imported them then, import them again and overwrite.

## Security

A PIN code opens your door, and several parts of Home Assistant can write one to disk. This integration keeps codes out of its own states and log lines: it never reads the attribute where the lock reports the last used PIN, and it masks digit runs in the error text it logs. It cannot cover ZHA's own last PIN code sensor (off by default), ZHA's diagnostics download, zigpy debug logging, or the recorder and the automation trace when `set_pin` is called as an action rather than from the Configure menu. What each of those stores, and what to do about it, is in [docs/debugging.md](docs/debugging.md#pin-codes-appear-in-raw-logs-and-diagnostics). Scrub codes from anything you paste into an issue.

Every release from 1.4.0 carries an attestation binding the ZIP HACS installs to the commit and the workflow that built it. [SECURITY.md](SECURITY.md) says how to verify one.

## Limitations

The full list, with the workarounds, is in the [user guide](docs/user-guide.md#limitations). In short:

- **Zigbee2MQTT is not supported.** Its `onesti.ts` converter decodes the same attribute into raw numbers, and a lock on Z2M has to move to ZHA.
- **The lock sleeps.** A command that times out is retried after a wake, and the wake is a lock command: an unlocked door gets locked, and an open door gets its bolt driven out into the air. Close the door before managing codes, and keep a Zigbee router near it.
- **Events can stop after a battery change** until the lock is reconfigured in ZHA.
- **RFID tags and fingerprints are enrolled at the keypad**, not over Zigbee, and a code changed at the keypad is not seen here.
- **ZHA has no public API for what this reads**, so a Home Assistant update can break event delivery. A repair issue then says so.
- **No firmware updates over Zigbee**, and going back to an older version of the integration is untested.

## If you're buying a new lock

Short version: none of the locks we checked meets the full list of local, Home-Assistant-native, with per-user attribution for code, tag and fingerprint, on a Scandinavian door. These locks come closest, and with this integration they are the only one we found that does all three credential types locally, but the firmware has real flaws worth knowing before you buy. The honest case for and against, a table of every lock we checked, and what owners report is in [docs/buying-a-lock.md](docs/buying-a-lock.md).

## Troubleshooting

The [debugging guide](docs/debugging.md) describes each problem with its symptom, cause and fix, starting with the ones people run into most, and ends with how to turn on debug logging before you open an [issue](https://github.com/fredrik-lindseth/onesti-lock/issues). The log can contain PIN codes, so read [Security](#security) before you paste it.

## Documentation

| Document                                                   | Content                                                          |
| ---------------------------------------------------------- | ---------------------------------------------------------------- |
| [User guide](docs/user-guide.md)                           | Entities, actions, the event, multiple locks, automation examples, limitations, removal |
| [Buying a lock](docs/buying-a-lock.md)                     | Honest case for and against, and every alternative we checked    |
| [Debugging guide](docs/debugging.md)                       | Pairing, LED indicators, troubleshooting, debug logging          |
| [Technical details](docs/technical.md)                     | Event decoding, coordinator, auto-wake, ZHA internals            |
| [Slot numbering](docs/slot-numbering.md)                   | Master and user slots per model, Zigbee vs BLE vs cloud          |
| [Zigbee captures](docs/zigbee-protocol/zigbee-captures.md) | Raw ZCL frames and verified protocol values                      |
| [Upstream status](docs/upstream-status.md)                 | Open threads in the ZHA quirk and the Z2M converter              |
| [Vendor Zigbee spec](docs/zigbee-protocol/elife-module-spec.md) | Onesti's own 2021 spec for the module, and where it disagrees with what we measure |
| [Hardware generations](docs/hardware-generations.md)       | Every lock seen in public reports: model string, radio, firmware fields |
| [Community reports](docs/community-reports.md)             | What owners on the forums have measured, relayed and claimed, marked as such |
| [Feature parity](docs/feature-parity.md)                   | What the vendor app and hub do that this does not, and why       |
| [Vendor manuals](docs/manuals/README.md)                   | Which manuals exist per model and brand, and where to get them   |
| [Cloud API status](docs/cloud-api-status.md)               | Reverse engineering of the vendor cloud, progress and next steps |
| [BLE library](docs/nimly-ble-app/ble-library.md)           | A Bluetooth protocol library in the repo; not used by the integration and not yet tested on a lock |

Bugs and questions go to the [issue tracker](https://github.com/fredrik-lindseth/onesti-lock/issues).

## Contributing

Pull requests are welcome. [AGENTS.md](AGENTS.md) describes the architecture, the rules and the pitfalls, and applies to people as much as to agents. Before you open one, run `python3 scripts/ci_sim.py`, which runs ruff and then `tests/` in the same uv environment as CI, and catches a test that imports Home Assistant. To add a language, copy `custom_components/onesti_lock/translations/en.json` and translate it, `common` section included. Taking part here means following the [Code of Conduct](CODE_OF_CONDUCT.md).

The integration is built to follow Home Assistant's [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/), a list of 54 rules about setup, error handling, documentation, entities and typing. [`quality_scale.yaml`](custom_components/onesti_lock/quality_scale.yaml) goes through them rule by rule and says whether each is met or does not apply, with a reason for every exemption, and [`tests/test_quality_scale.py`](tests/test_quality_scale.py) mirrors hassfest's own check of the rule list and the file's schema. No level is claimed: a level is something the core team assigns on review, as part of an integration being included in Home Assistant, and the file is a checklist rather than a badge.

## License

MIT License
