# Technical details

## How user identification works

Onesti locks send a custom attribute report (`attrid 0x0100`) on the Door Lock cluster for every lock and unlock. The value is a bitmap32 holding user slot, action and source. ZHA's stock quirk and the Zigbee2MQTT converter both decode it into raw numbers; this integration is the one that turns it into named users and readable activity. It listens for the reports with `cluster.on_event("attribute_report", ...)` (`register_event_listener()` in `events.py`) and decodes the bitmap:

```
Bits 0-15:  user_slot (uint16 LE; 0 = master or no user, see below)
Bits 16-23: action (1 = lock, 2 = unlock)
Bits 24-31: source (see SOURCE_MAP in events.py)
```

| Source byte | Meaning                                                                                           |
| ----------- | ------------------------------------------------------------------------------------------------- |
| `0x00`      | zigbee (remote command)                                                                           |
| `0x02`      | keypad (PIN code)                                                                                 |
| `0x03`      | fingerprint                                                                                       |
| `0x04`      | rfid                                                                                              |
| `0x05`      | unattributed (NimlyCodePRO fw 4.8 reports this for Zigbee, auto-relock and interior keypad alike) |
| `0x0A`      | auto (auto-relock)                                                                                |

Slot 0 means two things. With source keypad, fingerprint or rfid, a person used the master credential (capture 29.03: `0x02020000`, slot 0, unlock, keypad). The event then carries `user_slot: 0` and the name set on slot 0, or "Master" without one. With source zigbee, auto, unattributed or unknown, slot 0 means no user, and `user_slot` and `user_name` are `null`. Which other slots hold master codes depends on the model, see [slot-numbering.md](slot-numbering.md).

`SOURCE_MAP` in `events.py` is the canonical decoder, so update this table when the map changes. The raw captures behind these values are in `docs/zigbee-protocol/zigbee-captures.md`.

`attrid 0x0101` holds the PIN code in BCD plaintext. The integration leaves it alone on purpose. Every state attribute ends up in the recorder, the logbook and diagnostics, which would put real access codes on disk (see zha-device-handlers#4881), and the slot number from 0x0100 already identifies the user.

## Why standard ZHA approaches don't work

We tried 6 approaches before one worked. The lock sends the event data, but ZHA and zigpy don't expose it through the standard APIs:

| Approach                                   | Result                                                                          |
| ------------------------------------------ | ------------------------------------------------------------------------------- |
| ZHA `last_action_user` sensor              | Never updates on keypad use, stale from last HA command                         |
| `zha_event` bus events                     | `operation_event_notification` (0x0020) never received                          |
| `add_listener` + `attribute_updated`       | Suppressed by zigpy for unknown attributes (`_suppress_attribute_update_event`) |
| `add_listener` + `handle_cluster_request`  | Only for cluster commands, not general commands like Report_Attributes          |
| `add_listener` + `general_command`         | Not dispatched to listeners for Report_Attributes                               |
| **`cluster.on_event("attribute_report")`** | **Works, catches all attribute reports including custom 0x0100**                |

## Reaching the lock through ZHA

ZHA has no public API for a device's zigpy clusters, so everything that knows ZHA's object layout lives in `zha.py`. The rest of the integration talks to a lock through `ZhaLockTransport`, which is injected into the coordinator so tests can pass a fake.

### Device chain

The gateway comes from ZHA's own helper `get_zha_gateway_proxy`. It raises `ValueError` when ZHA has no running gateway (not set up yet, failed, or reloading), and `zha.py` turns that into "no gateway". The device is looked up in `gateway_proxy.device_proxies`, matching the IEEE address without regard to case, and the Door Lock cluster lives on the deepest zigpy device object:

```
ZHADeviceProxy (depth 0, no endpoints)
  → Device (depth 1, empty in_clusters)
    → CustomDeviceV2 (depth 2, clusters here)
```

`find_door_lock_cluster()` walks the `.device` chain up to four levels, skips endpoint 0, and returns the first endpoint's Door Lock cluster (0x0101). The config flow's `has_door_lock_cluster()` uses the same walk to decide which devices to offer. Commands are sent to the endpoint the cluster belongs to (`cluster.endpoint.endpoint_id`). Endpoint 11, where every Onesti lock seen so far has the cluster, is only the fallback when that id cannot be read.

### Finding ZHA's lock entity

The auto-wake calls `lock.lock` on ZHA's own lock entity, and `find_lock_entity_id()` finds it through the registries. ZHA registers each device with a zigbee connection holding the IEEE address in lowercase. The device is the one with that connection among the devices of ZHA's own config entries (`async_entries_for_config_entry`), not a registry-wide `async_get_device`: from HA 2026.9 a connection is unique only within one config entry, and HA reports `async_get_device` as breaking in 2027.8. The lock entity is the one entity on it in the `lock` domain from the `zha` platform. Disabled entities are skipped, since HA would refuse the service call. No unique_id format is parsed.

### When ZHA is reloaded

A ZHA reload or a re-pair builds new zigpy objects, and a listener left on the old cluster would stop receiving lock events without a word. `__init__.py` therefore subscribes to `ConfigEntry.async_on_state_change` on every ZHA config entry that exists at setup, and on every ZHA entry added later (it listens for `ConfigEntryChange.ADDED` on `SIGNAL_CONFIG_ENTRY_CHANGED`), so a ZHA that is removed and added again is still followed. When a ZHA entry reaches `LOADED` while this entry is loaded, the entry schedules its own reload if nothing is listened to yet (`coordinator.listened_cluster` is `None`) or if the cluster ZHA now holds is another one. That is also how the integration recovers when it was set up before ZHA had the lock.

### When ZHA starts after this integration

The ZHA entry is often still in `SETUP_RETRY` when this entry sets up, typically because the coordinator's USB stick comes up late. That is not a fault. When ZHA has no gateway and no ZHA entry is `LOADED`, setup logs one info line, skips the listener and the capability read, and leaves the rest to the ZHA watch above: once ZHA reaches `LOADED`, the reload registers the listener, or raises the repair issue if something really is missing.

### Repair issue for missing ZHA internals

The event listener depends on three things that are not public API: the gateway, the Door Lock cluster under the device, and `cluster.on_event`. If one is missing at setup while ZHA is running (a gateway exists or a ZHA entry is `LOADED`), `register_event_listener()` raises `ZhaInternalsMissing`, and `__init__.py` logs an error and creates the repair issue `zha_internals_<entry_id>` (severity error, not fixable). Its `detail` placeholder names the missing piece:

| `detail`                              | Meaning                                         |
| ------------------------------------- | ----------------------------------------------- |
| `ZHA gateway (get_zha_gateway_proxy)` | ZHA is `LOADED` but has no gateway              |
| `Door Lock cluster for <ieee>`        | ZHA runs, but the lock or its cluster is absent |
| `<ClusterClass>.on_event`             | The cluster has no `on_event`                   |

Without the listener nothing reports who unlocked, though PIN writes may still work when ZHA itself runs. The issue is deleted when the listener registers and when the entry unloads. What the user does about it is in [debugging.md](debugging.md#repair-issue-lock-events-are-not-being-received).

## Sending commands

`ZhaLockTransport.send()` calls the command on the lock's zigpy Door Lock cluster directly, `cluster.command(command_id, **params)`, on the cluster `find_door_lock_cluster()` returns. The cluster belongs to its endpoint, so the command goes out from wherever ZHA found it. This is the call ZHA's `issue_zigbee_cluster_command` service ends in (`Device.issue_cluster_command` in the zha library), and `send()` does what that method does around it:

- zigpy's default reply timeout, which ZHA does not change.
- No manufacturer code. The service only fills one in for manufacturer clusters (0xFC00 and up), and it never passes it on to the cluster call anyway.
- A `None` answer is success. An exception handed back as the answer is a failure. Otherwise the answer's `status` field decides, if it has one: anything but `SUCCESS` is a failure. The answer is either a Default Response or the command's own response, such as Set PIN Code Response, and both name the field `status`. An answer without one counts as success, as in ZHA.

Where the service raised `ZHAException` for a failure status, `send()` returns `False` with a warning naming the status. The lock answered, so it is awake, and nothing is woken.

The service is not used because Home Assistant fires a `call_service` event with the full service data for every service call, and the recorder stores those events. Through the service, every PIN the integration set, from the options flow as well, was written to the recorder database in clear text. `tests_ha/test_pin_canary.py` checks that no `call_service` event carries the code. The same bypass keeps the parameters out of the debug line ZHA's service logs for each command.

`tests_ha/test_zha_contract.py` fails when Home Assistant moves to a zha library release whose `issue_cluster_command` has not been read against `send()`. zha 0.0.59 (HA 2025.6) and 2.2.2 (HA 2026.9) have been.

Not verified on a real lock: that the direct call behaves like the service did against an Onesti lock. The frame on the air should be the same, since both end in the same zigpy call with the same arguments, but no PIN has been set this way on hardware yet. The status check is also new for HA 2025.x: the answer's status was never read there (see below), so a lock that answers a delivered PIN with a failure status now gets `False` where it used to get `True`.

### Nimly response quirk

PIN commands used to fail with `IndexError: tuple index out of range` even though the command reached the lock. The most likely source is ZHA, not the lock: zha 0.0.x, which HA 2025.6 ships, read the status as `response[1]`, and Set PIN Code Response and Clear PIN Code Response have one field, so index 1 does not exist. zha 2.x reads `response.status` instead. `send()` reads the status by name as well, so it should not see the error at all. It still catches `IndexError` and treats the command as sent, logged at debug level only, in case the lock's answer itself trips zigpy's parser.

## Coordinator pattern

`NimlyCoordinator` is a custom class, on purpose NOT based on HA's `DataUpdateCoordinator`. A polling coordinator makes no sense for a battery-powered Zigbee EndDevice that sleeps between events and cannot be polled. There is one per lock, kept on `entry.runtime_data`.

### Slot data storage

Slot data is stored in the config entry's options (`.storage`), which survives HA restarts. Keys are strings (`"0"`, `"1"`, ...) because `ConfigEntry.options` serializes to JSON. A stored slot holds `name` and `has_pin` and nothing else. Fields outside that schema are dropped on load, so a hand-edited or older save cannot bring them back.

The same options hold `reserved_slots` from the settings form and `capabilities` once the lock has reported them (see below).

The config entry is at version 2.2. `async_migrate_entry` takes a 2.1 entry to 2.2 by stripping `has_rfid` from every stored slot, a field nothing ever set. An entry written by a newer major version is refused rather than guessed at.

### PIN operations

`set_pin`, `clear_pin` and `clear_slot` refuse slots below the first user slot (`_check_writable`), whoever calls them, so slot 0 is never written from HA. They run one at a time per lock under an `asyncio.Lock`, since the options flow and the services can both write, and interleaved sends and saves could leave storage describing the older of two writes. Local state changes only after a command reached the lock: a failed `clear_slot` does not show the slot as vacant while the lock still accepts the old code.

A successful send means the lock took the frame. It does not mean the lock accepted the code, since the Onesti response cannot be parsed (see the quirk above).

In the options flow, a PIN write runs as its own task, and the progress task HA shows only waits for it through `asyncio.shield`. HA cancels the progress task when the dialog closes, and by then the command may have reached the lock, so cancelling it before the save would leave storage describing the old code. The write finishes on its own and logs its outcome, and the flow logs at info level when a dialog closes while a write is running.

### Listener pattern

The slot sensors register callbacks with `add_listener(callback)`. When slot data changes (a name set, a PIN set or cleared), the coordinator calls `_notify_listeners()`, which runs `async_write_ha_state()` in each sensor.

### Slot sensors and reloads

The slot sensor row starts at the first user slot and has `NUM_USER_SLOTS` (10) sensors, each with the unique_id `<ieee>-slot-<n>`. On setup, registry entries for slot sensors outside the current row are removed, so moving `reserved_slots` does not leave unavailable entities behind, and a slot that is in both rows keeps its entity id.

Changing `reserved_slots` reloads the entry through an update listener. The coordinator writes slot data and capabilities to the same options, and every write calls that listener, so it compares the first user slot with the one the setup was built for and reloads only when that changed.

### Activity sensor

The activity sensor registers separately, with `set_activity_sensor(sensor)`, and gets `update_activity(user_slot, action, source)` for every decoded operation event that is not a system lock (`is_system_lock()` in `events.py`):

- source `auto`, always
- source `unattributed` with action lock and no user slot, which is how NimlyCodePRO reports auto-relock
- source `zigbee` with action lock and no user slot, but only while the wake echo is pending (see [Wake echo](#wake-echo))

That keeps auto-relock and the integration's own wake from overwriting the last activity that mattered. A Zigbee lock from a dashboard outside the echo window does update the sensor, and so does a master code unlock on slot 0.

The sensor is a `RestoreEntity`. It stores the raw fields (`user_name`, `user_slot`, `action`, `source`, `timestamp`) as extra restore data, never the rendered text, and builds the state from them with the current strings, so it comes back after a restart and follows a change of server language. Restored data is filtered to those five keys, and data without a string `action` and `source` is dropped. `timestamp` is ISO 8601 in UTC (`dt_util.utcnow()`).

### Lock capabilities

The coordinator reads the standard ZCL DoorLock attributes 0x0012 (NumberOfPINUsersSupported), 0x0017 (MaxPINCodeLength) and 0x0018 (MinPINCodeLength) until the lock has answered once:

- at setup
- after every command that reached the lock
- on every attribute report from the lock, whatever the attribute

The last two are the moments the radio is known to be awake. Each read runs as a background task tied to the entry, so an unload cancels a read still waiting on a sleeping lock. `read_capabilities()` returns `None` when the lock was not reached, and the read is then repeated at the next chance. Any answer is final, also one without these attributes, since some variants skip them. The answer is stored in `entry.options["capabilities"]` and loaded from there at the next setup, and the lock is never asked again. zigpy may key the answer by attribute id or by name, and both are mapped.

What the capabilities decide is in `pin_rules.py`:

- `set_pin` rejects slots at or above NumberOfPINUsersSupported (`max_user_slot`, highest slot N-1). A missing count, or one outside 4-1000, gives the manual's ceiling of 999. NimlyPRO and NimlyCodePRO both report 50.
- A PIN code is ASCII digits within the reported min and max length (`pin_length_range`). Each bound is trusted only between 4 and 20, and falls back on its own to 4-8. If the two bounds left over contradict each other, 4-8 applies.

The floor of 4 is there for the log masking below: a lock that reports a minimum of 3 still gets 4.

### Runtime strings

Sensor states and options-flow labels are built in Python and never pass through HA's translation layer. `localize.py` looks them up in the `runtime` section of `translations/<lang>.json` for the server language (`hass.config.language`). English, Norwegian bokmål, Swedish and Danish ship with the integration. `no` and `nn` map to `nb`, and missing keys fall back to English. The coordinator loads them at setup.

## Auto-wake mechanism

Battery-powered Zigbee EndDevices sleep most of the time, and ZCL commands like `set_pin_code` fail while the radio is asleep. `ZhaLockTransport.send()` in `zha.py` wakes the lock and retries:

1. The first attempt sends the ZCL command to the zigpy cluster (see Sending commands).
2. On `TimeoutError` or zigpy's `DeliveryError`, it calls `wake()` and retries the command once.
3. `wake()` sends a `lock.lock` service call to ZHA's lock entity, then waits 1 second for the radio to settle.
4. The command is sent again. A second failure returns `False`.

`DeliveryError` is included because a sleeping lock can plausibly surface as a failed delivery and not only as a timeout. Which of the two a real Onesti lock produces has not been checked. Any other `ZigbeeException` has nothing to do with sleep, so it returns `False` at once without moving the bolt. Any other exception is logged as an error and returns `False` as well: `send()` never raises.

`wake()` must not stop the retry. If no ZHA lock entity is found it logs a warning and skips the wake, and if the service call fails the retry runs anyway.

`lock.lock` is used because it works, while attribute reads through the integration's own cluster path time out. Why it works is not established. ZHA's lock entity wraps the command in longer timeouts and retries for sleepy devices, which is the likely reason, but at the radio level a read and a write are queued the same way.

The wake has a side effect, since it is a real lock command and not a read. An unlocked door gets physically locked, and an open door drives the bolt out into the air. The README limitations and the options flow texts both say so. A wake that does not move the bolt is not solved yet, and replacing the mechanism needs testing on real hardware first.

Nothing sent over the air wakes a sleeping EndDevice, since its radio is off. All the coordinator can do is queue a unicast at the parent router and hope the lock polls within the 7.68-second window; once one frame gets through, the lock fast-polls and drains the rest, which is what looks like waking. At that level a `read_attributes` is queued exactly like a lock command, so if `lock.lock` works better than a plain read (`read_capabilities` usually goes unanswered against a sleeping lock), the difference is the retry and extended-timeout envelope ZHA gives its lock entity, not the fact that it writes. That is why `homeassistant.update_entity` on the ZHA lock entity, which goes through the same entity path, is the candidate for a bolt-free wake, with "only wake when the cached state is already locked" as the fallback.

### Wake echo

The lock reports the wake's `lock.lock` as an ordinary Zigbee lock (source `zigbee`, no user slot), which would replace the last activity every time a PIN is set on a sleeping lock. `wake()` stamps the time just before the service call, because the report can arrive while the call is still waiting, and `wake_echo_pending()` is true for `WAKE_ECHO_WINDOW_S` (30 seconds, `const.py`) after that. If the service call fails, the stamp goes back to what it was before, so a failed wake opens no window. Asking does not reset it, since the lock may report the wake more than once. Inside the window, a Zigbee lock without a user slot counts as a system lock: the event still fires, and the activity sensor stays as it was.

The 30 seconds are a generous guess. How long the report can trail the command on a real lock has not been measured.

The trade-off is deliberate. A real lock from a dashboard within 30 seconds of the integration's own wake looks exactly like the echo (source `zigbee`, action lock, no user slot), so it is taken for the echo and the activity sensor does not change. The `onesti_lock_activity` event still fires for it. Unlocks, locks with a user slot, and anything from the keypad, fingerprint or RFID are never affected.

## Logging and PIN codes

Parameters for `set_pin_code` hold the PIN, and exception messages on the send path are not ours to shape: an error from building the frame may quote the params, and a zigpy error may echo the frame. `send()` therefore never logs a traceback, and every exception message goes through `redact_digits()` in `redact.py` first. It replaces every run of four or more digits with a fixed `****`, so the mask does not reveal the code's length either. Shorter runs stay readable, since command ids, slot numbers and ZCL status codes are what make an error message useful.

The mask covers every PIN the integration accepts only because `pin_rules` never accepts a code shorter than 4 (`PIN_LENGTH_SANE_MIN`, which `redact.py` imports). Lowering one without the other puts codes in the log.

This covers the integration's own log lines. ZHA and zigpy log on their own terms, see [debugging.md](debugging.md#pin-codes-appear-in-raw-logs-and-diagnostics).

## `onesti_lock_activity` event

Every operation event decoded from attrid `0x0100` fires `onesti_lock_activity`, auto-lock and the wake echo included, so automations see everything the activity sensor leaves out. The payload:

| Key         | Value                                                                               |
| ----------- | ----------------------------------------------------------------------------------- |
| `ieee`      | The lock's IEEE address as stored in the config entry                               |
| `user_slot` | Slot number, `0` for the master credential, `null` when no user was involved        |
| `user_name` | Name for `user_slot`, `null` exactly when `user_slot` is `null`                     |
| `action`    | `lock`, `unlock` or `unknown`                                                       |
| `source`    | `zigbee`, `keypad`, `fingerprint`, `rfid`, `unattributed`, `auto` or `unknown`      |

`user_slot` is `null` for slot 0 from a source that is not keypad, fingerprint or rfid (see [How user identification works](#how-user-identification-works)). Otherwise it is the slot the lock reported.

`user_name` is never `null` for a known slot. It is the name set on the slot, and without one it falls back to "Master" for slot 0 and "Slot N" for any other slot, in the server language as loaded at setup. A template can therefore not tell an unnamed slot from a named one by testing `user_name`. Test `user_slot` against `null` to know whether a user was involved.

The activity sensor carries the same `user_slot`, `user_name`, `action` and `source` as attributes, plus `timestamp`, and the capabilities once reported.

### Automation example

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

With more than one lock, add `ieee` to `event_data` to pick one.

## Sleepy device behavior

The Connect Module ZMNC010 is a battery-powered Zigbee EndDevice, and the radio sleeps between events to save battery. What wakes the radio, the 7.68-second message TTL at the parent router, and recovery after a battery change are covered in [docs/debugging.md](debugging.md#1-zigbee-connectivity) section 1.

## Community references

- [Z2M PR #11332: PIN code parsing and user tracking](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332)
- [Z2M issue #17205: Not fully supported](https://github.com/Koenkk/zigbee2mqtt/issues/17205)
- [Z2M issue #5884: Original device support](https://github.com/Koenkk/zigbee2mqtt/issues/5884)
- [ZHA issue #3095: Device support request](https://github.com/zigpy/zha-device-handlers/issues/3095)
- [HA community: Nimly lock thread (12+ pages)](https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634)
- [Blakadder: ZMNC010](https://zigbee.blakadder.com/Nimly_ZMNC010.html)

## ZMNC010 Connect Module

The Zigbee radio module inside all Onesti/Nimly locks, also sold separately as an accessory.

| Property              | Value                                                                  |
| --------------------- | ---------------------------------------------------------------------- |
| Manufacturer code     | `0x1234` (4660), a placeholder not registered with the Zigbee Alliance |
| Max buffer size       | 108                                                                    |
| Max incoming transfer | 127                                                                    |
| Max outgoing transfer | 127                                                                    |
| Logical type          | EndDevice (battery-powered)                                            |
| Frequency             | 2.4 GHz (Zigbee 3.0)                                                   |
| Certifications        | CE-marked, no FCC ID found (European product)                          |

The unregistered manufacturer code (`0x1234`) points to an OEM module rather than a custom Zigbee implementation. The small buffer and transfer sizes fit a lower-end chip, likely a TI CC2530 or similar.

## Alternatives considered

| Integration                                                               | Why not                                                                                           |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| [Keymaster](https://github.com/FutureTense/keymaster)                     | Z-Wave only, no Zigbee support                                                                    |
| [Lock Code Manager](https://github.com/raman325/lock_code_manager)        | Requires `supported_features` on lock entity. ZHA reports `supported_features: 0` for these locks |
| [Zigbee Lock Manager](https://github.com/Fiercefish1/Zigbee-Lock-Manager) | Dormant (no commits since January 2025). No config flow, doesn't handle Onesti response quirk     |

## Comparison with Zigbee2MQTT

Z2M has an `onesti.ts` converter for these locks, and this integration decodes the same Onesti attributes. Where they differ:

| Feature                                           | This integration (ZHA)                                  | Z2M `onesti.ts`                                   |
| ------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------- |
| Decode attrid 0x0100 (user/source/action)         | Yes                                                     | Yes                                               |
| Last used PIN code (attrid 0x0101)                | No, removed on purpose (0x0101 is the PIN in plaintext) | Yes, `last_used_pin_code` state                   |
| Lock capabilities (max users, min/max PIN length) | Yes, read until the lock answers once                   | Exposed, never populated (see upstream-status.md) |
| Set / clear PIN codes                             | Yes, via HA UI and services                             | Yes, via MQTT                                     |
| Name any slot (for RFID/fingerprint)              | Yes, persisted in HA                                    | No                                                |
| Activity sensor with human-readable messages      | Yes                                                     | No, raw fields only                               |
| HA events for automations                         | Yes, `onesti_lock_activity`                             | Via MQTT events                                   |
| Auto-wake for sleepy device                       | Yes, send lock command before retry                     | No                                                |
| Blueprints included                               | Yes (connectivity, goodnight, notifications)            | No                                                |
| Protocol                                          | ZHA only                                                | Zigbee2MQTT only                                  |
