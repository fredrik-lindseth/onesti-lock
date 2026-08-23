# Technical Details

## How user identification works

Onesti locks send a custom attribute report (`attrid 0x0100`) on the Door Lock cluster for every lock/unlock event. This bitmap32 encodes user slot, action, and source — but no existing integration decoded it.

This integration listens for these reports via `cluster.on_event("attribute_report", ...)` and decodes the bitmap:

```
Bits 0-15:  user_slot (uint16 LE; 0 = system, 3-999 = user)
Bits 16-23: action (1 = lock, 2 = unlock)
Bits 24-31: source (see _SOURCE_MAP in __init__.py)
```

| Source byte | Meaning |
| ----------- | ------- |
| `0x00` | zigbee (remote command) |
| `0x02` | keypad (PIN code) |
| `0x03` | fingerprint |
| `0x04` | rfid |
| `0x05` | unattributed (NimlyCodePRO fw 4.8 reports this for Zigbee, auto-relock and interior keypad alike) |
| `0x0A` | auto (auto-relock) |

`_SOURCE_MAP` in `__init__.py` is the canonical decoder; update this table when the map changes. Raw captures behind these values live in `docs/zigbee-protocol/zigbee-captures.md`.

`attrid 0x0101` contains the PIN code in BCD plaintext. The integration deliberately
does not decode or expose it: every state attribute ends up in the recorder, the
logbook and diagnostics, which would put real access codes on disk (see
zha-device-handlers#4881). The slot number from 0x0100 already identifies the user.

## Why standard ZHA approaches don't work

We tested 6 different approaches before finding one that works. The lock sends event data, but ZHA/zigpy doesn't expose it through standard APIs:

| Approach                                   | Result                                                                          |
| ------------------------------------------ | ------------------------------------------------------------------------------- |
| ZHA `last_action_user` sensor              | Never updates on keypad use — stale from last HA command                        |
| `zha_event` bus events                     | `operation_event_notification` (0x0020) never received                          |
| `add_listener` + `attribute_updated`       | Suppressed by zigpy for unknown attributes (`_suppress_attribute_update_event`) |
| `add_listener` + `handle_cluster_request`  | Only for cluster commands, not general commands like Report_Attributes          |
| `add_listener` + `general_command`         | Not dispatched to listeners for Report_Attributes                               |
| **`cluster.on_event("attribute_report")`** | **Works — catches all attribute reports including custom 0x0100**               |

## ZHA device chain

The Door Lock cluster lives on the deepest zigpy device object:

```
ZHADeviceProxy (depth 0, no endpoints)
  → Device (depth 1, empty in_clusters)
    → CustomDeviceV2 (depth 2, clusters here)
```

## Nimly response quirk

PIN commands return a malformed ZCL response causing `IndexError: tuple index out of range` in zigpy. The command reaches the lock — the error is in response parsing only. This integration catches the error silently.

## Slot data persistence

User→slot mapping stored in config entry options (`.storage`), survives restarts.

## Coordinator pattern

`NimlyCoordinator` is a custom class — intentionally NOT based on HA's `DataUpdateCoordinator`. A polling coordinator makes no sense for a battery-powered Zigbee EndDevice that sleeps between events and cannot be polled.

**Slot data storage:** User-to-slot mappings are stored in the config entry's options dict (`.storage`), which survives HA restarts. Dictionary keys are strings (`"0"`, `"1"`, ...) because `ConfigEntry.options` serializes to JSON.

**Listener pattern:** Sensors (e.g. the slot overview sensor) register callbacks via `add_listener(callback)`. When slot data changes (name set, PIN set/cleared), the coordinator calls `_notify_listeners()` which invokes all registered callbacks. This triggers `async_write_ha_state()` in each sensor.

**Activity sensor:** Registered separately via `set_activity_sensor(sensor)`. The coordinator calls `update_activity(user_slot, action, source)` on it when an operation event is decoded, except for system-initiated locking: source `auto`, and on NimlyCodePRO an `unattributed` lock with no user slot. This keeps auto-relock from overwriting the last meaningful activity.

## Auto-wake mechanism

Battery-powered Zigbee EndDevices sleep most of the time. ZCL commands like `set_pin_code` time out if the radio is asleep. The coordinator implements a wake-and-retry strategy in `_send_cluster_command()`:

1. First attempt: send the ZCL command via `zha.issue_zigbee_cluster_command`
2. On `TimeoutError`: call `_wake_lock()`, then retry the original command once
3. `_wake_lock()` sends a `lock.lock` service call to the ZHA lock entity — ZHA's lock entity uses extended timeout for sleepy devices, which reliably wakes the radio
4. After a 1-second delay (for the radio to stabilize), the original command is retried

**Side effect:** the wake is a real lock command, not a read. An unlocked door is physically locked, and an open door drives the bolt out into the air. This is documented in the README limitations and in the options flow texts. Replacing the mechanism with a non-actuating wake requires hardware testing and is tracked as a separate issue.

**Lock entity discovery:** `_wake_lock()` finds the ZHA lock entity by scanning the entity registry for an entity where `platform == "zha"`, the `unique_id` contains the device's IEEE address, and the `unique_id` ends with `"257"` (the DoorLock cluster endpoint identifier).

**Service used:** `zha.issue_zigbee_cluster_command` — not direct cluster access. This goes through ZHA's service layer which handles ZCL framing and transport.

## `onesti_lock_activity` event

Every operation event decoded from attrid `0x0100` fires a Home Assistant event for use in automations:

- **Event name:** `onesti_lock_activity`
- **Payload:** `ieee`, `user_slot`, `user_name`, `action`, `source`
- **Scope:** Fired for ALL events including auto-lock
- **Activity sensor:** Not updated for system-initiated locking (source `auto`, or an `unattributed` lock with no user slot on NimlyCodePRO), so auto-relock does not immediately overwrite the last user event

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

The Nimly/Onesti lock uses a battery-powered Zigbee EndDevice (Connect Module ZMNC010). The radio sleeps between events to conserve battery.

**What wakes the Zigbee radio:**

- Entering a complete PIN code + `#` on the keypad
- Physical lock/unlock (turning the knob)
- Lock/unlock command from HA (ZHA uses extended timeout)

**What does NOT wake the radio:**

- Touching the keypad alone (wakes the keypad backlight, but not the Zigbee radio)

**Message TTL at parent router:** 7.68 seconds. Messages queued for a sleeping EndDevice are discarded after this window.

**After battery change:**

- The lock re-joins the Zigbee network, but bindings may reset
- `reconfigure` often fails (binding + reporting setup times out)
- Battery reporting stops until bindings are re-established
- `set_pin_code` times out consistently (hours or days)
- Lock/unlock still works (simpler commands with ZHA's extended timeout)
- **Resolution:** Wait hours/days for bindings to re-establish, or remove and re-pair the lock in ZHA

## Community references

- [Z2M PR #11332 — PIN code parsing and user tracking](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332)
- [Z2M issue #17205 — Not fully supported](https://github.com/Koenkk/zigbee2mqtt/issues/17205)
- [Z2M issue #5884 — Original device support](https://github.com/Koenkk/zigbee2mqtt/issues/5884)
- [ZHA issue #3095 — Device support request](https://github.com/zigpy/zha-device-handlers/issues/3095)
- [HA community — Nimly lock thread (12+ pages)](https://community.home-assistant.io/t/nimly-lock-with-zigbee-module/523634)
- [Blakadder — ZMNC010](https://zigbee.blakadder.com/Nimly_ZMNC010.html)

## ZMNC010 Connect Module

The Zigbee radio module inside all Onesti/Nimly locks. Sold separately as an accessory.

| Property              | Value                                                                  |
| --------------------- | ---------------------------------------------------------------------- |
| Manufacturer code     | `0x1234` (4660) — placeholder, NOT registered with the Zigbee Alliance |
| Max buffer size       | 108                                                                    |
| Max incoming transfer | 127                                                                    |
| Max outgoing transfer | 127                                                                    |
| Logical type          | EndDevice (battery-powered)                                            |
| Frequency             | 2.4 GHz (Zigbee 3.0)                                                   |
| Certifications        | CE-marked — no FCC ID found (European product)                         |

The unregistered manufacturer code (`0x1234`) suggests an OEM module rather than a custom Zigbee implementation. The small buffer/transfer sizes are consistent with a lower-end chip (likely TI CC2530 or similar).

## Alternatives considered

| Integration                                                               | Why not                                                                                           |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| [Keymaster](https://github.com/FutureTense/keymaster)                     | Z-Wave only — no Zigbee support                                                                   |
| [Lock Code Manager](https://github.com/raman325/lock_code_manager)        | Requires `supported_features` on lock entity. ZHA reports `supported_features: 0` for these locks |
| [Zigbee Lock Manager](https://github.com/Fiercefish1/Zigbee-Lock-Manager) | Abandoned (last update Sep 2024). No config flow, doesn't handle Onesti response quirk            |

## Comparison with Zigbee2MQTT

Z2M has an `onesti.ts` converter for these locks. This integration decodes the same Onesti attributes. The key differences:

| Feature | This integration (ZHA) | Z2M `onesti.ts` |
|---------|------------------------|-----------------|
| Decode attrid 0x0100 (user/source/action) | Yes | Yes |
| Last used PIN code (attrid 0x0101) | No, removed on purpose (0x0101 is the PIN in plaintext) | Yes — `last_used_pin_code` state |
| Lock capabilities (max users, min/max PIN length) | Yes — read at setup | Yes |
| Set / clear PIN codes | Yes — via HA UI and services | Yes — via MQTT |
| Name any slot (for RFID/fingerprint) | Yes — persisted in HA | No |
| Activity sensor with human-readable messages | Yes | No — raw fields only |
| HA events for automations | Yes — `onesti_lock_activity` | Via MQTT events |
| Auto-wake for sleepy device | Yes — send lock command before retry | No |
| Blueprints included | Yes (connectivity, goodnight, notifications) | No |
| Protocol | ZHA only | Zigbee2MQTT only |
