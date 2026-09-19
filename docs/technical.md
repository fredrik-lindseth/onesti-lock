# Technical details

## How user identification works

Onesti locks send a custom attribute report (`attrid 0x0100`) on the Door Lock cluster for every lock and unlock. The value is a bitmap32 holding user slot, action and source, and no existing integration decoded it. This integration listens for the reports with `cluster.on_event("attribute_report", ...)` and decodes the bitmap:

```
Bits 0-15:  user_slot (uint16 LE; 0 = master or no user, see below)
Bits 16-23: action (1 = lock, 2 = unlock)
Bits 24-31: source (see _SOURCE_MAP in __init__.py)
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

`_SOURCE_MAP` in `__init__.py` is the canonical decoder, so update this table when the map changes. The raw captures behind these values are in `docs/zigbee-protocol/zigbee-captures.md`.

`attrid 0x0101` holds the PIN code in BCD plaintext. The integration leaves it
alone on purpose. Every state attribute ends up in the recorder, the logbook and
diagnostics, which would put real access codes on disk (see
zha-device-handlers#4881), and the slot number from 0x0100 already identifies
the user.

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

## ZHA device chain

The Door Lock cluster lives on the deepest zigpy device object:

```
ZHADeviceProxy (depth 0, no endpoints)
  → Device (depth 1, empty in_clusters)
    → CustomDeviceV2 (depth 2, clusters here)
```

## Nimly response quirk

PIN commands get a malformed ZCL response back, and zigpy raises `IndexError: tuple index out of range` on it. The command reaches the lock, and only the response parsing fails. The integration catches the error and treats the command as sent. It logs the quirk at debug level only, so it stays out of the log unless debug logging is on.

## Coordinator pattern

`NimlyCoordinator` is a custom class, on purpose NOT based on HA's `DataUpdateCoordinator`. A polling coordinator makes no sense for a battery-powered Zigbee EndDevice that sleeps between events and cannot be polled.

### Slot data storage

User-to-slot mappings are stored in the config entry's options dict (`.storage`), which survives HA restarts. Dictionary keys are strings (`"0"`, `"1"`, ...) because `ConfigEntry.options` serializes to JSON.

### Listener pattern

Sensors (for example the slot overview sensor) register callbacks with `add_listener(callback)`. When slot data changes (a name set, a PIN set or cleared), the coordinator calls `_notify_listeners()`, which runs `async_write_ha_state()` in each sensor.

### Activity sensor

The activity sensor registers separately, with `set_activity_sensor(sensor)`. The coordinator calls `update_activity(user_slot, action, source)` on it for every decoded operation event except system-initiated locking, which is source `auto`, and on NimlyCodePRO an `unattributed` lock with no user slot. That keeps auto-relock from overwriting the last activity that mattered. A master code unlock on slot 0 is a user event and does update the sensor.

### Lock capabilities

At setup the coordinator reads the standard ZCL DoorLock attributes 0x0012 (NumberOfPINUsersSupported), 0x0017 (MaxPINCodeLength) and 0x0018 (MinPINCodeLength) in the background, and carries on without them if the lock never answers. `set_pin` rejects slots above what the lock reports (`pin_rules.max_user_slot`, highest slot = N-1). When the attribute is missing or makes no sense, the manual's 0-999 range applies. NimlyPRO and NimlyCodePRO both report 50 PIN users.

### Runtime strings

Sensor states and options-flow labels are built in Python and never pass through HA's translation layer. `localize.py` looks them up in the `runtime` section of `translations/<lang>.json` for the server language (`hass.config.language`). English, Norwegian bokmål, Swedish and Danish ship with the integration. `no` and `nn` map to `nb`, and missing keys fall back to English.

## Auto-wake mechanism

Battery-powered Zigbee EndDevices sleep most of the time, and ZCL commands like `set_pin_code` time out while the radio is asleep. `_send_cluster_command()` in the coordinator wakes the lock and retries:

1. The first attempt sends the ZCL command via `zha.issue_zigbee_cluster_command`.
2. On `TimeoutError` it calls `_wake_lock()` and retries the original command once.
3. `_wake_lock()` sends a `lock.lock` service call to the ZHA lock entity.
4. After a 1-second pause for the radio to settle, the original command is retried.

`lock.lock` is used because it works, while attribute reads through the integration's own cluster path time out. Why it works is not established. ZHA's lock entity wraps the command in longer timeouts and retries for sleepy devices, which is the likely reason, but at the radio level a read and a write are queued the same way.

The wake has a side effect, since it is a real lock command and not a read. An unlocked door gets physically locked, and an open door drives the bolt out into the air. The README limitations and the options flow texts both say so. A wake that does not move the bolt is not solved yet, and replacing the mechanism needs testing on real hardware first.

Nothing sent over the air wakes a sleeping EndDevice, since its radio is off. All the coordinator can do is queue a unicast at the parent router and hope the lock polls within the 7.68-second window; once one frame gets through, the lock fast-polls and drains the rest, which is what looks like waking. At that level a `read_attributes` is queued exactly like a lock command, so if `lock.lock` works better than a plain read (`read_lock_capabilities` just times out against a sleeping lock), the difference is the retry and extended-timeout envelope ZHA gives its lock entity, not the fact that it writes. That is why `homeassistant.update_entity` on the ZHA lock entity, which goes through the same entity path, is the candidate for a bolt-free wake, with "only wake when the cached state is already locked" as the fallback.

To find the ZHA lock entity, `_wake_lock()` scans the entity registry for an entity where `platform == "zha"`, the `unique_id` contains the device's IEEE address, and the `unique_id` ends with `"257"` (the DoorLock cluster endpoint identifier).

Commands go through `zha.issue_zigbee_cluster_command` instead of touching the cluster directly, so ZHA's service layer handles ZCL framing and transport.

## `onesti_lock_activity` event

Every operation event decoded from attrid `0x0100` fires a Home Assistant event that automations can use:

- **Event name:** `onesti_lock_activity`
- **Payload:** `ieee`, `user_slot`, `user_name`, `action`, `source`. `user_slot` is `0` for the master credential (keypad, fingerprint or rfid source) and `null` when no user was involved.
- **Scope:** fired for ALL events, auto-lock included.
- **Activity sensor:** not updated for system-initiated locking (source `auto`, or an `unattributed` lock with no user slot on NimlyCodePRO), so auto-relock does not immediately overwrite the last user event.

### Automation example

```yaml
automation:
  - alias: "Notify when someone unlocks the front door"
    trigger:
      - platform: event
        event_type: onesti_lock_activity
        event_data:
          action: unlock
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.source != 'auto' }}"
    action:
      - service: notify.mobile_app
        data:
          title: "Door unlocked"
          message: >
            {{ trigger.event.data.user_name or 'Unknown' }}
            unlocked via {{ trigger.event.data.source }}
```

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
| [Zigbee Lock Manager](https://github.com/Fiercefish1/Zigbee-Lock-Manager) | Abandoned (last update Sep 2024). No config flow, doesn't handle Onesti response quirk            |

## Comparison with Zigbee2MQTT

Z2M has an `onesti.ts` converter for these locks, and this integration decodes the same Onesti attributes. Where they differ:

| Feature                                           | This integration (ZHA)                                  | Z2M `onesti.ts`                 |
| ------------------------------------------------- | ------------------------------------------------------- | ------------------------------- |
| Decode attrid 0x0100 (user/source/action)         | Yes                                                     | Yes                             |
| Last used PIN code (attrid 0x0101)                | No, removed on purpose (0x0101 is the PIN in plaintext) | Yes, `last_used_pin_code` state |
| Lock capabilities (max users, min/max PIN length) | Yes, read at setup                                      | Yes                             |
| Set / clear PIN codes                             | Yes, via HA UI and services                             | Yes, via MQTT                   |
| Name any slot (for RFID/fingerprint)              | Yes, persisted in HA                                    | No                              |
| Activity sensor with human-readable messages      | Yes                                                     | No, raw fields only             |
| HA events for automations                         | Yes, `onesti_lock_activity`                             | Via MQTT events                 |
| Auto-wake for sleepy device                       | Yes, send lock command before retry                     | No                              |
| Blueprints included                               | Yes (connectivity, goodnight, notifications)            | No                              |
| Protocol                                          | ZHA only                                                | Zigbee2MQTT only                |
