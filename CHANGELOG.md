# Changelog

All notable changes to Onesti Lock. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Features

- **Lock number two is found on its own.** Once one lock is set up, pairing another Onesti lock with ZHA makes it turn up under Discovered on the integrations page, with its model and IEEE address, and you confirm or ignore it there. The first lock still has to be added with Add Integration: Home Assistant does not load a custom integration that has no config entry. <!--short-->
- **The lock's device says which lock it is.** It is named after the model and the last four characters of its Zigbee address, so two locks of the same model are no longer two entries called Onesti Lock, and it carries the model and the address as its serial number. On Home Assistant 2026.9 and newer it is shown under ZHA's device for the same lock; on older releases the two become one device with the lock entity and these sensors on it. Existing entity IDs and names are kept. <!--short-->
- **A replaced Connect Module keeps the lock's setup.** The module is an accessory with its own Zigbee address, and swapping it used to mean setting the lock up again from scratch. Use Reconfigure on the entry and pick the new module: the slot names, the PIN status and every sensor stay as they are. <!--short-->
- **All 54 rules in Home Assistant's Integration Quality Scale are met.** `quality_scale.yaml` states each one and the manifest declares platinum. The declaration is our own: Home Assistant gives custom integrations no level, and see the README for what that means.
- **The sensors say when they are not being updated.** While ZHA is not running, no lock event can reach Home Assistant, and the slot and activity sensors show as unavailable until it is back. A lock that is only asleep is not unavailable: the sensors keep what they have. The log gets one line when events stop and one when they are back, in place of the line that only ever said they had started. <!--short-->

### Security

### Bug fixes

### Breaking changes

- **The lock's PIN capacity and code length moved off the activity sensor.** `num_pin_users`, `min_pin_length` and `max_pin_length` are no longer attributes there. They are three sensors of their own, switched off when the integration is set up: turn them on under the device if you need them. An automation or template reading the old attributes has to point at the sensors instead. <!--short-->

## [1.4.0] - 2026-09-19

### Action required

- **Import the blueprints again if you use them.** HACS does not update imported blueprints, and copies from 1.3.0 and earlier ignore some of their settings (see Bug fixes). Import and overwrite them from [the Blueprints section](README.md#blueprints) of the README. The new copies are in English, the notification texts included. Blueprints have no translation mechanism in Home Assistant, so the Norwegian texts are gone; edit your automation's message if you want them back.

### Features

- **Reserved slots are a setting.** How many slots from 0 up hold master codes differs per model: Touch Pro, PRO and Code reserve 000-002, Code Pro only 000. Set it per lock under Configure, Settings (1 to 3, default 3). Set PIN, Clear PIN and the services stay off the reserved slots, and the slot sensors start at the first user slot. (#6) <!--short-->
- **Every slot can be named**, master slots 0-2 included, so the activity sensor can say who used the master code. View user slots now lists the master rows too. (#6) <!--short-->
- **You are told when the lock refuses a code.** If the lock answers that it refused a PIN, Set PIN and `set_pin` fail with an error that says so, and says why when the lock gives a reason: another slot already uses the code, or the code memory is full. Before, a refusal was reported as the lock being unreachable, or not at all. Which answers Nimly locks send has not been checked on a real lock, so still try a new code on the keypad. <!--short-->
- **Pick the lock by device in services.** `set_pin`, `clear_pin`, `set_name` and `clear_slot` take a `device_id` with a device picker in the automation editor. `ieee` still works and now ignores case.
- **Repair issue when lock events cannot be received.** If a part of ZHA the integration depends on is missing, Settings, Repairs says so and names it. Before, activity just stopped arriving. A lock that is gone from ZHA, removed or moved to a new Connect Module, is not treated as an error: setup waits and retries until the lock is back. A ZHA that is still starting, for example with a slow Zigbee stick, is waited for the same way. <!--short-->
- **PIN length follows the lock.** Set PIN and `set_pin` check the code against the minimum and maximum length the lock reports, with 4-8 digits until it has reported.
- **Download diagnostics.** The integration page has a diagnostics download you can attach to a bug report. No PIN code is in it, and neither is the IEEE address: each slot is listed as named or unnamed, with whether it holds a code, next to the slot and length limits the lock reports.
- **The integration has an icon of its own.** Newer Home Assistant versions show it on the integration page and in the device list, in place of the default puzzle piece.

### Security

- **Setting a PIN from the UI no longer puts the code in the recorder database.** Every PIN command went through ZHA's `issue_zigbee_cluster_command` action, and Home Assistant records each action call with its data, so every code set since 1.0.0 was stored in clear text. Commands now go straight to the lock's Door Lock cluster. Calling the `onesti_lock.set_pin` action still records the code you passed it, because Home Assistant records that call too, and so does the trace of the automation or script that made it (see [Security](README.md#security)). Events already stored are removed when the recorder purges them, after 10 days unless you changed `purge_keep_days`. <!--short-->
- **Errors no longer put PIN codes in the log.** A failed PIN command could log the error from ZHA, which quotes the command, code included, and a failed service call passed that error on to the caller. Digit runs of four or more are now masked in everything the integration logs about a command, and services raise their own error instead. <!--short-->

### Bug fixes

- **Lock activity now works on Home Assistant 2025.6 through 2026.1.** On those releases the Zigbee library has no `on_event` hook, so the integration raised a repair issue at startup and no lock or unlock ever reached the activity sensor or the `onesti_lock_activity` event. It now listens through the older hook those releases do have, and the repair issue is left for a library with neither. Setting and clearing PIN codes was never affected. <!--short-->
- **Set PIN and Clear PIN in the UI no longer spin forever.** The dialog stayed on the progress spinner after the command finished, in every version since 1.0.1. It now moves on to a result, or back to the form with the error. <!--short-->
- **Closing the Set PIN dialog early no longer loses the change.** A code that had already reached the lock is now saved even if the dialog was closed while it waited.
- **Clear PIN code keeps the slot's name** and only lists slots that have a PIN. Use the `clear_slot` service to remove the name as well.
- **The master code shows up by name.** Unlocking with the master code showed "Unknown". It now shows the name you gave slot 0, or "Master". (#6) <!--short-->
- **Locks reporting an unexpected model string can be added.** A Connect Module can report a sibling model, such as a Code Pro that pairs as NimlyTwist, and setup said no devices were found. Any Onesti lock with a Door Lock cluster is now offered. (#5)
- **The last activity survives a restart.** The activity sensor was empty after every Home Assistant restart until the next lock event. Its `timestamp` attribute is now UTC with an offset instead of local time without one.
- **Setting a PIN no longer overwrites the last activity.** Waking a sleeping lock before a PIN write locks the door through ZHA, and the activity sensor showed that as "Locked via Zigbee". Locking from a dashboard still shows up.
- **Blueprints use their settings.** "Notify on unlock" ignored "only unlock" and the notify service you picked, and "connectivity alerts" ignored the number of minutes. Import them again to get the fix. <!--short-->
- **Lock events keep arriving after ZHA reloads.** A ZHA reload or re-pair left the integration listening to the old device, and activity stopped without a warning. It now reloads onto the new one.
- **Commands to a sleeping lock retry in more cases.** A failed delivery now wakes the lock and retries, like a timeout already did. Other Zigbee errors fail at once without moving the bolt.
- **The lock's slot and PIN limits are actually read.** They were only read at startup, when the lock is usually asleep. The read now repeats while the lock is awake until it answers, and the answer is kept.
- **A mistake in a service call is no longer logged as an error.** A slot out of range, a PIN of the wrong length or a lock that is not set up fails with a message where the call was made, without a traceback in the log. Errors from the lock itself still reach the log.

### Breaking changes

- **Home Assistant 2025.6 is the minimum.** HACS keeps older installations on 1.3.0. <!--short-->
- **`onesti_lock_activity` reports `user_slot: 0` for the master code.** Unlocking with the master code by keypad, fingerprint or RFID used to give `user_slot: none`, the same as auto-lock and remote locking. Those still give `none`. An automation that used `is none` to skip system events now also runs for the master code. To keep skipping it, change <!--short-->

  ```yaml
  condition: "{{ trigger.event.data.user_slot is not none }}"
  ```

  to

  ```yaml
  condition: "{{ trigger.event.data.user_slot not in [none, 0] }}"
  ```

- **Services need `device_id` or `ieee` when more than one lock is set up.** Without either, the call used to go to whichever lock came first. It is now refused, and the error lists the locks. <!--short-->
- **PIN codes shorter than 4 digits are refused**, whatever the lock reports.
- **Slot sensors follow the reserved-slots setting.** With the default of 3 nothing changes. With a lower setting the row moves down, for example to slots 1-10, and the sensors for slots that fall out of it are removed.
- **The `has_rfid` attribute on slot sensors is gone.** It was always false: no Zigbee report says whether a slot holds a card.

## [1.3.0] - 2026-08-23

### Action required

- **Reload the integration after upgrading.**

### Features

- **Four languages**: English, Norwegian, Swedish and Danish. Sensor states, entity names, options-flow labels and error messages follow the Home Assistant server language. Previously all of it was hard-coded Norwegian and the language setting had no effect. Adding a language is now one file: copy `translations/en.json`, translate, open a PR. (#5)

### Security

- **`last_pin_code` is removed.** Attribute 0x0101 is the PIN itself in plaintext, not an opaque credential id, and the activity sensor published it as a state attribute. Versions 1.1.0 through 1.2.0 wrote real door codes into the recorder, the logbook and any diagnostics dump. To clear codes already in your history, call `recorder.purge_entities` on the activity sensor. Identified by @supersej in zigpy/zha-device-handlers#4881.

### Bug fixes

- **Slot changes were not saved.** Only the first change after a restart reached disk; names and PIN status set after that were lost on the next restart. The integration handed Home Assistant the same dictionary it kept modifying, so HA saw no change and never wrote to storage.
- **A failed PIN removal showed the slot as empty.** Local state was cleared even when the command never reached the lock, so a code you thought you had deleted was still accepted by the door.
- **Nimly Code Pro reports source `0x05`** for Zigbee commands, auto-relock and the interior keypad alike, always with user 0. It decodes as `unattributed` instead of `unknown`, and auto-relock no longer overwrites who actually opened the door. Reported by @CrallH. (#5)
- **User slots above 255 were misattributed.** The slot is 16 bits wide; slot 300 used to decode as slot 44.
- **`set_pin` refuses slots the lock cannot hold.** Both lock models report 50 PIN users, and higher slots were most likely rejected by the lock while the interface reported success. Clearing and renaming stay permissive, so an existing slot can still be cleaned up.

### Breaking changes

- The `last_pin_code` state attribute is gone.
- Activity and slot sensor state texts changed, including on Norwegian installations. Automations matching on the text need updating. Prefer triggering on the `onesti_lock_activity` event, whose `action` and `source` fields stay in English.
- On Nimly Code Pro, locking remotely no longer updates the activity sensor. The lock sends an identical payload for remote locking and auto-relock, so the two cannot be told apart. The event still fires for both.
- `onesti_lock.set_pin` rejects slots above what the lock reports it can hold.

## [1.2.0] - 2026-06-27

### Features

- **Nimly Code Pro support**: adds the `NimlyCodePRO` Zigbee model id to the supported list. The Code Pro is the same Onesti hardware and firmware family as the Touch Pro, verified against a real device interview (manufacturer `Onesti Products AS`, DoorLock attributes `0x0100`/`0x0101`, 50 PIN user slots), just with physical buttons instead of a touch surface. Owners of the newer Connect module that reports as `NimlyCodePRO` can now add the lock. Previously the config flow returned "no devices found". (#4)

### Bug fixes

- Silenced ruff `SIM114` and `UP041` warnings so CI passes on the current ruff release.

### Documentation

- Added a troubleshooting section for re-pairing the lock after a Zigbee network change.
- Tidied release-notes formatting and fixed a few docstring references.

## [1.1.1] - 2026-04-24

### Bug fixes

- **PIN length min/max swapped**: v1.1.0 reported `min_pin_length=8, max_pin_length=4` because the ZCL attribute IDs `0x0017` and `0x0018` were mapped to the wrong names. Per zigpy: `0x0017` is MaxPINCodeLength, `0x0018` is MinPINCodeLength. Verified live against a NimlyPRO (50 users, min 4, max 8 digits).
- Renames `max_pin_users` to `num_pin_users` on the activity sensor to match what attribute 0x0012 actually represents (number of PIN user slots supported).

## [1.1.0] - 2026-04-24

### Features

- **`last_pin_code` on the activity sensor**: decodes attribute 0x0101 from the DoorLock cluster to show the actual PIN digits typed at the keypad. Supports both BCD (packed nibbles, seen on NimlyPRO) and ASCII (seen in Z2M PR #11332) encoding, auto-detected per message. Master codes are not leaked by the lock.
- **Lock capabilities**: reads standard ZCL attributes at setup and exposes `num_pin_users`, `min_pin_length`, `max_pin_length` as attributes on the activity sensor. The read runs in the background so a sleepy lock does not block setup.

### Known issue

- v1.1.0 swapped `min_pin_length` and `max_pin_length`. **Upgrade to v1.1.1** for the fix.

### Privacy note

- `last_pin_code` contains the actual digits used. HA's recorder persists sensor attributes, see the README for an example exclude block.

## [1.0.2] - 2026-04-07

### Bug fixes

- **Setup without ZHA explains itself.** With ZHA not configured, or the lock paired through Zigbee2MQTT, the config flow crashed. It now says that ZHA is required, and the README says so too.
- **The options flow** uses `self.config_entry` the way current Home Assistant expects.

## [1.0.1] - 2026-04-01

### Bug fixes

- **Config flow 500 error on HA 2025.1+**: `FlowResult` was removed from `homeassistant.data_entry_flow` in HA 2025.1, causing `ImportError` on config flow load. Replaced with `ConfigFlowResult` from `homeassistant.config_entries`.
- **KeyError when setting PIN on unused slots**: `set_pin`, `clear_pin`, and `set_slot_name` crashed if the slot didn't already exist in stored data. Now uses `setdefault` to create the slot on first use.

## [1.0.0] - 2026-03-30

A rewrite of the integration, now for every Onesti lock and not only the Nimly Touch Pro.

### Features

- **Activity sensor** that tells who locked or unlocked the door and how: keypad, fingerprint, RFID, Zigbee or auto-lock. Auto-lock does not overwrite the last person who used the door.
- **Slot sensors** with a name per user slot.
- **PIN management** from the options flow and from the `set_pin` and `clear_pin` services, with a progress spinner while the lock is reached.
- **Sleeping locks are woken.** A PIN command that times out wakes the lock and is retried once.
- **Norwegian translation.**

### Breaking changes

- **The domain is now `onesti_lock`** instead of `nimly_pro`.
- **User slots start at 3.** Slots 0-2 hold the master codes.

## [0.2.3] - 2026-01-22

### Changes

- Code cleanup, no functional changes.

## [0.2.2] - 2026-01-20

### Bug fixes

- Fix ZHA device access for Home Assistant 2024.x+
- Fix device detection for newer Home Assistant versions

## [0.2.0] - 2026-01-20

### Bug fixes

- Fix config flow import errors that caused "Invalid handler specified" error
- Fix ZHA gateway detection for newer Home Assistant versions
- Fix Zigbee cluster IDs (use integers instead of strings)

### Features

- Add strings.json for config flow UI translations
