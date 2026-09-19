# Debugging guide

How to track down the usual problems with the Onesti Lock integration.

## LED indicators and sounds

Source: [Nimly Touch Pro Manual](https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf)

### Keypad (outside unit)

| Indicator                          | Meaning                                            |
| ---------------------------------- | -------------------------------------------------- |
| Green flash + short beep           | Success (unlock, registration, programming)        |
| Red flash                          | Failure (wrong code, timeout, registration failed) |
| Long beep + green flash            | Successful factory reset                           |
| Repeated frequent beeps on locking | Low battery, replace batteries soon                |
| White backlit keypad               | Keypad woken (touch), ready for input              |

With the anti-tamper function on (programming sequence `#2`, master code, `#1`), three wrong codes in a row disable the keypad for 5 minutes. The manual does not say whether it is on from the factory.

The camouflage function lets you type false digits before and after the real code, so `21345681#` works when the real code is `3456`.

### Sound volume

Set with the master code (programming sequence `#0`):

| Value | Level            |
| ----- | ---------------- |
| 0     | Silent           |
| 1     | Low              |
| 2     | Normal (default) |

### Connect Module LED (E-Life 3.0 / ZMNC010)

The flashing and reset rows come from the Connect Module installation guide. The solid and no-LED rows are not in any manual and have not been checked against a module, so treat them as a guess.

| LED    | Pattern    | Meaning                                        |
| ------ | ---------- | ---------------------------------------------- |
| Blue   | flashing   | BLE pairing mode (searching)                   |
| Orange | flashing   | Zigbee pairing mode (searching)                |
| Orange | fast blink | Reset in progress (hold button ~15 sec)        |
| Blue   | solid      | BLE connected (unverified)                     |
| Orange | solid      | Zigbee connected (unverified)                  |
| No LED |            | Normal state, paired and sleeping (unverified) |

### Connect Module reset

1. Hold the reset button on the module for about 15 seconds.
2. Let go as soon as the orange LED blinks rapidly.
3. The module is now reset and ready to pair again.
4. Pairing mode lasts four minutes and starts when the module gets power. If it has run out, remove and reinsert the batteries with the inside and outside units connected.

### Lock factory reset

**A factory reset deletes all registered fingerprints, codes and key tags.** Settings are kept.

1. Take the inside unit off the door.
2. Connect the cable and insert batteries.
3. Turn the inside unit around so the back faces you.
4. Hold down the gold-colored reset button on the circuit board.
5. The lock confirms with a long beep and a green flash.
6. The factory code `123#` is back.

### Pairing with ZHA after reset

1. Reset the Connect Module (see above).
2. Right after, enter a PIN + `#` on the keypad to keep the radio awake.
3. Start "Add device" in ZHA within a few seconds.
4. The module should appear as `Onesti Products AS` with a model name.

PIN codes survive re-pairing the Connect Module, but a factory reset of the lock deletes them.

### Module not discovered during pairing

If the Connect Module never shows up in ZHA's "Add device", even after several attempts:

1. **Reset the module first.** After a Zigbee network change (HA moved to new hardware, a new coordinator, ZHA set up again without restoring the network backup), the module still holds the old network key and will not join the new network on its own. A reset clears it.
2. **Wait out pairing mode before resetting.** On some modules the reset button behaves differently while pairing mode is active. If you have just started pairing, wait about 4 minutes for it to time out, then hold reset.
3. After a successful reset, the module can take a few minutes to appear in ZHA discovery.

### Lock not offered when adding the integration

If the module is paired and visible in ZHA, but "Add integration" ends in "No devices found", the config flow found no device that met both of its criteria. The ZHA device manufacturer must be `Onesti Products AS`, and the device must expose a Door Lock cluster (0x0101). The model name is not checked, so a module reporting a sibling model such as `NimlyTwist` is still offered, and the log gets a warning naming the unknown model string.

Check the manufacturer and clusters in ZHA under Device info → Zigbee info. A device with the right manufacturer but no Door Lock cluster has usually not finished its interview. Re-interview it from the same page.

A lock that is already set up is also left out of the list, so an existing config entry is the other reason it can come back empty.

## 1. Zigbee connectivity

### Lock not responding (sleepy device)

These locks are battery-powered Zigbee EndDevices, and the radio sleeps most of the time to save battery. Messages queued at the parent router are thrown away after **7.68 seconds**.

These wake the Zigbee radio:

- Entering a complete PIN code + `#` on the keypad
- Physical lock/unlock (turning the knob)
- Lock/unlock command from HA (ZHA uses extended timeout)

Touching the keypad alone does NOT wake the radio. It wakes the backlight only.

### How auto-wake works

When a command times out or Zigbee reports that it could not be delivered, `ZhaLockTransport.send()` in `zha.py` wakes the lock with a `lock.lock` service call to ZHA's lock entity, waits 1 second for the radio to settle, and retries the original command once. The wake is a real lock command, so an unlocked door gets physically locked. Details in [docs/technical.md](technical.md#auto-wake-mechanism).

The wake needs ZHA's lock entity for the device to exist and be enabled. Without it the log says `No ZHA lock entity found for <ieee>, so the lock cannot be woken`, and the command is retried without a wake, which usually fails on a sleeping lock. Enable the lock entity under the device in ZHA.

### Signal issues

A metal door and a metal casing make a Faraday cage, and the Zigbee signal is heavily attenuated. What helps:

- Place a Zigbee router (e.g. a smart plug) within 2-3 meters of the lock
- Avoid multiple walls between the lock and coordinator
- Check LQI (link quality) in ZHA: **Settings → Devices → [lock] → Zigbee info**

### After battery change

After new batteries, the lock rejoins the Zigbee network, but the bindings may reset. Then:

- Attribute reporting (0x0100 events) stops
- `set_pin_code` consistently times out
- Lock/unlock still works (a simpler command with ZHA's extended timeout)
- Reconfigure in ZHA often fails (binding setup times out)

To fix it:

1. Try **Reconfigure** in ZHA (see below).
2. If that fails, wait hours or days for the bindings to come back on their own.
3. As a last resort, remove and re-pair the lock in ZHA.

### Reconfigure in ZHA

Reconfigure (Settings → Devices → [lock] → "Reconfigure device") sets up bindings and reporting again. On a sleepy device it often fails, because the device falls asleep halfway through. This raises the odds:

1. Enter a PIN + `#` on the keypad to wake the radio.
2. Click "Reconfigure" within 2-3 seconds.
3. Repeat if needed. The radio stays awake longer after an unlock than after just touching the keypad.
4. If it never succeeds, remove the device from ZHA and re-pair it.

## 2. PIN code failures

### "Slot must be between 3 and N"

`set_pin` refuses slots above what the lock reports in NumberOfPINUsersSupported. The highest slot is N-1, and NimlyPRO and NimlyCodePRO report 50. Until the lock has answered the capability read, 999 is the ceiling. The read is tried at startup and again whenever the lock is awake (after a command reaches it, or when it reports anything), so setting one PIN or unlocking the door once is usually enough. After the first answer the capabilities show up as attributes on the activity sensor, and the lock is not asked again.

The lower bound is the reserved-slots setting under Configure > Settings. The default of 3 fits Touch Pro, PRO and Code, which have master codes on 0-2. A Code Pro has only slot 0 as master, so set it to 1 there to use slots 1 and 2. Slot 0 is never written.

### "PIN code must be 4-8 digits"

The length range comes from the lock's reported MinPINCodeLength and MaxPINCodeLength. Until the lock has answered (see above), and for any value that makes no sense, 4-8 applies. A code shorter than 4 digits is never accepted, even if the lock reports a lower minimum, because the log masking only hides runs of 4 digits or more.

### "Slot number must be between 3 and 999"

Fixed after 1.3.0. The Name a user slot form used to refuse the master slots 0-2, so the master code could not have a name. It now takes any slot from 0 to 999, like `set_name`. Names never reach the lock.

### "Could not reach the lock" in Options flow

Both attempts in `ZhaLockTransport.send()` failed:

1. Attempt 1 timed out or was not delivered (the lock was asleep).
2. Auto-wake sent `lock.lock` to wake the radio.
3. Attempt 2 failed as well.

Any other Zigbee error fails at once, without a wake or a retry, and the log line names the error.

What to try:

- Enter a PIN + `#` on the keypad to wake the lock by hand.
- Retry within 5 seconds, while the radio is awake.
- Check that the ZHA lock entity works (lock/unlock from the dashboard). If that doesn't respond either, the problem is Zigbee connectivity, not the integration.

### IndexError quirk (Nimly response parsing)

PIN commands (`set_pin_code`, `clear_pin_code`) have raised `IndexError: tuple index out of range` when their response was read. The command reached the lock and was carried out; only reading the answer failed. The likely source is ZHA code reading `response[1]` on a Set PIN Code Response that carries a single field (see [technical.md](technical.md)), not a crash in zigpy's parser, and since commands now go to the zigpy cluster directly the error may not occur at all. That has not been tested on a real lock, so the handling stays.

The integration catches the error, logs it at debug level and treats it as success (`ZhaLockTransport.send()` in `zha.py`):

```python
except IndexError:
    # Nimly quirk: command was sent and received, but response
    # format is unexpected causing "tuple index out of range"
    # in zigpy response parsing. Command still reached the lock.
    _LOGGER.debug(
        "Nimly response quirk (IndexError) for command 0x%04x, "
        "command was sent successfully",
        command,
    )
    return True
```

With debug logging off, nothing about it shows up in the log.

Nothing confirms that the PIN was actually set, so you **must** test the code on the keypad.

### Verifying a PIN

After setting a PIN:

1. Go to the lock.
2. Enter the new code + `#`.
3. Check that the lock opens.
4. Check that the activity sensor in HA shows the right user and slot.

## 3. Activity sensor not updating

### attribute_report (attrid 0x0100) not received

The activity sensor depends on the lock sending attribute reports with attrid `0x0100` (Onesti's custom operation event). If the sensor never updates, start with the event listener. If it could not be registered, Home Assistant shows the repair issue below under Settings → Repairs. With debug logging on (section 4), a working setup logs this at startup, with the cluster's class name at the end:

```
Event listener registered on DoorLock
```

Next, check that attribute reports actually arrive. Set the integration's logger to `info` or `debug` (see section 4) and unlock the door. You should see:

```
Lock event: unlock by Kari via keypad (raw: 0x02020003)
```

If nothing is logged on unlock, the lock is not sending reports. See "After battery change" in section 1.

### Repair issue: Lock events are not being received

The integration could not find a part of ZHA it listens through. Setting PIN codes may still work, but the activity sensor and the `onesti_lock_activity` event stay silent. The issue names the missing part:

- **ZHA gateway (get_zha_gateway_proxy)**: ZHA was not running when the integration started. Check that ZHA is loaded under Settings → Devices & services. When ZHA comes up with the lock, the integration reloads by itself and the issue goes away. If ZHA runs normally and the issue stays, a Home Assistant update has most likely changed ZHA's internals.
- **Door Lock cluster for (address)**: ZHA runs, but the lock is not among its devices, or it has no Door Lock cluster. Check the device in ZHA, re-interview it if the cluster is missing (see "Lock not offered when adding the integration"), then reload Onesti Lock.
- **(class).on_event**: the Zigbee library no longer offers the hook the integration listens on. Nothing on your side fixes this.

For the first case when ZHA is running, and for the last case, open an issue on [GitHub](https://github.com/fredrik-lindseth/onesti-lock/issues) with your Home Assistant version and the text of the repair issue. The log has the same text on an error line starting `Lock events for`.

Versions before this repair issue logged only `ZHA not found` or `ZHA gateway_proxy not found`. Both meant what the first case means now: the integration could not reach ZHA's gateway.

### Slot 0 shows as Unknown

Fixed after 1.3.0. Earlier versions treated slot 0 as "no user" for every source, so a master code unlock showed as "Unknown unlocked with code". Slot 0 events from the keypad, fingerprint reader or key tag reader now carry the name set on slot 0, or "Master" if it has none. To name it, use Configure > Name a user slot with slot 0. Slot 0 with source zigbee, auto or unattributed still means no user.

### Auto-lock overwrites user events

In older versions, auto-lock events overwrote the ones that mattered, so "Kari unlocked with code" turned into "Auto-lock" 5 seconds later.

This is fixed. The activity sensor now ignores system-initiated locking, which is source `auto`, and on NimlyCodePRO an `unattributed` lock with no user slot. The HA event `onesti_lock_activity` still fires for every event, auto-lock included, so automations can use it.

Locking from Home Assistant does update the sensor, as "Locked via Zigbee". The one exception is the auto-wake before a PIN write, which also locks the door over Zigbee: a Zigbee lock within 30 seconds of a wake is taken as that echo and left out of the sensor. A dashboard lock inside the same 30 seconds is left out too. Whether 30 seconds fits every lock has not been measured, so if a PIN write on a sleeping lock still leaves "Locked via Zigbee" behind, report it with a debug log.

## 4. Debug logging

### Integration logging

Add to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.onesti_lock: debug
```

Restart HA. The log then shows:

- Event listener registration at startup
- All incoming operation events (attrid 0x0100) with raw values
- Auto-wake attempts and results
- A Zigbee lock taken as the echo of the auto-wake
- The Nimly response quirk (IndexError) when it occurs
- Cluster lookup errors

Error messages from the send path have every run of 4 or more digits replaced with `****`, so a PIN code in an error does not reach the log from this integration.

### Zigpy/ZHA debug logging for raw Zigbee traffic

To see every raw Zigbee frame, which helps when you suspect the lock is not sending reports:

```yaml
logger:
  default: warning
  logs:
    custom_components.onesti_lock: debug
    zigpy.zcl: debug
    homeassistant.components.zha: debug
```

`zigpy.zcl: debug` writes a lot of log data. Turn it on while troubleshooting and off again afterwards.

### PIN codes appear in raw logs and diagnostics

`zigpy.zcl: debug` prints raw ZCL frames, and frames for attribute 0x0101 on the DoorLock cluster carry the last used PIN in plaintext. The same goes for ZHA's "Download diagnostics" on the device, which dumps zigpy's attribute cache including the last reported 0x0101 value.

Scrub those values before pasting a log or a diagnostics file into a GitHub issue or a forum post. If you already shared one, change the codes on the lock.

### What to look for in the log

**Successful operation event:**

```
Lock event: unlock by Kari via keypad (raw: 0x02020003)
```

The raw value is a bitmap32: `0x02020003` → source=0x02 (keypad), action=0x02 (unlock), slot=3.

**Auto-wake sequence:**

```
TimeoutError on attempt 1 for command 0x0005, waking lock and retrying
Waking lock via lock.onesti_products_as_nimlypro_door_lock
```

The first line says `DeliveryError` when Zigbee reported the frame as undelivered. The entity in the second line is ZHA's lock entity, so its id follows ZHA's naming, not this integration's.

**Failed command:**

```
TimeoutError sending command 0x0005 to f4:ce:36:... after wake and retry, lock may be unreachable: ...
```

**Nimly response quirk:**

```
Nimly response quirk (IndexError) for command 0x0005, command was sent successfully
```

**Event listener not registered:**

```
Lock events for f4:ce:36:... cannot be received, ZHA internals missing: ZHA gateway (get_zha_gateway_proxy). Report the Home Assistant version in an issue if ZHA itself is running
```

It comes with the repair issue described in section 3, and usually after one of these:

```
ZHA has no running gateway, so the lock cannot be reached
Door Lock cluster not found for f4:ce:36:...
```

Older versions logged `ZHA not found` and `ZHA gateway_proxy not found` in the same situation.

**Raw attribute report from zigpy (with `zigpy.zcl: debug`):**

zigpy logs every incoming frame twice, first raw (`Received ZCL frame: ...`) and then decoded. The decoded line for an operation event looks like this, with the exact repr depending on the zigpy version:

```
[0x...:11:0x0101] Decoded ZCL frame: DoorLock:Report_Attributes(attribute_reports=[Attribute(attrid=0x0100, ...)])
```

If you see reports with `attrid=0x0000` (lock state) but none with `attrid=0x0100` (operation event), the lock has lost its reporting configuration. Try Reconfigure.

## 5. Common ZHA issues

### Device shows as "unavailable"

- **Battery:** check the battery level. A low battery means fewer reports and more command timeouts.
- **Signal:** the lock is too far from the nearest Zigbee router. Move a router closer.
- **After a battery change:** the lock may have rejoined but lost its bindings. See section 1.

If Reconfigure fails repeatedly, follow "Reconfigure in ZHA" in section 1.

### Tips for stable operation

- **Put a Zigbee router near the lock.** A smart plug that works as a Zigbee router, 1-3 meters from the door, makes an enormous difference for sleepy devices.
- **Don't move the coordinator.** The Zigbee network takes time to find new routes after the topology changes.
- **Do not wait for a Zigbee firmware update.** The module lists the OTA Upgrade cluster, but no image for it exists in the community zigbee-OTA index, so ZHA has nothing to offer. Whether the vendor's BLE app can update the firmware has not been checked.
- **Keep an eye on the battery.** An automation that warns about low battery lets you avoid the problems that come with a battery change.

## 6. Cleanup after versions 1.1.0 through 1.2.0

Versions 1.1.0 through 1.2.0 published a `last_pin_code` attribute on `sensor.*_siste_aktivitet`. Attribute 0x0101 is the PIN itself, not an opaque id, so real access codes ended up in the recorder database. The attribute is gone now, but old values stay in the database until they are purged.

Purge the history for the activity sensor:

```yaml
service: recorder.purge_entities
target:
  entity_id: sensor.NAME_siste_aktivitet
data:
  keep_days: 0
```

This deletes all history for that entity, not only the PIN attribute. There is no way to purge a single attribute.

Purging does not reach everything. zigpy keeps the last reported 0x0101 value in its own `zigbee.db` attribute cache, and ZHA diagnostics dumps that cache whatever this integration does. If a diagnostics file or a zigpy debug log has been shared publicly, the only reliable cleanup is to change the codes on the lock.
