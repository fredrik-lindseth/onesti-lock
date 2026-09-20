# Technical details

## How user identification works

Onesti locks send a custom attribute report (`attrid 0x0100`) on the Door Lock cluster for every lock and unlock. The value is a bitmap32 holding user slot, action and source. ZHA's stock quirk and the Zigbee2MQTT converter decode it into raw numbers; this integration turns it into named users and readable activity. `register_event_listener()` in `events.py` listens on the zigpy Door Lock cluster (which hook, see [Listening for reports](#listening-for-reports)) and decodes:

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

Slot 0 means two things. With source keypad, fingerprint or rfid, a person used the master credential (capture 29.03: `0x02020000`, slot 0, unlock, keypad); the event carries `user_slot: 0` and the name set on slot 0, or "Master". With source zigbee, auto, unattributed or unknown, slot 0 means no user, and `user_slot` and `user_name` are `null`. Which other slots hold master codes depends on the model, see [slot-numbering.md](slot-numbering.md).

`SOURCE_MAP` in `events.py` is the canonical decoder, so update this table when the map changes. The raw captures behind the values are in [zigbee-captures.md](zigbee-protocol/zigbee-captures.md).

`attrid 0x0101` holds the PIN code in BCD plaintext. The integration leaves it alone: every state attribute ends up in the recorder, the logbook and diagnostics, which would put real access codes on disk (see zha-device-handlers#4881), and the slot number from 0x0100 already identifies the user.

## Listening for reports

ZHA and zigpy expose the reports through nothing public, so `register_event_listener()` hangs off zigpy's own cluster object. Which hook it uses depends on the zigpy version, because `Cluster.on_event` only exists from zigpy 0.91.0, where `Cluster` started inheriting `EventBase`. Home Assistant pins zigpy through zha:

| Home Assistant | zigpy  | Hook used      |
| -------------- | ------ | -------------- |
| 2025.6         | 0.80.1 | `add_listener` |
| 2025.8         | 0.82.2 | `add_listener` |
| 2026.1         | 0.90.0 | `add_listener` |
| 2026.2         | 0.91.5 | `on_event`     |
| 2026.9         | 2.2.0  | `on_event`     |

`cluster.on_event("attribute_report", ...)` is tried first; zigpy emits it for every `Report_Attributes` frame, unknown attributes and unchanged values included. `cluster.add_listener(obj)` with `obj.attribute_updated(attrid, value, timestamp)` is the fallback, unsubscribed with `cluster.remove_listener(obj)`. `handle_cluster_general_request` calls `_update_attribute` for every attribute in the frame, unknown attrids included, and that fires `attribute_updated` unconditionally. It also fires for the integration's own attribute reads, which the attrid filter drops.

Both hooks run the same handler, so decoding, the system-lock rule and the HA event have one implementation. `tests_ha/test_zigpy_listener.py` drives a real zigpy `DoorLock` cluster with a real frame on both, with zigpy pinned per test environment to the version Home Assistant ships.

Earlier versions of this document said the `add_listener` path was "suppressed by zigpy for unknown attributes". Checked against the source on 2026-09-19, that is wrong for every zigpy from 0.80.1 to 0.90.0; only the `on_event` path had been measured.

What does not work:

| Approach                                  | Result                                                                 |
| ----------------------------------------- | ---------------------------------------------------------------------- |
| ZHA `last_action_user` sensor             | Never updates on keypad use, stale from last HA command                |
| `zha_event` bus events                    | `operation_event_notification` (0x0020) never received                 |
| `add_listener` + `handle_cluster_request` | Only for cluster commands, not general commands like Report_Attributes |
| `add_listener` + `general_command`        | Not dispatched to listeners for Report_Attributes                      |

## Reaching the lock through ZHA

ZHA has no public API for a device's zigpy clusters, so everything that knows ZHA's object layout lives in `zha.py`. The rest of the integration talks to a lock through `ZhaLockTransport`, injected into the coordinator so tests can pass a fake.

### Device chain

The gateway comes from ZHA's own helper `get_zha_gateway_proxy`. It raises `ValueError` when ZHA has no running gateway (not set up yet, failed, or reloading), which `zha.py` turns into "no gateway". The device is looked up in `gateway_proxy.device_proxies` by IEEE address, case-insensitively, and the Door Lock cluster lives on the deepest zigpy device object:

```
ZHADeviceProxy (depth 0, no endpoints)
  → Device (depth 1, empty in_clusters)
    → CustomDeviceV2 (depth 2, clusters here)
```

`find_door_lock_cluster()` walks the `.device` chain up to four levels, skips endpoint 0, and returns the first endpoint's Door Lock cluster (0x0101). The config flow's `has_door_lock_cluster()` uses the same walk to decide which devices to offer. Commands go to the endpoint the cluster belongs to (`cluster.endpoint.endpoint_id`); endpoint 11, where every Onesti lock seen so far has the cluster, is only the fallback when that id cannot be read.

### Finding ZHA's device and its lock entity

ZHA registers each device with a zigbee connection holding the IEEE address in lowercase, and `find_zha_device()` looks the device up by that connection, scoped to ZHA's own config entries. From HA 2026.9 a connection is unique only within one config entry, so the lookup is `async_get_device_by_connection(connection, zha_entry_id)`; older releases have no such method, and the devices of each ZHA entry are walked instead. A registry-wide `async_get_device` is not used: HA reports it as breaking in 2027.8.

Two things need that device. The auto-wake calls `lock.lock` on ZHA's lock entity, which `find_lock_entity_id()` takes as the one entity on the device in the `lock` domain from the `zha` platform; disabled entities are skipped, since HA would refuse the service call, and no unique_id format is parsed. And the lock's own device links to it, see Devices.

### Devices

Each lock gets one device of ours, built in `entity.py` by `build_device_info()`: the model read off ZHA, `serial_number` set to the IEEE address, the same zigbee connection ZHA uses, and a name made of the model and the last four characters of the address, so two locks of the same model are told apart on the device page and in entity ids.

Identifiers are `(DOMAIN, entry_id)`, not the IEEE address. A replaced Connect Module brings a new address for the same door, and keying on the entry lets the reconfigure flow point the entry at the new module while the device, its entities, their names and whatever a dashboard refers to stay put. Entity unique ids are `<entry_id>-<key>` for the same reason. Entries from 2.2 and earlier are rewritten by the migration.

What the shared connection does depends on the Home Assistant version, and both are tested. Through 2026.8 a connection is unique across config entries, so the registry merges this device and ZHA's into one entry carrying both integrations, and the lock has a single device page with ZHA's lock entity and ours side by side. From 2026.9 a connection is unique only within one config entry, so the two stay apart, and `build_device_info()` sets `via_device_id` to ZHA's device so ours hangs off it. `DeviceInfo` lost `via_device` in the same release; which field it has is what the code branches on (`HAS_VIA_DEVICE_ID` in `entity.py`).

### When ZHA is reloaded

A ZHA reload or a re-pair builds new zigpy objects, and a listener left on the old cluster would stop receiving lock events without a word. `__init__.py` therefore subscribes to `ConfigEntry.async_on_state_change` on every ZHA config entry that exists at setup, and on every ZHA entry added later (`ConfigEntryChange.ADDED` on `SIGNAL_CONFIG_ENTRY_CHANGED`), so a ZHA removed and added again is still followed. When a ZHA entry reaches `LOADED` while this entry is loaded, the entry schedules its own reload if nothing is listened to yet (`coordinator.listened_cluster` is `None`) or if the cluster ZHA now holds is another one. That is also how the integration recovers when it was set up before ZHA had the lock.

The same watch decides availability. `OnestiCoordinator.available` is true once the event listener sits on a cluster, and `OnestiEntity.available` reads it, so every sensor goes unavailable while no ZHA entry is loaded and comes back when a listener is registered again. A lock that is merely asleep stays available: the slot sensors show Home Assistant's own stored data, the activity sensor the last event it saw, and a command that times out says nothing about whether events arrive. When ZHA comes back with the objects it already had, the listener still fits, so availability is restored without a reload.

The change is logged as one INFO line when events stop (`Lock events for <ieee> stopped, ZHA is not running`) and one when they are back, never the same twice in a row. The flag behind that is per IEEE on the coordinator module rather than per coordinator, because ZHA coming back reloads the entry: the loss is logged by the coordinator that is going away and the return by the one that takes over.

### When ZHA starts after this integration

The ZHA entry is often still in `SETUP_RETRY` when this entry sets up, typically because the coordinator's USB stick comes up late. That is not a fault. When ZHA has no gateway and no ZHA entry is `LOADED`, setup logs one info line, skips the listener and the capability read, and leaves the rest to the ZHA watch: once ZHA reaches `LOADED`, the reload registers the listener, or raises the repair issue if something really is missing.

### Discovering further locks

Home Assistant does not load a custom integration that has no config entry, so the first lock has to be added by hand. Once one entry exists, `async_setup` registers a watch that offers the rest: for every Onesti device in ZHA with a Door Lock cluster that no entry owns, it starts a config flow with `SOURCE_INTEGRATION_DISCOVERY`, and the lock appears under Discovered with its model and IEEE address.

Two things start a look: a device registry entry created or updated for a device with a Zigbee connection belonging to one of ZHA's config entries, which is what a newly paired device looks like, and a ZHA entry reaching `LOADED`, which covers ZHA starting after this integration, when the registry entries were written before the watch existed. Neither says which device it was; the list always comes from the gateway through `iter_onesti_locks()`, the same one the config flow's device picker uses.

`async_step_integration_discovery` sets the IEEE as the flow's unique id, as the user step does. That covers three cases: a lock that already has an entry, a lock the user pressed Ignore on (Home Assistant stores an ignored entry with that unique id), and a second flow for a lock already being asked about. All three abort, so the card does not come back. The confirmation step creates the same entry the user step would.

The watch lives for the whole Home Assistant run, like the services, and is registered in `async_setup` rather than per entry, so unloading one lock does not stop the others from being found.

### Replacing the Connect Module

The module (ZMNC010) is an accessory, and a replacement brings a new IEEE address for the same door. `async_step_reconfigure` offers the Onesti locks in ZHA that no other entry owns, this entry's own lock included, and `async_update_reload_and_abort` writes the new address and model into `entry.data`, moves the unique id with it, and reloads. An entry that appeared between the form and the submit is caught by an explicit check that aborts with `already_configured`.

Nothing else moves. Slot names and PIN status describe the codes in the lock, not in the module, and the device and entity keys are the config entry, so the entities keep their ids and names.

### Repair issue for missing ZHA internals

A lock missing from ZHA altogether, removed or replaced by a module with a new IEEE, is not a repair issue: `async_setup_entry` raises `ConfigEntryNotReady` before anything is set up, and Home Assistant retries with backoff until the lock is back. Nothing in ZHA is broken then.

The event listener depends on three things that are not public API: the gateway, the Door Lock cluster under the device, and a listener hook on that cluster. If one is missing at setup while ZHA is running (a gateway exists or a ZHA entry is `LOADED`), `register_event_listener()` raises `ZhaInternalsMissing`, and `__init__.py` logs an error and creates the repair issue `zha_internals_<entry_id>` (severity error, not fixable). Its `detail` placeholder names the missing piece:

| `detail`                                                             | Meaning                                      |
| -------------------------------------------------------------------- | -------------------------------------------- |
| `ZHA gateway (get_zha_gateway_proxy)`                                | ZHA is `LOADED` but has no gateway           |
| `Door Lock cluster for <ieee>`                                       | ZHA lists the lock, but no Door Lock cluster |
| `<ClusterClass>.on_event, and no add_listener/remove_listener either` | Neither listener hook is on the cluster      |

No zigpy release looks like the last row; every version has at least one of the two hooks. It stands for a future one that drops both.

Without the listener nothing reports who unlocked, though PIN writes may still work when ZHA runs. The issue is deleted when the listener registers and when the entry unloads. What the user does about it is in [debugging.md](debugging.md#repair-issue-lock-events-are-not-being-received).

## Reaching the lock over Bluetooth

`bluetooth.py` is the Bluetooth counterpart of `zha.py`: everything that knows Home Assistant's Bluetooth integration and bleak-retry-connector. The protocol is the `ble/` library ([ble-library.md](nimly-ble-app/ble-library.md)), which may not import Home Assistant, and `ble/client/bleak_transport.py` speaks it over a connected bleak client. Nothing uses `bluetooth.py` yet, and `__init__.py` does not import it: there is no config flow step or coordinator for it, and it has not talked to a lock through Home Assistant.

The manifest does not name `bluetooth_adapters` yet, on purpose. Home Assistant's own Bluetooth integrations depend on it because it depends on `bluetooth` and loads after ESPHome, Shelly and the other integrations that bring remote scanners, so every proxy is known before the entry sets up. As long as nothing here imports `bluetooth.py`, naming it would set the Bluetooth stack up on every installation and hold this entry back until those are done, for nothing. **The dependency goes back in the same change that first imports `bluetooth.py`**, together with the pin on the Bluetooth stack; the module's own imports (bleak, bleak-retry-connector) only exist where Bluetooth is set up. `tests/test_coordinator.py` and `tests_ha/test_bluetooth.py` both hold the manifest to this, so that change has to change those two tests as well. A `bluetooth` matcher stays out for longer: it would start discovery flows in the UI before any flow can enroll a lock.

`async_open_session()` is the one call a caller needs: it finds the lock, connects, runs the key exchange and hands over a `Session`, and releases the connection when the block ends, however it ends. An ESPHome Bluetooth proxy has only a few connection slots, and a held one blocks other integrations. The steps are also public on their own.

`async_find_lock()` looks among the connectable advertisements Home Assistant already holds (`async_discovered_service_info`) for 0xFD00 service data that is the enrolled lock with a given device id (`Advertisement.matches`), or without a device id, a factory-reset lock (seed `00 00`). Two factory-reset locks with no address to choose between is an error, since enrolling the wrong one hands over a neighbour's lock. When the lock is not known yet it registers a callback for 0xFD00 and waits `BLE_ADVERTISEMENT_TIMEOUT_S` (`const.py`), a guess. What has been measured says the lock is not advertising at all in normal operation (an ESPHome proxy 50 cm from Fredrik's lock, the Home Assistant host and a Shelly scanner all saw no 0xFD00 service data, awake lock included, and a third party with a Touch Pro on firmware 4.7.79 saw nothing during use but had the lock appear the moment the vendor's app opened "Add device", [upstream-status.md](upstream-status.md#another-implementation-ariddernimly-manager)). If that holds for an unenrolled module, Home Assistant cannot open a session on its own, since it only knows devices heard in the last few minutes, and enrollment becomes a flow the user starts by opening a window on the lock. An enrolled module may behave differently: the unloc app opens doors by scanning for enrolled locks in ordinary use ([unloc-app.md](nimly-ble-app/unloc-app.md)), which only works if such a module advertises all the time. Nobody has measured either state on this hardware.

`async_connect()` takes the `BLEDevice` for the best path from `async_ble_device_from_address`, drops stale connections from a crashed run (`close_stale_connections_by_address`), and connects with `establish_connection`, whose `ble_device_callback` fetches a fresh path before each retry. bleak's disconnected callback is relayed to `BleakTransport.client_disconnected()` once the transport exists.

The client class is read off `bleak_retry_connector` at call time, never imported by name. While the Bluetooth integration runs, habluetooth replaces `BleakClientWithServiceCache` in that module with its own wrapper, which routes the connection through an adapter or a proxy; a reference taken at import time, before Bluetooth was set up, would connect past Home Assistant's Bluetooth stack.

Every failure is a `BleError` with a message a person can act on: Bluetooth not set up (checked in `hass.config.components`, since the API itself raises a `RuntimeError` from habluetooth then), no adapter or proxy in reach, no free connection slot, or the connect failing or timing out (`BleTimeoutError`).

The two pinned Home Assistant releases run different Bluetooth stacks: bleak 0.22.3, bleak-retry-connector 3.9.0 and habluetooth 3.49.0 on 2025.6, and 3.0.2, 4.7.0 and 6.26.11 on 2026.9. The calls `bluetooth.py` makes have the same shape in both. What differs is outside them: `async_register_callback` gained keyword-only `scan_interval`, `scan_duration` and `replay` arguments, `BluetoothScanningMode` an `AUTO` member, `establish_connection` a `pair` argument, and bleak 1.0 dropped `rssi` from `BLEDevice`. Both releases replay advertisements already seen to a newly registered callback. `tests_ha/test_bluetooth.py` runs the lookup and the connect against the real Bluetooth manager of each, with advertisements injected the way Home Assistant's own tests do.

## Sending commands

`ZhaLockTransport.send()` calls the command on the lock's zigpy Door Lock cluster directly, `cluster.command(command_id, **params)`, on the cluster `find_door_lock_cluster()` returns. This is the call ZHA's `issue_zigbee_cluster_command` service ends in (`Device.issue_cluster_command` in the zha library), and `send()` does what that method does around it: zigpy's default reply timeout, which ZHA does not change; no manufacturer code, since the service only fills one in for manufacturer clusters (0xFC00 and up) and never passes it on to the cluster call anyway; and the answer read the same way. A `None` answer is success, an exception handed back is a failure, and otherwise the answer's `status` field decides, anything but `SUCCESS` being a failure. The answer is a Default Response or the command's own response, such as Set PIN Code Response, and both name the field `status`. An answer without one counts as success, as in ZHA.

`send()` returns a `SendOutcome` with one of three values of `Delivery`:

| Outcome     | When                                                                                                       | Wake and retry |
| ----------- | ---------------------------------------------------------------------------------------------------------- | -------------- |
| `DELIVERED` | The lock answered with no failure status, or the Nimly `IndexError` quirk (below)                         | No             |
| `REJECTED`  | The lock answered with a status other than `SUCCESS`; the outcome carries the status                     | No             |
| `UNREACHED` | Timeout or failed delivery after one wake and retry, any other Zigbee error, no cluster, an exception handed back, or any unexpected error | Only for timeout and failed delivery |

Where the service raised `ZHAException` for a failure status, `send()` returns `REJECTED` with a warning naming the status. The lock answered, so it is awake, and nothing is woken. A refusal still counts as a moment the radio is awake, so the coordinator schedules the capability read after it, as after a delivered command.

For Set PIN Code the ZCL Door Lock spec gives the response's status byte four values: 0 success, 1 general failure, 2 memory full, 3 duplicate code. `REJECTED` records 2 as `MEMORY_FULL` and 3 as `DUPLICATE_CODE`, but only from Set PIN Code's own response. A Default Response carries a general ZCL status, where those numbers mean something else, so it is always `OTHER`. The services raise, and the options flow shows, `lock_rejected_memory_full`, `lock_rejected_duplicate` or `lock_rejected` with the status number, instead of the "could not reach the lock" text, which is wrong advice for a lock that answered.

None of these statuses has been seen from a real Onesti lock. Which of them a Nimly lock sends for a duplicate code, a full table or a slot above its capacity, and whether it sends any at all rather than silently storing or dropping the code, is still to be captured on hardware. Until then, the texts for duplicate and memory full rest on the ZCL spec alone.

The service is not used because Home Assistant fires a `call_service` event with the full service data for every service call, and the recorder stores those events. Through the service, every PIN the integration set, from the options flow as well, was written to the recorder in clear text. `tests_ha/test_pin_canary.py` checks that no `call_service` event carries the code. The same bypass keeps the parameters out of the debug line ZHA's service logs for each command.

`tests_ha/test_zha_contract.py` fails when Home Assistant moves to a zha library release whose `issue_cluster_command` has not been read against `send()`. zha 0.0.59 (HA 2025.6) and 2.2.2 (HA 2026.9) have been.

Not verified on a real lock: that the direct call behaves like the service did against an Onesti lock. The frame on the air should be the same, since both end in the same zigpy call with the same arguments, but no PIN has been set this way on hardware yet. The status check is also new for HA 2025.x: the answer's status was never read there (see below), so a lock that answers a delivered PIN with a failure status now gets `REJECTED` where it used to count as delivered.

### Nimly response quirk

PIN commands used to fail with `IndexError: tuple index out of range` even though the command reached the lock. The source is ZHA, not the lock, and the line was found on 2026-09-20: `Device.issue_cluster_command` in zha 0.0.59 (`zha/zigbee/device.py`, behind the `issue_zigbee_cluster_command` service the integration used to call) checks `if response[1] is not ZclStatus.SUCCESS`, which assumes the two-field Default Response `(command_id, status)`. Set PIN Code Response and Clear PIN Code Response have one field, `status`, so index 1 does not exist. zha 2.2.2 has replaced that line with `getattr(response, "status", None)` and a comment saying exactly this, so the bug is fixed upstream and there is nothing left to report. The vendor's 2021 spec ([elife-module-spec.md](zigbee-protocol/elife-module-spec.md)) documents the answer as one status byte, FAILURE or SUCCESS, the standard one-field response zigpy parses without trouble; the error was never in the frame. `send()` reads the status by name, so it should not see the error at all. It still catches `IndexError` and treats the command as sent, logged at debug level only, in case the lock's answer itself trips zigpy's parser.

## Coordinator pattern

`OnestiCoordinator` is a custom class, on purpose not based on HA's `DataUpdateCoordinator`: a polling coordinator makes no sense for a battery-powered Zigbee EndDevice that sleeps between events and cannot be polled. There is one per lock, on `entry.runtime_data`.

### Slot data storage

Slot data is stored in the config entry's options (`.storage`), which survives restarts. Keys are strings (`"0"`, `"1"`, ...) because `ConfigEntry.options` serializes to JSON. A stored slot holds `name` and `has_pin` and nothing else; fields outside that schema are dropped on load, so a hand-edited or older save cannot bring them back. The same options hold `reserved_slots` from the settings form and `capabilities` once the lock has reported them.

The config entry is at version 2.3. `async_migrate_entry` takes a 2.1 entry to 2.2 by stripping `has_rfid` from every stored slot, a field nothing ever set, and a 2.2 entry to 2.3 by storing the model in `entry.data` and moving the registry keys from the IEEE address to the entry id: the device identifier becomes `(DOMAIN, entry_id)` and every entity unique id `<entry_id>-<key>`, rewritten in place with `async_update_device` and `async_update_entity` so entity ids and user-set names survive. The model is read off ZHA when it is running; an entry migrated before ZHA is up keeps an empty model until a reconfigure fills it in. An entry written by a newer major version is refused rather than guessed at.

### PIN operations

`set_pin`, `clear_pin` and `clear_slot` refuse slots below the first user slot (`_check_writable`), whoever calls them, so slot 0 is never written from HA. They run one at a time per lock under an `asyncio.Lock`, since the options flow and the services can both write, and interleaved sends and saves could leave storage describing the older of two writes. Each returns the transport's `SendOutcome`, and local state changes only when it is `DELIVERED`: a failed or refused `clear_slot` does not show the slot as vacant while the lock still accepts the old code, and a refused `set_pin` does not mark the slot as having a PIN.

A delivered send means the lock took the frame and reported no failure. Whether it stored the code depends on what the lock reports, which is unverified (see Sending commands), so a code that looks set may still be worth trying on the keypad.

In the options flow, a PIN write runs as its own task, and the progress task HA shows only waits for it through `asyncio.shield`. HA cancels the progress task when the dialog closes, and by then the command may have reached the lock, so cancelling it before the save would leave storage describing the old code. The write finishes on its own and logs its outcome, and the flow logs at info level when a dialog closes while a write is running.

### Listener pattern

The slot sensors register callbacks with `add_listener(callback)`. When slot data changes, the coordinator calls `_notify_listeners()`, which runs `async_write_ha_state()` in each sensor.

### Slot sensors and reloads

The slot sensor row starts at the first user slot and has `NUM_USER_SLOTS` (10) sensors, each with the unique_id `<entry_id>-slot-<n>`. On setup, registry entries for slot sensors outside the current row are removed, so moving `reserved_slots` leaves no unavailable entities behind, and a slot in both rows keeps its entity id.

Changing `reserved_slots` reloads the entry through an update listener. The coordinator writes slot data and capabilities to the same options, and every write calls that listener, so it compares the first user slot with the one the setup was built for and reloads only when that changed.

### Activity sensor

The activity sensor registers separately, with `set_activity_sensor(sensor)`, and gets `update_activity(user_slot, action, source)` for every decoded operation event that is not a system lock (`is_system_lock()` in `events.py`):

- source `auto`, always
- source `unattributed` with action lock and no user slot, which is how NimlyCodePRO reports auto-relock
- source `zigbee` with action lock and no user slot, but only while the wake echo is pending (see [Wake echo](#wake-echo))

That keeps auto-relock and the integration's own wake from overwriting the last activity that mattered. A Zigbee lock from a dashboard outside the echo window does update the sensor, and so does a master code unlock on slot 0.

The sensor is a `RestoreEntity`. It stores the raw fields (`user_name`, `user_slot`, `action`, `source`, `timestamp`) as extra restore data, never the rendered text, and builds the state from them with the current strings, so it comes back after a restart and follows a change of server language. Restored data is filtered to those five keys, and data without a string `action` and `source` is dropped. `timestamp` is ISO 8601 in UTC (`dt_util.utcnow()`).

### Lock capabilities

The coordinator reads the standard ZCL DoorLock attributes 0x0012 (NumberOfPINUsersSupported), 0x0017 (MaxPINCodeLength) and 0x0018 (MinPINCodeLength) until the lock has answered once: at setup, after every command that reached the lock, and on every attribute report from the lock, whatever the attribute. The last two are the moments the radio is known to be awake. Each read runs as a background task tied to the entry, so an unload cancels a read still waiting on a sleeping lock. `read_capabilities()` returns `None` when the lock was not reached, and the read is repeated at the next chance. Any answer is final, also one without these attributes, since some variants skip them. The answer is stored in `entry.options["capabilities"]`, loaded from there at the next setup, and the lock is never asked again. zigpy may key the answer by attribute id or by name, and both are mapped.

What the capabilities decide is in `pin_rules.py`. `set_pin` rejects slots at or above NumberOfPINUsersSupported (`max_user_slot`, highest slot N-1); a missing count, or one outside 4-1000, gives the manual's ceiling of 999. NimlyPRO and NimlyCodePRO both report 50. A PIN code is ASCII digits within the reported min and max length (`pin_length_range`); each bound is trusted only between 4 and 20 and falls back on its own to 4-8, and if the two bounds left over contradict each other, 4-8 applies. The floor of 4 is there for the log masking: a lock that reports a minimum of 3 still gets 4.

### Runtime strings

Sensor states and options-flow labels are built in Python and never pass through HA's translation layer. `localize.py` looks them up in the `common` section of `translations/<lang>.json` for the server language (`hass.config.language`). The section is called `common` because hassfest rejects any top-level key outside HA's strings schema, and `common` is one it allows. English, Norwegian bokmål, Swedish and Danish ship with the integration; `no` and `nn` map to `nb`, and missing keys fall back to English. The coordinator loads them at setup.

## Auto-wake mechanism

Battery-powered Zigbee EndDevices sleep most of the time, and ZCL commands like `set_pin_code` fail while the radio is asleep. `ZhaLockTransport.send()` sends the command to the zigpy cluster; on `TimeoutError` or zigpy's `DeliveryError` it calls `wake()`, which sends `lock.lock` to ZHA's lock entity and waits 1 second for the radio to settle, and then sends the command once more. A second failure returns `False`.

`DeliveryError` is included because a sleeping lock can plausibly surface as a failed delivery and not only as a timeout; which of the two a real Onesti lock produces has not been checked. Any other `ZigbeeException` has nothing to do with sleep, so it returns `False` at once without moving the bolt. Any other exception is logged as an error and returns `False` as well: `send()` never raises. `wake()` must not stop the retry: with no ZHA lock entity it logs a warning and skips the wake, and if the service call fails the retry runs anyway.

`lock.lock` is used because it works, while attribute reads through the integration's own cluster path time out. Why is not established. Nothing sent over the air wakes a sleeping EndDevice, since its radio is off; all the coordinator can do is queue a unicast at the parent router and hope the lock polls within the 7.68-second window, and once one frame gets through, the lock fast-polls and drains the rest, which is what looks like waking. At that level a `read_attributes` is queued exactly like a lock command, so if `lock.lock` works better than a plain read (`read_capabilities` usually goes unanswered against a sleeping lock), the difference is the retry and extended-timeout envelope ZHA gives its lock entity, not the fact that it writes. That is why `homeassistant.update_entity` on the ZHA lock entity, which goes through the same entity path, is the candidate for a bolt-free wake, with "only wake when the cached state is already locked" as the fallback.

The wake is a real lock command: an unlocked door gets physically locked, and an open door drives the bolt out into the air. The [user guide's limitations](user-guide.md#limitations) and the options flow texts both say so. A wake that does not move the bolt is not solved, and replacing the mechanism needs testing on real hardware first.

### Wake echo

The lock reports the wake's `lock.lock` as an ordinary Zigbee lock (source `zigbee`, no user slot), which would replace the last activity every time a PIN is set on a sleeping lock. `wake()` stamps the time just before the service call, because the report can arrive while the call is still waiting, and `wake_echo_pending()` is true for `WAKE_ECHO_WINDOW_S` (30 seconds, `const.py`) after that. If the service call fails, the stamp goes back to what it was, so a failed wake opens no window. Asking does not reset it, since the lock may report the wake more than once. Inside the window, a Zigbee lock without a user slot counts as a system lock: the event still fires, the activity sensor stays as it was.

The 30 seconds are a generous guess. How long the report can trail the command on a real lock has not been measured.

The trade-off is deliberate. A real lock from a dashboard within 30 seconds of the integration's own wake looks exactly like the echo (source `zigbee`, action lock, no user slot), so it is taken for the echo and the activity sensor does not change. The `onesti_lock_activity` event still fires for it. Unlocks, locks with a user slot, and anything from the keypad, fingerprint or RFID are never affected.

## Logging and PIN codes

Parameters for `set_pin_code` hold the PIN, and exception messages on the send path are not ours to shape: an error from building the frame may quote the params, and a zigpy error may echo the frame. `send()` therefore never logs a traceback, and every exception message goes through `redact_digits()` in `redact.py` first. It replaces every run of four or more digits with a fixed `****`, so the mask does not reveal the code's length either. Shorter runs stay readable, since command ids, slot numbers and ZCL status codes are what make an error message useful.

The mask covers every PIN the integration accepts only because `pin_rules` never accepts a code shorter than 4 (`PIN_LENGTH_SANE_MIN`, which `redact.py` imports). Lowering one without the other puts codes in the log.

This covers the integration's own log lines. ZHA and zigpy log on their own terms, see [debugging.md](debugging.md#pin-codes-appear-in-raw-logs-and-diagnostics).

## `onesti_lock_activity` event

Every operation event decoded from attrid `0x0100` fires `onesti_lock_activity`, auto-lock and the wake echo included. The payload, what `null` means in it, and automation examples are in the [user guide](user-guide.md#the-onesti_lock_activity-event).

## Sleepy device behavior

The Connect Module ZMNC010 is a battery-powered Zigbee EndDevice whose radio sleeps between events. What wakes it, the 7.68-second message TTL at the parent router, and recovery after a battery change are in [debugging.md](debugging.md#1-zigbee-connectivity), section 1.

## Community references

- [Z2M PR #11332: PIN code parsing and user tracking](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332)
- [Z2M issue #17205: Not fully supported](https://github.com/Koenkk/zigbee2mqtt/issues/17205)
- [Z2M issue #5884: Original device support](https://github.com/Koenkk/zigbee2mqtt/issues/5884)
- [ZHA issue #3095: Device support request](https://github.com/zigpy/zha-device-handlers/issues/3095)
- [HA community: Nimly lock thread (12+ pages)](https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634)
- [Blakadder: ZMNC010](https://zigbee.blakadder.com/Nimly_ZMNC010.html)

## ZMNC010 Connect Module

The radio module inside the Onesti/Nimly locks, also sold separately. It carries Zigbee and Bluetooth LE on one Nordic part; this integration uses the Zigbee side only.

| Property              | Value                                                                  |
| --------------------- | ---------------------------------------------------------------------- |
| Manufacturer code     | `0x1234` (4660), not registered with the Zigbee Alliance; the default an unconfigured ZBOSS stack reports, and ZBOSS is the Zigbee stack in Nordic's nRF Connect SDK |
| Max buffer size       | 108                                                                    |
| Max incoming transfer | 127                                                                    |
| Max outgoing transfer | 127                                                                    |
| Logical type          | EndDevice (battery-powered)                                            |
| Frequency             | 2.4 GHz (Zigbee 3.0)                                                   |
| Certifications        | CE-marked, no FCC ID found (European product)                          |

Two independent clues point at the same silicon. The EUI64 of every Onesti Products AS lock seen so far begins with `f4:ce:36`, an OUI the IEEE registry assigns to Nordic Semiconductor ASA, and manufacturer code 4660 is what a ZBOSS stack reports before a vendor sets its own. The only Nordic parts with an 802.15.4 radio (nRF52840, nRF52833, nRF5340) carry Bluetooth LE on the same die, so the module has a BLE radio whatever its revision; whether the firmware on a given module uses it is another question (the vendor's module guide says Bluetooth is only on "newer versions", and no advertisement has been captured from Fredrik's lock). An earlier edition of this file guessed at a TI CC2530, which has no Bluetooth and cannot be it. Which Nordic part it is has not been established. Details and the Basic cluster version attributes are in [hardware-gateway.md](connect-bridge/hardware-gateway.md#which-silicon).

The firmware has changed more than the hardware. The vendor's 2021 spec lists no `0x0100` or `0x0101` attribute, and a March 2021 Zigbee sniff of an EasyCodeTouch on the same Nordic OUI shows lock state reports and nothing manufacturer-specific ([zigbee-captures.md](zigbee-protocol/zigbee-captures.md#captures-from-other-locks)). The operation event this integration is built on arrived in a later firmware, and which one is not known. One report ([Z2M#6551](https://github.com/Koenkk/zigbee2mqtt/issues/6551)) shows a differently-branded EasyAccess lock on a different OUI and a different `ManufacturerName`, which the config flow would not discover at all; [hardware-generations.md](hardware-generations.md) has that report and every other one caught so far.

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
