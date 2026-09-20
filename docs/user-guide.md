# User guide

What the integration gives you once a lock is set up, and how to use it. Installing and setting up are in the [README](../README.md), and so is the PIN management menu under Configure ([Managing access](../README.md#managing-access)).

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

A lock the integration reads as system-initiated does not change the sensor, so "Kari unlocked with code" stays visible after the door relocks. Locking from a dashboard does change it, to "Locked via Zigbee". The lock command the integration sends to wake a sleeping lock (see [Limitations](#limitations)) does not: a Zigbee lock within 30 seconds of a wake is taken to be that command. NimlyCodePRO reports Zigbee commands, auto-relock and the interior keypad with the same source code, so there `source` is `unattributed` and the sensor reads plain "Locked" or "Unlocked". An unattributed lock with no user is treated as auto-relock.

All of that rests on the source byte the lock sends, and the reading of `auto` is not settled. It is taken to mean the lock relocking itself, but in one NimlyPRO session every Zigbee command came back with that source as well, so on some firmware it may mean no more than "no user to attribute this to" ([upstream status](upstream-status.md)).

Every decoded event also fires `onesti_lock_activity`, auto-lock included, see [the event](#the-onesti_lock_activity-event).

Entity IDs come from the server language when the entity is created, so a lock set up on a Norwegian server gets `sensor.*_siste_aktivitet` and keeps it.

## Data updates

The integration never polls. When someone locks or unlocks the door, whether at the keypad, with a tag or finger, from a dashboard or by auto-lock, the lock sends a report on its own. ZHA receives it and the integration decodes it, so the activity sensor and the event change as soon as the report arrives. Nothing is sent to the lock on a timer, which would drain a battery lock that sleeps between uses.

The lock wakes up when it is used, so sleep does not delay events. It does get in the way of commands, since Home Assistant can only reach the lock while its radio is awake. A PIN change may therefore need the wake-up described under [Limitations](#limitations).

The PIN capacity and allowed code length are read from the lock once, the first time it is awake after setup, and kept after that. The slot sensors show what Home Assistant has sent to the lock and had accepted, and the lock is never asked what it holds, so a code changed on the keypad does not show up here. What the lock reports back on a PIN write has not been checked on real hardware either, so a slot shown as set is worth trying on the keypad. The lock state and the battery level come from ZHA's own entities, which ZHA keeps up to date on its own terms.

## Managing access

The menu under **Settings → Devices & Services → Onesti Lock → Configure** is described in the [README](../README.md#managing-access). It covers the ten slots from the first user slot; everything else goes through the actions below.

The first user slot is the Settings value in that menu, 3 by default. Which slots are master on which model, and where the manuals put fingerprints and key tags, is in [slot-numbering.md](slot-numbering.md).

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

The first user slot is the Settings value, 3 by default. N is the number of PIN users the lock reports. A NimlyPRO reports 50, and a NimlyCodePRO interview posted upstream shows the same, so the highest slot `set_pin` takes there is 49, and until the lock has reported, the ceiling is 999. `clear_pin` and `clear_slot` go to 999 so a slot filled before the limit was known can still be emptied.

A mistake in the call itself, a slot out of range, a PIN of the wrong length or a lock that is not set up, fails as a validation error: the message appears where the call was made and nothing is logged as an error. When the call was fine but the lock was unreachable or refused the write, the service fails with the lock's answer instead, and that one does reach the log.

The lock usually sleeps when Home Assistant starts, so the integration also asks for the PIN capacity and length after each command that reached the lock and whenever the lock reports something, until it has answered once. The answer is kept, also across restarts.

Calling `set_pin` as an action puts the code in the recorder database and in the trace of the automation or script that made the call. The options flow does not; see [PIN codes in logs, diagnostics and the recorder](debugging.md#pin-codes-appear-in-raw-logs-and-diagnostics).

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

## The `onesti_lock_activity` event

Every operation event decoded from attrid `0x0100` fires `onesti_lock_activity`, auto-lock and the wake echo included, so automations see everything the activity sensor leaves out. The payload:

| Key         | Value                                                                               |
| ----------- | ----------------------------------------------------------------------------------- |
| `ieee`      | The lock's IEEE address as stored in the config entry                               |
| `user_slot` | Slot number, `0` for the master credential, `null` when no user was involved        |
| `user_name` | Name for `user_slot`, `null` exactly when `user_slot` is `null`                     |
| `action`    | `lock`, `unlock` or `unknown`                                                       |
| `source`    | `zigbee`, `keypad`, `fingerprint`, `rfid`, `unattributed`, `auto` or `unknown`      |

`user_slot` is `null` for slot 0 from a source that is not keypad, fingerprint or rfid (see [How user identification works](technical.md#how-user-identification-works)). Otherwise it is the slot the lock reported.

`user_name` is never `null` for a known slot. It is the name set on the slot, and without one it falls back to "Master" for slot 0 and "Slot N" for any other slot, in the server language as loaded at setup. A template can therefore not tell an unnamed slot from a named one by testing `user_name`. Test `user_slot` against `null` to know whether a user was involved.

The activity sensor carries the same `user_slot`, `user_name`, `action` and `source` as [attributes](#entities), plus `timestamp`.

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

With more than one lock, add `ieee` to `event_data` to pick one, see [Multiple locks](#multiple-locks).

- **Know who came in.** The [unlock notification](../README.md#blueprints) blueprint sends "Kari unlocked via keypad" to your phone, so while you are out you can see whether it was the cleaner, the neighbour feeding the cat or one of the family.
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

- **A code for the plumber.** An automation calls `onesti_lock.set_pin` on a spare slot the morning the job starts and `onesti_lock.clear_pin` when it ends, so the code only works on those days. The events then show when the plumber came and went. Setting a code can physically lock an unlocked door (see [Limitations](#limitations)), and the code ends up in the recorder and the automation trace (see [From services](#from-services)).
- **Who opened the door, and when.** The activity sensor's history and the logbook list every lock and unlock with the name and the method, so you can look back at who came in last Tuesday.

## Languages

English, Norwegian (bokmål), Swedish and Danish. Sensor states, entity names, options flow labels and service errors follow the Home Assistant server language (Settings > System > General), not each user's frontend language. Reload the integration after upgrading or after changing the server language.

## Limitations

1. **Zigbee2MQTT is not supported.** Z2M's `onesti.ts` converter decodes the same attribute and gives you raw slot numbers, but no named users, no readable activity messages and no PIN management UI. A comparison is in [technical.md](technical.md#comparison-with-zigbee2mqtt). If you want to stay on Z2M, stay with the converter.

2. **Sleepy device**: the lock sleeps aggressively, so commands may time out on the first attempt. The integration then wakes the lock and retries, and it wakes it by sending a **lock command**.

   If the door is unlocked when you set or clear a PIN, it will physically lock. If the door is standing open, the bolt is driven out into the air. Close the door before managing PIN codes, or wake the lock yourself first by turning the thumb-turn.

   Place a Zigbee router right next to the door as well, since the metal casing works like a Faraday cage.

3. **Attribute reporting after a battery change**: the lock may stop sending activity events after new batteries. Try "Reconfigure" in ZHA, after waking the lock by entering a code. If that fails, remove and re-pair the lock. Details in [debugging.md](debugging.md#after-battery-change).

4. **RFID and fingerprint enrollment** only works from the physical keypad or the BLE app, not over Zigbee.

5. **Slot state drift**: if PINs are changed on the keypad or in another app, the integration's slot data can fall out of sync. Use "View user slots" to check.

6. **No OTA firmware updates over Zigbee**: the module lists the OTA Upgrade cluster, but no firmware image for it exists in the community zigbee-OTA index, so ZHA has nothing to offer.

7. **ZHA internals**: ZHA has no public API for what this integration reads, so a Home Assistant update can break it. If that happens, a repair issue titled "Lock events are not being received" appears under Settings → System → Repairs. PIN codes may still work, but the activity sensor and the event go quiet. Open an issue with your Home Assistant version. When ZHA restarts with the lock, the integration reconnects by itself, and a ZHA that is still starting when Home Assistant boots is simply waited for.

8. **Dashboard locks right after a wake**: a lock from a dashboard within 30 seconds of the integration waking the lock looks the same as the wake itself, so the activity sensor does not show it. The `onesti_lock_activity` event still fires. The 30 seconds is a chosen window, not one measured on a lock.

9. **Going back to an older version is untested.** From 1.4.0 on, HACS installs the ZIP attached to the release instead of the tag's source tree. The ZIPs on the 1.0.0 to 1.3.0 releases hold the same flat layout, so picking one of them in HACS should land the right files, but nobody has tried it. If a downgrade leaves Home Assistant without the integration, delete `config/custom_components/onesti_lock`, install the version you want again and restart. Releases before 1.0.0 are the old `nimly_pro` integration and are not a rollback target at all. Upgrading is not affected.

## Removing the integration

Remove each lock's entry, then the integration itself:

1. Clear any PIN codes that should stop working, with **Clear PIN code** under Configure or the `onesti_lock.clear_slot` action. The codes live on the lock, and removing the integration leaves them there, still opening the door.
2. Go to **Settings → Devices & Services → Onesti Lock**, open the ⋮ menu on each lock's entry and pick **Delete**. This removes the Onesti Lock device and its sensors, and deletes the slot names and PIN status stored in Home Assistant.
3. In HACS, open Onesti Lock, pick **Remove** from the ⋮ menu, and restart Home Assistant. With a manual install, delete `config/custom_components/onesti_lock` and restart.

ZHA's device and its lock entity are not touched, so you can still lock and unlock from Home Assistant. Imported blueprints and automations that use them stay behind until you delete them yourself.
