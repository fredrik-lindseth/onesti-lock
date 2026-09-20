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

The lock reports every event on a custom Zigbee attribute. ZHA's stock quirk exposes it as raw numbers at most, and an open upstream report says those entities do not update live. This integration decodes it into who locked or unlocked the door, by the name you gave the slot, and how (keypad, RFID, fingerprint). You can also manage PIN codes from Home Assistant and name every slot. You get an activity sensor, an event for automations and three automation blueprints.

The vendor's own route to the same data is the Nimly Connect app, which needs a Connect Bridge gateway and sends every lock event through the iotiliti cloud ([docs/nimly-connect-app/app-architecture.md](docs/nimly-connect-app/app-architecture.md)). This integration talks to the lock over the Zigbee network you already run, so events stay on your own hardware.

Requires ZHA and Home Assistant 2025.6 or newer. Zigbee2MQTT is not supported, see [Limitations](#limitations).

## Supported devices

All Onesti Products AS locks with the Zigbee Connect Module (ZMNC010):

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

"Assumed" means nobody has reported on that model yet. The locks are the same Onesti hardware with the same Zigbee module, sold under Nimly, EasyAccess, Keyfree, Salus, Homely, Forebygg and other brands, so they are expected to work. If yours does, or does not, say so in an [issue](https://github.com/fredrik-lindseth/onesti-lock/issues).

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

Or go to **Settings → Devices & Services → Add Integration → Onesti Lock**. The form asks for one thing, **Lock**: pick your lock from the list, where each entry shows the model and the IEEE address ZHA gave it. The list only holds locks that are already paired with ZHA, so there is nothing to look up beforehand. The sensors show up on their own. With more than one lock, see [Multiple locks](#multiple-locks). The master slot setting and the PIN codes are set afterwards, under [Managing access](#managing-access).

If the Zigbee Connect Module is later replaced, the lock is the same lock but its Zigbee address is not. Use **Reconfigure** on the entry and pick the new module: the names, the PIN status and every sensor stay as they are.

This is only needed for the first lock. After that, pairing an Onesti lock with ZHA is enough: it turns up under **Discovered** on the integrations page with its model and IEEE address, and you either set it up from there or press Ignore. Home Assistant does not load a custom integration that has no config entry, which is why the first one cannot be found this way.

## Entities

ZHA and this integration split the work. ZHA owns the lock itself: the lock entity you lock and unlock with, the battery, and whatever sensors ZHA's quirk adds. This integration adds names, activity and PIN management. On Home Assistant 2026.9 and newer that is a device of its own, named after the model and the last four characters of the address, shown under ZHA's device for the same lock; on older releases the two are one device with everything on it. Entities named `sensor.onesti_products_as_*` come from ZHA's quirk, not from this integration.

Each lock gets ten slot sensors, one activity sensor and three diagnostic sensors that are off by default. The slot sensors start at the first user slot (see [Managing access](#managing-access)), so slots 3-12 by default and 1-10 on a Code Pro set to one master slot. Changing that setting moves the row and removes the sensors that fell out of it. A slot sensor shows the name on the slot, or "Vacant", with `slot_id` and `has_pin` as attributes.

The activity sensor reads like "Kari unlocked with code" and has these attributes:

| Attribute        | Value                                                                                              |
| ---------------- | -------------------------------------------------------------------------------------------------- |
| `user_slot`      | Slot number, or `null` when no user was involved. `0` is the master code, tag or finger.           |
| `user_name`      | The slot's name. Never `null` when `user_slot` is set: an unnamed slot gives "Slot 5" or "Master". |
| `action`         | `lock`, `unlock` or `unknown`                                                                      |
| `source`         | `keypad`, `rfid`, `fingerprint`, `zigbee`, `auto`, `unattributed` or `unknown`                     |
| `timestamp`      | When the event arrived, in UTC as ISO 8601                                                         |

Three more sensors show what the lock says about itself: PIN slots, shortest PIN code and longest PIN code. They are diagnostic sensors and switched off when the integration is set up, since the numbers are the same for every lock of a model and only matter when a code is refused. Turn them on under the device, and they show a value once the lock has been awake and answered. Up to and including 1.4.0 the same three numbers were attributes on the activity sensor.

All the sensors go unavailable while ZHA is not running, since no lock event can reach Home Assistant then; a lock that is only asleep keeps them as they are.

The sensor text and the "Slot 5" and "Master" fallbacks follow the server language. The raw values in `action` and `source` do not, so use those in automations. The last activity survives a restart.

Auto-lock does not change the sensor, so "Kari unlocked with code" stays visible after the door relocks. Locking from a dashboard does change it, to "Locked via Zigbee". The lock command the integration sends to wake a sleeping lock (see [Limitations](#limitations)) does not: a Zigbee lock within 30 seconds of a wake is taken to be that command. NimlyCodePRO reports Zigbee commands, auto-relock and the interior keypad with the same source code, so there `source` is `unattributed` and the sensor reads plain "Locked" or "Unlocked". An unattributed lock with no user is treated as auto-relock.

Every decoded event also fires `onesti_lock_activity`, auto-lock included. The payload is `ieee`, `user_slot`, `user_name`, `action` and `source`, with the same values as above. Automation examples are in [docs/technical.md](docs/technical.md#onesti_lock_activity-event).

Entity IDs come from the server language when the entity is created, so a lock set up on a Norwegian server gets `sensor.*_siste_aktivitet` and keeps it.

## Data updates

The integration never polls. When someone locks or unlocks the door, whether at the keypad, with a tag or finger, from a dashboard or by auto-lock, the lock sends a report on its own. ZHA receives it and the integration decodes it, so the activity sensor and the event change as soon as the report arrives. Nothing is sent to the lock on a timer, which would drain a battery lock that sleeps between uses.

The lock wakes up when it is used, so sleep does not delay events. It does get in the way of commands, since Home Assistant can only reach the lock while its radio is awake. A PIN change may therefore need the wake-up described under [Limitations](#limitations).

The PIN capacity and allowed code length are read from the lock once, the first time it is awake after setup, and kept after that. The slot sensors show what Home Assistant has written to the lock, and the lock is never asked what it holds, so a code changed on the keypad does not show up here. The lock state and the battery level come from ZHA's own entities, which ZHA keeps up to date on its own terms.

## Managing access

### From the UI

**Settings → Devices & Services → Onesti Lock → Configure**

- **Set PIN code**: pick a slot, enter a name and a code.
- **Clear PIN code**: lists only the slots that have a PIN code, and removes the code. The name stays.
- **Name a user slot**: name any slot from 0 to 999, master slots included, for RFID tags, fingerprints, the master code and so on. An empty name removes it.
- **View user slots**: the master slots and the ten user slots.
- **Settings**: how many slots from 0 up hold master codes on this lock (1-3, default 3). User slots start after them, and nothing in Home Assistant writes a PIN to them. A Code Pro has only one master slot, so set it to 1 there. Slot 0 is never written, whatever the setting.

Set PIN code and View user slots cover the ten slots from the first user slot. Use the `set_pin` service for anything higher.

The allowed PIN length comes from the lock. Until it has reported one, 4-8 digits is the rule, and no code shorter than 4 digits is accepted whatever the lock says. If the lock answers that it refused a code, as a duplicate of another slot's code or because its memory is full, Home Assistant says so instead of reporting it unreachable. Which answers the lock actually sends has not been checked on a real lock, so try a new code on the keypad.

When someone unlocks with the master code, fingerprint or tag on slot 0, the activity sensor and the event use the name you gave slot 0, or "Master" if it has none. Menu labels follow the server language.

### From services

```yaml
action: onesti_lock.set_pin
data:
  slot: 3
  name: "Kari"
  code: "5478"
```

| Service                  | What it removes or sets              | Slots accepted         |
| ------------------------ | ------------------------------------ | ---------------------- |
| `onesti_lock.set_pin`    | Sets a PIN code and a name           | first user slot to N-1 |
| `onesti_lock.clear_pin`  | Removes the PIN code, keeps the name | first user slot to 999 |
| `onesti_lock.set_name`   | Sets the name, touches no code       | 0-999                  |
| `onesti_lock.clear_slot` | Removes the PIN code and the name    | first user slot to 999 |

The first user slot is the Settings value, 3 by default. N is the number of PIN users the lock reports. NimlyPRO and NimlyCodePRO report 50, so the highest slot `set_pin` takes is 49, and until the lock has reported, the ceiling is 999. `clear_pin` and `clear_slot` go to 999 so a slot filled before the limit was known can still be emptied.

A mistake in the call itself, a slot out of range, a PIN of the wrong length or a lock that is not set up, fails as a validation error: the message appears where the call was made and nothing is logged as an error. When the call was fine but the lock was unreachable or refused the write, the service fails with the lock's answer instead, and that one does reach the log.

The lock usually sleeps when Home Assistant starts, so the integration also asks for the PIN capacity and length after each command that reached the lock and whenever the lock reports something, until it has answered once. The answer is kept, also across restarts.

### Where names are stored

Names and PIN status live in Home Assistant, in the config entry under `.storage`, never on the lock. They survive updates and restarts and are part of Home Assistant backups. Removing the integration deletes them, while the codes stay on the lock, see [Removing the integration](#removing-the-integration).

### RFID and fingerprint

RFID tags and fingerprints are enrolled on the lock itself, with the master code and keypad sequences in your lock's manual. Then name the slot here, so events show "Fredrik" instead of "Slot 3".

## Multiple locks

There is one entry per lock. With the first one set up, the next lock is offered under **Discovered** as soon as it is paired with ZHA, so you only confirm it; **Add Integration** still works if you would rather do it by hand. Either way the model and the IEEE address are shown, so with two of the same model you need the IEEE address to tell them apart. A lock you press Ignore on is not offered again. Locks already set up are left out of the list. ZHA shows the address on the lock's device page under Zigbee info, in the form `00:0d:6f:00:11:22:33:44`. Each lock's device is named after its model and the last four characters of that address, so two of the same model are still told apart; rename them to whatever the doors are called.

The services take a `device_id`, and the UI shows a lock picker for it. On Home Assistant 2026.9 and newer, pick this integration's device for the lock, not the ZHA device below it. Scripts can pass `ieee` instead, and case does not matter there. With more than one lock and neither given, the call fails with a `multiple_locks` error listing the IEEE addresses, rather than guessing which door to program.

Events carry `ieee`, which is how an automation tells the locks apart. Event data is matched exactly, so copy the address as ZHA shows it, in lower case:

```yaml
triggers:
  - trigger: event
    event_type: onesti_lock_activity
    event_data:
      ieee: "00:0d:6f:00:11:22:33:44"
      action: unlock
```

## Blueprints

HACS installs the integration but not the blueprints. Import each one you want from its button, or copy the link on its name and paste it under **Settings → Automations & Scenes → Blueprints → Import Blueprint**.

- [**Unlock notification**](https://raw.githubusercontent.com/fredrik-lindseth/onesti-lock/main/blueprints/automation/unlock_activity_notify.yaml) tells you who unlocked and how. It reads the activity sensor, so it needs this integration.<br>
  [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Ffredrik-lindseth%2Fonesti-lock%2Fmain%2Fblueprints%2Fautomation%2Funlock_activity_notify.yaml)
- [**Connectivity alert**](https://raw.githubusercontent.com/fredrik-lindseth/onesti-lock/main/blueprints/automation/lock_connectivity_alert.yaml) notifies you when the lock goes offline or comes back. It uses ZHA's lock entity and works without this integration.<br>
  [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Ffredrik-lindseth%2Fonesti-lock%2Fmain%2Fblueprints%2Fautomation%2Flock_connectivity_alert.yaml)
- [**Goodnight lock**](https://raw.githubusercontent.com/fredrik-lindseth/onesti-lock/main/blueprints/automation/goodnight_lock.yaml) locks the door at a set time. It also uses ZHA's lock entity only.<br>
  [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Ffredrik-lindseth%2Fonesti-lock%2Fmain%2Fblueprints%2Fautomation%2Fgoodnight_lock.yaml)

Imported blueprints are copies that nothing updates. The unlock notification and connectivity alert from v1.3.0 and earlier did not pass their inputs on to their templates, so if you imported them then, import them again and overwrite.

## Use cases

- **Know who came in.** The [unlock notification](#blueprints) blueprint sends "Kari unlocked via keypad" to your phone, so while you are out you can see whether it was the cleaner, the neighbour feeding the cat or one of the family.
- **The kids are home from school.** Give each child a slot with their own code or tag, and trigger on their name, so you get a message when one of them unlocks on a weekday afternoon:

  ```yaml
  triggers:
    - trigger: event
      event_type: onesti_lock_activity
      event_data:
        user_name: "Emma"
        action: unlock
  conditions:
    - condition: time
      after: "13:00"
      before: "18:00"
      weekday: [mon, tue, wed, thu, fri]
  actions:
    - action: notify.mobile_app_your_phone
      data:
        message: "Emma is home"
  ```

- **A code for the plumber.** An automation calls `onesti_lock.set_pin` on a spare slot the morning the job starts and `onesti_lock.clear_pin` when it ends, so the code only works on those days. The events then show when the plumber came and went. Setting a code can physically lock an unlocked door (see [Limitations](#limitations)), and the code ends up in the recorder and the automation trace (see [Security](#security)).
- **Who opened the door, and when.** The activity sensor's history and the logbook list every lock and unlock with the name and the method, so you can look back at who came in last Tuesday.

## Security

A PIN code opens your door, and several parts of Home Assistant can write them to disk.

This integration does not. It never reads the attribute where the lock reports the last used PIN, it masks digit runs of 4 or more when it logs a failed command, and it never accepts a PIN shorter than 4 digits, so the mask always covers a real code. These can still leak one:

- ZHA's quirk has its own last PIN code sensor. It is disabled by default, but if it is enabled, the recorder stores every code used.
- ZHA's **Download diagnostics** on the lock's device dumps zigpy's attribute cache, last used PIN included.
- Debug logging for `zigpy.zcl` prints raw frames with the last used PIN, and every command sent to the lock, so a PIN you set shows up in clear text.
- Calling the `onesti_lock.set_pin` action puts the code in the recorder database, since Home Assistant records every action call with its data, and from an automation or script also in that run's trace. The options flow does not.

Scrub codes from logs, diagnostics and traces before you paste them into an issue or a forum post. If you already shared one, change the code on the lock.

Versions 1.1.0 through 1.2.0 of this integration exposed the last used PIN as a state attribute, which put real codes in the recorder database. If you ran one of them, follow the cleanup in [docs/debugging.md](docs/debugging.md#6-cleanup-after-versions-110-through-120).

## Slot numbering

The manuals disagree between models, so the numbering depends on the model:

| Model          | Master codes                       | User codes | Source                                                                                                                        |
| -------------- | ---------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Touch Pro, PRO | 000 (factory `123`), 001-002 extra | 003-999    | [Touch Pro manual (nimly.se, 2024)](https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf)  |
| Code           | 000 (factory `123`), 001-002 extra | 003-999    | [Code installation guide (nimly.se, 2022)](https://nimly.se/wp-content/uploads/2023/11/EN-Code-Installation-Guide-130922.pdf) |
| Code Pro       | 000 (factory `123`)                | 001-999    | [Code Pro product guide (nimly.se, 2026)](https://nimly.se/wp-content/uploads/2026/04/EN-Code-Pro-Product-Guide-120126.pdf)   |

Change the factory code straight away. According to the manuals, master codes cannot be deleted, only overwritten, and the master code also opens the door (the Code Pro can be set to use it for programming only). Fingerprints and key tags have their own ranges in each manual (the Touch Pro takes user fingerprints on 003-199), so check yours before naming those slots.

The lock does not tell the models apart over Zigbee: a Code Pro has reported itself as NimlyTwist ([#5](https://github.com/fredrik-lindseth/onesti-lock/issues/5)). That is why the number of master slots is a setting. The default of 3 is safe on every model. How Zigbee, BLE and cloud slot numbers relate is in [docs/slot-numbering.md](docs/slot-numbering.md).

## Languages

English, Norwegian (bokmål), Swedish and Danish. Sensor states, entity names, options flow labels and service errors follow the Home Assistant server language (Settings > System > General), not each user's frontend language. Reload the integration after upgrading or after changing the server language.

## Limitations

1. **Zigbee2MQTT is not supported.** Z2M's `onesti.ts` converter decodes the same attribute and gives you raw slot numbers, but no named users, no readable activity messages and no PIN management UI. A comparison is in [docs/technical.md](docs/technical.md#comparison-with-zigbee2mqtt). If you want to stay on Z2M, stay with the converter.

2. **Sleepy device**: the lock sleeps aggressively, so commands may time out on the first attempt. The integration then wakes the lock and retries, and it wakes it by sending a **lock command**.

   If the door is unlocked when you set or clear a PIN, it will physically lock. If the door is standing open, the bolt is driven out into the air. Close the door before managing PIN codes, or wake the lock yourself first by turning the thumb-turn.

   Place a Zigbee router right next to the door as well, since the metal casing works like a Faraday cage.

3. **Attribute reporting after a battery change**: the lock may stop sending activity events after new batteries. Try "Reconfigure" in ZHA, after waking the lock by entering a code. If that fails, remove and re-pair the lock.

4. **RFID and fingerprint enrollment** only works from the physical keypad or the BLE app, not over Zigbee.

5. **Slot state drift**: if PINs are changed on the keypad or in another app, the integration's slot data can fall out of sync. Use "View user slots" to check.

6. **No OTA firmware updates over Zigbee**: the module lists the OTA Upgrade cluster, but no firmware image for it exists in the community zigbee-OTA index, so ZHA has nothing to offer.

7. **ZHA internals**: ZHA has no public API for what this integration reads, so a Home Assistant update can break it. If that happens, a repair issue titled "Lock events are not being received" appears under Settings → System → Repairs. PIN codes may still work, but the activity sensor and the event go quiet. Open an issue with your Home Assistant version. When ZHA restarts with the lock, the integration reconnects by itself, and a ZHA that is still starting when Home Assistant boots is simply waited for.

8. **Dashboard locks right after a wake**: a lock from a dashboard within 30 seconds of the integration waking the lock looks the same as the wake itself, so the activity sensor does not show it. The `onesti_lock_activity` event still fires.

9. **Going back to an older version is untested.** From 1.4.0 on, HACS installs the ZIP attached to the release instead of the tag's source tree. The ZIPs on the 1.0.0 to 1.3.0 releases hold the same flat layout, so picking one of them in HACS should land the right files, but nobody has tried it. If a downgrade leaves Home Assistant without the integration, delete `config/custom_components/onesti_lock`, install the version you want again and restart. Releases before 1.0.0 are the old `nimly_pro` integration and are not a rollback target at all. Upgrading is not affected.

## If you're buying a new lock

Short version: no lock on the market meets the full list of local, Home-Assistant-native, with per-user attribution for code, tag and fingerprint, on a Scandinavian door. These locks come closest, and with this integration they are the only one that does all three credential types locally, but the firmware has real flaws worth knowing before you buy. The honest case for and against, a table of every lock we checked, and what owners report is in [docs/buying-a-lock.md](docs/buying-a-lock.md).

## Troubleshooting

The [debugging guide](docs/debugging.md) describes each problem with its symptom, cause and fix. The ones people run into most:

- Setup says no lock was found: [Lock not offered when adding the integration](docs/debugging.md#lock-not-offered-when-adding-the-integration).
- The lock will not pair with ZHA: [Module not discovered during pairing](docs/debugging.md#module-not-discovered-during-pairing).
- Setting a PIN fails with "Could not reach the lock": [the lock is asleep or out of range](docs/debugging.md#could-not-reach-the-lock-in-options-flow).
- The activity sensor stopped changing, often after new batteries: [Activity sensor not updating](docs/debugging.md#3-activity-sensor-not-updating).
- A repair issue says lock events are not being received: [Repair issue](docs/debugging.md#repair-issue-lock-events-are-not-being-received).

If none of that helps, turn on [debug logging](docs/debugging.md#4-debug-logging) and open an [issue](https://github.com/fredrik-lindseth/onesti-lock/issues). The log can contain PIN codes, so read [Security](#security) before you paste it.

## Removing the integration

Remove each lock's entry, then the integration itself:

1. Clear any PIN codes that should stop working, with **Clear PIN code** under Configure or the `onesti_lock.clear_slot` action. The codes live on the lock, and removing the integration leaves them there, still opening the door.
2. Go to **Settings → Devices & Services → Onesti Lock**, open the ⋮ menu on each lock's entry and pick **Delete**. This removes the Onesti Lock device and its sensors, and deletes the slot names and PIN status stored in Home Assistant.
3. In HACS, open Onesti Lock, pick **Remove** from the ⋮ menu, and restart Home Assistant. With a manual install, delete `config/custom_components/onesti_lock` and restart.

ZHA's device and its lock entity are not touched, so you can still lock and unlock from Home Assistant. Imported blueprints and automations that use them stay behind until you delete them yourself.

## Documentation

| Document                                                   | Content                                                          |
| ---------------------------------------------------------- | ---------------------------------------------------------------- |
| [Buying a lock](docs/buying-a-lock.md)                     | Honest case for and against, and every alternative we checked    |
| [Debugging guide](docs/debugging.md)                       | Pairing, LED indicators, troubleshooting, debug logging          |
| [Technical details](docs/technical.md)                     | Event decoding, coordinator, auto-wake, automation examples      |
| [Slot numbering](docs/slot-numbering.md)                   | Zigbee vs BLE vs cloud slot mapping                              |
| [Zigbee captures](docs/zigbee-protocol/zigbee-captures.md) | Raw ZCL frames and verified protocol values                      |
| [Upstream status](docs/upstream-status.md)                 | Open threads in the ZHA quirk and the Z2M converter              |
| [Feature parity](docs/feature-parity.md)                   | What the vendor app and hub do that this does not, and why       |
| [Vendor manuals](docs/manuals/README.md)                   | Which manuals exist per model and brand, and where to get them   |
| [Cloud API status](docs/cloud-api-status.md)               | Reverse engineering of the vendor cloud, progress and next steps |
| [BLE library](docs/nimly-ble-app/ble-library.md)           | A Bluetooth protocol library in the repo; not used by the integration and not yet tested on a lock |

Bugs and questions go to the [issue tracker](https://github.com/fredrik-lindseth/onesti-lock/issues).

## Integration Quality Scale

Home Assistant's [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) is a list of 54 rules about setup, error handling, documentation, entities and typing. They are a good checklist for a custom integration, so this one is built to follow them. [`quality_scale.yaml`](custom_components/onesti_lock/quality_scale.yaml) goes through them rule by rule and says whether each one is met or does not apply, with a reason for every exemption.

No level is claimed here. A level is something the core team assigns on review, as part of an integration being included in Home Assistant, and the file is a checklist rather than a badge. [`tests/test_quality_scale.py`](tests/test_quality_scale.py) keeps it honest by mirroring hassfest's own check of the rule list and the file's schema.

## Contributing

Pull requests are welcome. [AGENTS.md](AGENTS.md) describes the architecture, the rules and the pitfalls, and applies to people as much as to agents. Before you open one, run `python3 scripts/ci_sim.py`, which runs ruff and then `tests/` in the same uv environment as CI, and catches a test that imports Home Assistant. To add a language, copy `custom_components/onesti_lock/translations/en.json` and translate it, `common` section included. Taking part here means following the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT License
