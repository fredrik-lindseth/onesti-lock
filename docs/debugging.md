# Debugging guide

Practical guide for diagnosing common issues with the Onesti Lock integration.

## LED indicators and sounds

Source: [Nimly Touch Pro Manual](https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf)

### Keypad (outside unit)

| Indicator | Meaning |
|-----------|---------|
| **Green flash + short beep** | Success (unlock, registration, programming) |
| **Red flash** | Failure (wrong code, timeout, registration failed) |
| **Long beep + green flash** | Successful factory reset |
| **Repeated frequent beeps on locking** | Low battery — replace batteries soon |
| **White backlit keypad** | Keypad woken (touch), ready for input |

**Anti-tamper:** Three wrong codes in a row disables the keypad for 5 minutes.

**Camouflage function:** You can enter false digits before and after the real code. For example, `21345681#` where the real code is `3456`.

### Sound volume

Configurable via master code (programming sequence `#0`):

| Value | Level |
|-------|-------|
| 0 | Silent |
| 1 | Low |
| 2 | Normal (default) |

### Connect Module LED (E-Life 3.0 / ZMNC010)

| LED | Pattern | Meaning |
|-----|---------|---------|
| **Blue** slow blink | BLE pairing mode (searching) |
| **Orange** slow blink | Zigbee pairing mode (searching) |
| **Orange** fast blink | Reset in progress (hold button ~15 sec) |
| **Blue** solid | BLE connected |
| **Orange** solid | Zigbee connected |
| No LED | Normal state (paired and sleeping) |

### Connect Module reset

1. Hold the **reset button** on the module for **15 seconds**
2. Release when the orange LED blinks rapidly
3. Module is reset and ready for new pairing
4. Enters pairing mode automatically for 4 minutes after reset

### Lock factory reset

**Deletes all registered fingerprints, codes and key tags.** Settings are preserved.

1. Remove the inside unit from the door
2. Connect the cable and insert batteries
3. Turn the inside unit around with the back facing you
4. Hold down the **gold-colored reset button** on the circuit board
5. Lock confirms with **long beep + green flash**
6. Factory code `123#` is restored

### Pairing with ZHA after reset

1. Reset the Connect Module (see above)
2. Enter a PIN + `#` on the keypad right after (keeps the radio awake)
3. Start "Add device" in ZHA within a few seconds
4. Module should appear as `Onesti Products AS` with model name

**Note:** PIN codes survive Connect Module re-pairing, but are deleted by lock factory reset.

## 1. Zigbee connectivity

### Lock not responding (sleepy device)

These locks are battery-powered Zigbee EndDevices. The radio sleeps most of the time to save battery. Messages queued at the parent router are discarded after **7.68 seconds**.

**What wakes the Zigbee radio:**
- Entering a complete PIN code + `#` on the keypad
- Physical lock/unlock (turning the knob)
- Lock/unlock command from HA (ZHA uses extended timeout)

**What does NOT wake the radio:**
- Touching the keypad alone (wakes the backlight, but not the Zigbee radio)

### How auto-wake works

The integration has a built-in wake mechanism in `coordinator.py` (`_send_cluster_command`):

1. **Attempt 1:** Sends ZCL command via `zha.issue_zigbee_cluster_command`
2. **On timeout:** Calls `_wake_lock()` — sends `lock.lock` service call to the ZHA lock entity
3. **Waits 1 second** for the radio to stabilize
4. **Attempt 2:** Retries the original command

### Signal issues

Metal door and metal casing = Faraday cage. Zigbee signal is heavily attenuated.

**Mitigations:**
- Place a Zigbee router (e.g. a smart plug) within 2-3 meters of the lock
- Avoid multiple walls between the lock and coordinator
- Check LQI (link quality) in ZHA: **Settings → Devices → [lock] → Zigbee info**

### After battery change

When batteries are replaced, the lock re-joins the Zigbee network but bindings may reset:

- Attribute reporting (0x0100 events) stops
- `set_pin_code` consistently times out
- Lock/unlock still works (simpler command with ZHA's extended timeout)
- Reconfigure in ZHA often fails (binding setup times out)

**Solutions:**
1. Try **Reconfigure** in ZHA (see below)
2. If that fails: wait hours/days for bindings to re-establish on their own
3. Last resort: remove and re-pair the lock in ZHA

### Reconfigure in ZHA

Reconfigure (Settings → Devices → [lock] → "Reconfigure device") re-establishes bindings and reporting configuration. For sleepy devices this often fails because the device falls asleep during the process.

**Tips for success:**
1. Enter a PIN + `#` on the keypad (wakes the radio)
2. Click "Reconfigure" within 2-3 seconds
3. Repeat if needed — the radio stays awake longer after an unlock than after just touching the keypad
4. If it never succeeds: remove the device from ZHA and re-pair

## 2. PIN code failures

### "Could not reach the lock" in Options flow

This error means both attempts in `_send_cluster_command` failed:

1. Attempt 1 timed out (lock was asleep)
2. Auto-wake sent `lock.lock` to wake the radio
3. Attempt 2 also timed out

**Troubleshooting:**
- Press a PIN + `#` on the keypad to manually wake the lock
- Retry within 5 seconds (while the radio is awake)
- Check that the ZHA lock entity works (lock/unlock via Lovelace). If it also doesn't respond, the problem is Zigbee connectivity, not the integration.

### IndexError quirk (Nimly response parsing)

PIN commands (`set_pin_code`, `clear_pin_code`) return a malformed ZCL response that crashes zigpy's parser with `IndexError: tuple index out of range`. The command reached the lock and executed — the error is only in response parsing.

The integration catches this and treats it as success:

```python
except IndexError:
    # Nimly quirk: command was sent and received, but response
    # format is unexpected causing "tuple index out of range"
    # in zigpy response parsing. Command still reached the lock.
    return True
```

**Important:** There is no programmatic confirmation that the PIN was actually set. You **must** test the code on the keypad to verify.

### Verifying a PIN

After setting a PIN:

1. Go to the lock physically
2. Enter the new code + `#`
3. Check that the lock opens
4. Check the activity sensor in HA — it should show the correct user and slot

## 3. Activity sensor not updating

### attribute_report (attrid 0x0100) not received

The activity sensor depends on the lock sending attribute reports with attrid `0x0100` (Onesti custom operation event). If the sensor never updates:

**Check that the event listener is registered.** In the log at startup you should see:

```
Event listener registered on DoorLock (events: ['attribute_report'])
```

If you see `Could not find DoorLock cluster for event listener`, the integration couldn't find the cluster. Try reloading the integration (Settings → Integrations → Onesti Lock → Reload).

**Check that attribute reports are actually coming.** Enable debug logging (see section 4) and perform an unlock. You should see:

```
Lock event: unlock by Kari via keypad (raw: 0x02020003)
```

If nothing is logged on unlock: the lock is not sending reports. See "After battery change" in section 1.

### Auto-lock overwrites user events

Older versions of the integration let auto-lock events overwrite meaningful events. For example: "Kari unlocked with code" was immediately replaced by "Auto-lock" 5 seconds later.

This is fixed — `source != "auto"` filters auto-lock from the activity sensor:

```python
if decoded["source"] != "auto":
    coordinator.update_activity(...)
```

The HA event `onesti_lock_activity` still fires for all events including auto-lock, so automations can use it.

## 4. Debug logging

### Integration logging

Add to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.onesti_lock: debug
```

Restart HA. You will see:

- Event listener registration at startup
- All incoming operation events (attrid 0x0100) with raw values
- Auto-wake attempts and results
- Nimly response quirk (IndexError) when they occur
- Cluster lookup errors

### Zigpy/ZHA debug logging for raw Zigbee traffic

To see all raw Zigbee frames (useful when you suspect reports are not being sent):

```yaml
logger:
  default: warning
  logs:
    custom_components.onesti_lock: debug
    zigpy.zcl: debug
    homeassistant.components.zha: debug
```

**Warning:** `zigpy.zcl: debug` generates a lot of log data. Use it only for troubleshooting, not permanently.

### What to look for in the log

**Successful operation event:**

```
Lock event: unlock by Kari via keypad (raw: 0x02020003)
```

The raw value is decoded as (bitmap32): `0x02020003` → source=0x02 (keypad), action=0x02 (unlock), slot=3

**Auto-wake sequence:**

```
Timeout on attempt 1 for command 0x0005 — waking lock and retrying
Waking lock via lock.onesti_lock_nimly_pro_...
```

**Failed command:**

```
Timeout sending command 0x0005 to f4:ce:36:... after wake+retry — lock may be unreachable
```

**Nimly response quirk:**

```
Nimly response quirk (IndexError) for command 0x0005 — command was sent successfully
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

If you see reports for `0x0000` (lock state) but not `0x0100` (operation event), the lock has lost its reporting configuration — try Reconfigure.

## 5. Common ZHA issues

### Device shows as "unavailable"

- **Battery:** Check battery level. Low battery means less frequent reports and more command timeouts.
- **Signal:** Lock is too far from the nearest Zigbee router. Place a router closer.
- **After battery change:** The lock may have re-joined but lost bindings. See section 1.

### Reconfigure fails repeatedly

The lock falls asleep too quickly for Reconfigure to complete the binding setup.

**Approach:**
1. Enter PIN + `#` to wake the lock
2. Start Reconfigure immediately (within 2-3 seconds)
3. Repeat if needed — the radio stays awake longer after an unlock
4. If it never succeeds: remove the device from ZHA and re-pair

### Tips for stable operation

- **Zigbee router near the lock.** A smart plug with Zigbee router function 1-3 meters from the door makes an enormous difference for sleepy devices.
- **Don't move the coordinator.** The Zigbee network takes time to re-route after topology changes.
- **Keep firmware updated.** ZHA supports OTA for some devices, but Onesti/Nimly locks do not have OTA via Zigbee — firmware is only updated via the BLE app.
- **Monitor battery level.** Create an automation that alerts on low battery to avoid the problems that occur during battery replacement.
