# User guide

What the integration gives you once a lock is set up, and how to use it. Installing, setting up and the PIN menu under Configure are in the [README](../README.md) ([Managing access](../README.md#managing-access)).

## Entities

ZHA owns the lock itself: the lock entity, the battery, and whatever sensors ZHA's quirk adds. This integration adds names, activity and PIN management. On Home Assistant 2026.9 and newer that is a device of its own, named after the model and the last four characters of the address and shown under ZHA's device for the same lock; on older releases the two are one device. Entities named `sensor.onesti_products_as_*` come from ZHA's quirk, not from here.

Each lock gets ten slot sensors, one activity sensor and three diagnostic sensors that are off by default. The slot sensors start at the first user slot (see [Managing access](#managing-access)), so slots 3-12 by default and 1-10 on a Code Pro set to one master slot. Changing that setting moves the row and removes the sensors that fell out of it. A slot sensor shows the name on the slot, or "Vacant", with `slot_id` and `has_pin` as attributes.

The activity sensor reads like "Kari unlocked with code" and has these attributes:

| Attribute   | Value                                                                                              |
| ----------- | -------------------------------------------------------------------------------------------------- |
| `user_slot` | Slot number, or `null` when no user was involved. `0` is the master code, tag or finger.           |
| `user_name` | The slot's name. Never `null` when `user_slot` is set: an unnamed slot gives "Slot 5" or "Master". |
| `action`    | `lock`, `unlock` or `unknown`                                                                      |
| `source`    | `keypad`, `rfid`, `fingerprint`, `zigbee`, `auto`, `unattributed` or `unknown`                     |
| `timestamp` | When the event arrived, UTC, ISO 8601                                                              |

The sensor text and the "Slot 5" and "Master" fallbacks follow the server language; the raw `action` and `source` values do not, so use those in automations. The last activity survives a restart. Entity IDs are made from the server language when the entity is created, so a lock set up on a Norwegian server gets `sensor.*_siste_aktivitet` and keeps it.

The three diagnostic sensors are PIN slots, shortest PIN code and longest PIN code, what the lock says about itself. They are off because the numbers are the same for every lock of a model and only matter when a code is refused. Turn them on under the device; they show a value once the lock has been awake and answered. Up to 1.4.0 the same numbers were attributes on the activity sensor.

All the sensors go unavailable while ZHA is not running, since no lock event can reach Home Assistant then. A lock that is only asleep keeps them as they are.

A lock the integration reads as system-initiated does not change the activity sensor, so "Kari unlocked with code" stays after the door relocks. Locking from a dashboard does change it, to "Locked via Zigbee", except within 30 seconds of the lock command the integration sends to wake a sleeping lock (see [Limitations](#limitations)), which the lock reports the same way. NimlyCodePRO reports Zigbee commands, auto-relock and the interior keypad with one source code, so there `source` is `unattributed` and the sensor reads plain "Locked" or "Unlocked"; an unattributed lock with no user is treated as auto-relock.

All of that rests on the source byte the lock sends, and the reading of `auto` is not settled. It is taken to mean the lock relocking itself, but in one NimlyPRO session every Zigbee command came back with that source too, so on some firmware it may mean no more than "no user to attribute this to" ([upstream status](upstream-status.md)).

Every decoded event also fires `onesti_lock_activity`, auto-lock included, see [the event](#the-onesti_lock_activity-event).

## Data updates

The integration never polls. The lock sends a report on its own for every lock and unlock, whoever or whatever did it, ZHA receives it, and the sensor and the event change as soon as it arrives. Nothing is sent to the lock on a timer, which would drain a lock that sleeps between uses.

Being used wakes the lock, so sleep does not delay events. It does get in the way of commands, since Home Assistant only reaches the lock while its radio is awake, and a PIN change may need the wake-up described under [Limitations](#limitations).

The PIN capacity and allowed code length are read from the lock once, the first time it is awake after setup, and kept. The slot sensors show what Home Assistant has sent to the lock and had accepted; the lock is never asked what it holds, so a code changed on the keypad does not show up here. What the lock reports back on a PIN write has not been checked on real hardware either, so a slot shown as set is worth trying on the keypad. Lock state and battery come from ZHA's own entities.

## Managing access

The menu under **Settings → Devices & Services → Onesti Lock → Configure** is described in the [README](../README.md#managing-access). It covers the ten slots from the first user slot; everything else goes through the actions below.

The first user slot is the Settings value in that menu, 3 by default. Which slots are master on which model, and where the manuals put fingerprints and key tags, is in [slot-numbering.md](slot-numbering.md).

The allowed PIN length comes from the lock. Until it has reported one, 4-8 digits is the rule, and no code shorter than 4 digits is accepted whatever the lock says. If the lock answers that it refused a code, as a duplicate of another slot's or because its memory is full, Home Assistant says so instead of reporting it unreachable. Which answers the lock actually sends has not been checked on a real lock, so try a new code on the keypad.

When someone unlocks with the master code, fingerprint or tag on slot 0, the sensor and the event use the name you gave slot 0, or "Master" without one. Menu labels follow the server language.

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

N is the number of PIN users the lock reports. A NimlyPRO reports 50, and a NimlyCodePRO interview posted upstream shows the same, so the highest slot `set_pin` takes there is 49; until the lock has reported, the ceiling is 999. `clear_pin` and `clear_slot` go to 999 so a slot filled before the limit was known can still be emptied.

A mistake in the call itself (slot out of range, PIN of the wrong length, a lock that is not set up) fails as a validation error: the message appears where the call was made and nothing is logged. When the call was fine but the lock was unreachable or refused the write, the service fails with the lock's answer, and that one does reach the log.

The lock usually sleeps when Home Assistant starts, so the capability read is also tried after each command that reached the lock and whenever the lock reports something, until it has answered once. The answer is kept across restarts.

Calling `set_pin` as an action puts the code in the recorder database and in the trace of the automation or script that made the call. The options flow does not; see [PIN codes in logs, diagnostics and the recorder](debugging.md#pin-codes-appear-in-raw-logs-and-diagnostics).

### Where names are stored

Names and PIN status live in Home Assistant, in the config entry under `.storage`, never on the lock. They survive updates and restarts and are in Home Assistant backups. Removing the integration deletes them, while the codes stay on the lock, see [Removing the integration](#removing-the-integration).

### RFID and fingerprint

Tags and fingerprints are enrolled on the lock itself, with the master code and the keypad sequences in your lock's manual. Then name the slot here, so events show "Fredrik" instead of "Slot 3".

## Multiple locks

One entry per lock. With the first set up, the next lock is offered under **Discovered** as soon as it is paired with ZHA, and **Add Integration** still works by hand. Both show the model and the IEEE address, so two of the same model are told apart by the address, which ZHA shows on the lock's device page under Zigbee info as `00:0d:6f:00:11:22:33:44`. A lock you press Ignore on is not offered again, and locks already set up are left out. Each device is named after the model and the last four characters of the address; rename them to whatever the doors are called.

The services take a `device_id`, and the UI shows a lock picker for it. On Home Assistant 2026.9 and newer, pick this integration's device, not the ZHA device below it. Scripts can pass `ieee` instead, upper or lower case. With more than one lock and neither given, the call fails with a `multiple_locks` error listing the addresses rather than guessing which door to program.

Events carry `ieee`, which is how an automation tells the locks apart. Event data is matched exactly, so copy the address as ZHA shows it, in lower case:

```yaml
triggers:
  - trigger: event
    event_type: onesti_lock_activity
    event_data:
      ieee: "00:0d:6f:00:11:22:33:44"
      action: unlock
```

## The `onesti_lock_activity` event

Every operation event decoded from attrid `0x0100` fires `onesti_lock_activity`, auto-lock and the wake echo included, so automations see everything the activity sensor leaves out. The payload:

| Key         | Value                                                                          |
| ----------- | ------------------------------------------------------------------------------ |
| `ieee`      | The lock's IEEE address as stored in the config entry                          |
| `user_slot` | Slot number, `0` for the master credential, `null` when no user was involved   |
| `user_name` | Name for `user_slot`, `null` exactly when `user_slot` is `null`                |
| `action`    | `lock`, `unlock` or `unknown`                                                  |
| `source`    | `zigbee`, `keypad`, `fingerprint`, `rfid`, `unattributed`, `auto` or `unknown` |

`user_slot` is `null` for slot 0 from a source other than keypad, fingerprint or rfid (see [How user identification works](technical.md#how-user-identification-works)). Otherwise it is the slot the lock reported.

`user_name` is never `null` for a known slot: it is the name set on the slot, or "Master" for slot 0 and "Slot N" for any other, in the server language as loaded at setup. A template therefore cannot tell an unnamed slot from a named one by testing `user_name`. Test `user_slot` against `null` to know whether a user was involved.

The activity sensor carries the same four fields as [attributes](#entities), plus `timestamp`.

## Automation examples

Notify on every unlock by a person, whichever lock it was:

```yaml
automation:
  - alias: "Notify when someone unlocks the front door"
    triggers:
      - trigger: event
        event_type: onesti_lock_activity
        event_data:
          action: unlock
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.user_slot is not none }}"
    actions:
      - action: notify.notify
        data:
          title: "Door unlocked"
          message: >
            {{ trigger.event.data.user_name }}
            unlocked via {{ trigger.event.data.source }}
```

With more than one lock, add `ieee` to `event_data`, see [Multiple locks](#multiple-locks).

The [unlock notification](../README.md#blueprints) blueprint sends "Kari unlocked via keypad" to your phone, so while you are out you can see whether it was the cleaner, the neighbour feeding the cat or one of the family.

Give each child a slot with their own code or tag and trigger on the name, for a message when one of them comes home on a weekday afternoon:

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

A code for the plumber: an automation calls `onesti_lock.set_pin` on a spare slot the morning the job starts and `onesti_lock.clear_pin` when it ends, and the events show when the plumber came and went. Setting a code can physically lock an unlocked door (see [Limitations](#limitations)), and the code ends up in the recorder and the automation trace (see [From services](#from-services)).

The activity sensor's history and the logbook list every lock and unlock with name and method, so you can look back at who came in last Tuesday.

## Languages

English, Norwegian (bokmål), Swedish and Danish. Sensor states, entity names, options flow labels and service errors follow the Home Assistant server language (Settings > System > General), not each user's frontend language. Reload the integration after upgrading or after changing the server language.

## Limitations

1. **Zigbee2MQTT is not supported.** Z2M's `onesti.ts` converter decodes the same attribute into raw slot numbers, with no named users, no readable activity messages and no PIN management UI. A comparison is in [technical.md](technical.md#comparison-with-zigbee2mqtt). If you want to stay on Z2M, stay with the converter.

2. **Sleepy device.** The lock sleeps aggressively, so commands may time out on the first attempt. The integration then wakes the lock with a **lock command** and retries. If the door is unlocked when you set or clear a PIN, it locks. If the door is standing open, the bolt is driven out into the air. Close the door before managing PIN codes, or wake the lock yourself first by turning the thumb-turn. Put a Zigbee router right next to the door as well: the metal casing works like a Faraday cage.

3. **Events may stop after a battery change.** Try "Reconfigure" in ZHA after waking the lock with a code; if that fails, remove and re-pair the lock. Details in [debugging.md](debugging.md#after-battery-change).

4. **RFID and fingerprint enrollment** only works from the keypad or the BLE app, not over Zigbee.

5. **Slot state drift.** If PINs are changed on the keypad or in another app, the slot data here falls out of sync. Use "View user slots" to check.

6. **No OTA firmware updates over Zigbee.** The module lists the OTA Upgrade cluster, but no firmware image for it exists in the community zigbee-OTA index, so ZHA has nothing to offer.

7. **ZHA internals.** ZHA has no public API for what this integration reads, so a Home Assistant update can break it. A repair issue titled "Lock events are not being received" then appears under Settings → System → Repairs. PIN codes may still work, but the activity sensor and the event go quiet. Open an issue with your Home Assistant version. When ZHA restarts with the lock, the integration reconnects by itself, and a ZHA still starting when Home Assistant boots is waited for.

8. **Dashboard locks right after a wake.** A lock from a dashboard within 30 seconds of the integration waking the lock looks the same as the wake itself, so the activity sensor does not show it. The event still fires. The 30 seconds is a chosen window, not one measured on a lock.

9. **Going back to an older version is untested.** From 1.4.0 on, HACS installs the ZIP attached to the release instead of the tag's source tree. The ZIPs on the 1.0.0 to 1.3.0 releases hold the same flat layout, so picking one in HACS should land the right files, but nobody has tried. If a downgrade leaves Home Assistant without the integration, delete `config/custom_components/onesti_lock`, install the version you want again and restart. Releases before 1.0.0 are the old `nimly_pro` integration and are no rollback target. Upgrading is not affected.

## Removing the integration

Remove each lock's entry, then the integration itself:

1. Clear any PIN codes that should stop working, with **Clear PIN code** under Configure or the `onesti_lock.clear_slot` action. The codes live on the lock, and removing the integration leaves them there, still opening the door.
2. Go to **Settings → Devices & Services → Onesti Lock**, open the ⋮ menu on each lock's entry and pick **Delete**. This removes the Onesti Lock device and its sensors, and deletes the slot names and PIN status stored in Home Assistant.
3. In HACS, open Onesti Lock, pick **Remove** from the ⋮ menu, and restart Home Assistant. With a manual install, delete `config/custom_components/onesti_lock` and restart.

ZHA's device and its lock entity are not touched, so you can still lock and unlock from Home Assistant. Imported blueprints and automations that use them stay until you delete them yourself.
