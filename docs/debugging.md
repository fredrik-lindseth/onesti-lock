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

Three wrong codes in a row disable the keypad for 5 minutes (anti-tamper).

The camouflage function lets you type false digits before and after the real code, so `21345681#` works when the real code is `3456`.

### Sound volume

Set with the master code (programming sequence `#0`):

| Value | Level            |
| ----- | ---------------- |
| 0     | Silent           |
| 1     | Low              |
| 2     | Normal (default) |

### Connect Module LED (E-Life 3.0 / ZMNC010)

| LED    | Pattern    | Meaning                                 |
| ------ | ---------- | --------------------------------------- |
| Blue   | slow blink | BLE pairing mode (searching)            |
| Orange | slow blink | Zigbee pairing mode (searching)         |
| Orange | fast blink | Reset in progress (hold button ~15 sec) |
| Blue   | solid      | BLE connected                           |
| Orange | solid      | Zigbee connected                        |
| No LED |            | Normal state (paired and sleeping)      |

### Connect Module reset

1. Hold the reset button on the module for 15 seconds.
2. Let go when the orange LED blinks rapidly.
3. The module is now reset and ready to pair again.
4. It goes into pairing mode on its own for 4 minutes after the reset.

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

When a command times out, `_send_cluster_command` in `coordinator.py` wakes the lock with a `lock.lock` service call to the ZHA lock entity, waits 1 second for the radio to settle, and retries the original command once. The wake is a real lock command, so an unlocked door gets physically locked. Details in [docs/technical.md](technical.md#auto-wake-mechanism).

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

`set_pin` refuses slots above what the lock reports in NumberOfPINUsersSupported. The highest slot is N-1, and NimlyPRO and NimlyCodePRO report 50. If the lock never answered the capability read, 999 is the ceiling.

The lower bound is the reserved-slots setting under Configure > Settings. The default of 3 fits Touch Pro, PRO and Code, which have master codes on 0-2. A Code Pro has only slot 0 as master, so set it to 1 there to use slots 1 and 2. Slot 0 is never written.

### "Slot number must be between 3 and 999"

Fixed after 1.3.0. The Name a user slot form used to refuse the master slots 0-2, so the master code could not have a name. It now takes any slot from 0 to 999, like `set_name`. Names never reach the lock.

### "Could not reach the lock" in Options flow

Both attempts in `_send_cluster_command` failed:

1. Attempt 1 timed out (the lock was asleep).
2. Auto-wake sent `lock.lock` to wake the radio.
3. Attempt 2 timed out as well.

What to try:

- Enter a PIN + `#` on the keypad to wake the lock by hand.
- Retry within 5 seconds, while the radio is awake.
- Check that the ZHA lock entity works (lock/unlock from the dashboard). If that doesn't respond either, the problem is Zigbee connectivity, not the integration.

### IndexError quirk (Nimly response parsing)

PIN commands (`set_pin_code`, `clear_pin_code`) get a malformed ZCL response back, and zigpy's parser crashes on it with `IndexError: tuple index out of range`. The command reached the lock and was carried out. Only the response parsing fails.

The integration catches the error, logs it at debug level and treats it as success (`_send_cluster_command` in `coordinator.py`):

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

The activity sensor depends on the lock sending attribute reports with attrid `0x0100` (Onesti's custom operation event). If the sensor never updates, start with the event listener. At startup the log should say:

```
Event listener registered on DoorLock (events: ['attribute_report'])
```

`Could not find DoorLock cluster for event listener` means the integration did not find the cluster. Try reloading the integration (Settings → Integrations → Onesti Lock → Reload).

Next, check that attribute reports actually arrive. Turn on debug logging (see section 4) and unlock the door. You should see:

```
Lock event: unlock by Kari via keypad (raw: 0x02020003)
```

If nothing is logged on unlock, the lock is not sending reports. See "After battery change" in section 1.

### Slot 0 shows as Unknown

Fixed after 1.3.0. Earlier versions treated slot 0 as "no user" for every source, so a master code unlock showed as "Unknown unlocked with code". Slot 0 events from the keypad, fingerprint reader or key tag reader now carry the name set on slot 0, or "Master" if it has none. To name it, use Configure > Name a user slot with slot 0. Slot 0 with source zigbee, auto or unattributed still means no user.

### Auto-lock overwrites user events

In older versions, auto-lock events overwrote the ones that mattered, so "Kari unlocked with code" turned into "Auto-lock" 5 seconds later.

This is fixed. The activity sensor now ignores system-initiated locking, which is source `auto`, and on NimlyCodePRO an `unattributed` lock with no user slot. The HA event `onesti_lock_activity` still fires for every event, auto-lock included, so automations can use it.

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
- The Nimly response quirk (IndexError) when it occurs
- Cluster lookup errors

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
Timeout on attempt 1 for command 0x0005, waking lock and retrying
Waking lock via lock.onesti_lock_nimly_pro_...
```

**Failed command:**

```
Timeout sending command 0x0005 to f4:ce:36:... after wake+retry; lock may be unreachable
```

**Nimly response quirk:**

```
Nimly response quirk (IndexError) for command 0x0005, command was sent successfully
```

**Event listener not registered:**

```
Could not find DoorLock cluster for event listener
```

or:

```
ZHA not found
ZHA gateway_proxy not found
```

**Raw attribute report from zigpy (with `zigpy.zcl: debug`):**

```
[0x...] DoorLock: Received report for attr 0x0100: <bitmap32 value>
```

If you see reports for `0x0000` (lock state) but not `0x0100` (operation event), the lock has lost its reporting configuration. Try Reconfigure.

## 5. Common ZHA issues

### Device shows as "unavailable"

- **Battery:** check the battery level. A low battery means fewer reports and more command timeouts.
- **Signal:** the lock is too far from the nearest Zigbee router. Move a router closer.
- **After a battery change:** the lock may have rejoined but lost its bindings. See section 1.

If Reconfigure fails repeatedly, follow "Reconfigure in ZHA" in section 1.

### Tips for stable operation

- **Put a Zigbee router near the lock.** A smart plug that works as a Zigbee router, 1-3 meters from the door, makes an enormous difference for sleepy devices.
- **Don't move the coordinator.** The Zigbee network takes time to find new routes after the topology changes.
- **Keep the firmware updated.** ZHA supports OTA for some devices, but Onesti/Nimly locks have no OTA over Zigbee. The firmware can only be updated from the BLE app.
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
