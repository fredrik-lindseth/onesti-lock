# Debugging guide

The usual problems, each with symptom, cause and fix. The ones people run into most:

- Setup says no lock was found: [Lock not offered when adding the integration](#lock-not-offered-when-adding-the-integration).
- The lock will not pair with ZHA: [Module not discovered during pairing](#module-not-discovered-during-pairing).
- Setting a PIN fails with "Could not reach the lock": [the lock is asleep or out of range](#could-not-reach-the-lock-in-options-flow).
- The lock keeps going unavailable, or commands time out at random: [Signal issues](#signal-issues).
- The activity sensor stopped changing, often after new batteries: [Activity sensor not updating](#3-activity-sensor-not-updating).
- A repair issue says lock events are not being received: [Repair issue](#repair-issue-lock-events-are-not-being-received).

If none of that helps, turn on [debug logging](#4-debug-logging) and open an [issue](https://github.com/fredrik-lindseth/onesti-lock/issues). The log can contain PIN codes, so read [PIN codes appear in raw logs and diagnostics](#pin-codes-appear-in-raw-logs-and-diagnostics) before you paste it.

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

With anti-tamper on (programming sequence `#2`, master code, `#1`), three wrong codes in a row disable the keypad for 5 minutes. The manual does not say whether it is on from the factory.

The camouflage function lets you type false digits before and after the real code, so `21345681#` works when the real code is `3456`.

### Sound volume

Set with the master code (programming sequence `#0`):

| Value | Level            |
| ----- | ---------------- |
| 0     | Silent           |
| 1     | Low              |
| 2     | Normal (default) |

### Connect Module LED (E-Life 3.0 / ZMNC010)

The flashing and reset rows come from the Connect Module installation guides (2022 through 2026 editions, `docs/manuals/README.md`). The solid rows come from Copiax's 2022 edition of the same guide, which says a successful pairing shows as solid light on the blue (BLE) or orange (Zigbee) LED. Nobody has checked any row against a module, and the no-LED row is in no manual.

| LED    | Pattern    | Meaning                                                   |
| ------ | ---------- | --------------------------------------------------------- |
| Blue   | flashing   | Pairing mode, Bluetooth side (four minutes after power-on) |
| Orange | flashing   | Pairing mode, Zigbee side (same window)                    |
| Orange | fast blink | Reset in progress (hold button ~15 sec)                    |
| Blue   | solid      | Paired over BLE (Copiax guide, unverified)                 |
| Orange | solid      | Paired over Zigbee (Copiax guide, unverified)              |
| No LED |            | Normal state, paired and sleeping (guess)                  |

Every edition of the guide since 2022 describes both colours in pairing mode, and the 2024 and 2026 editions add in a footnote that Bluetooth is only on newer versions of the module, without saying which; a user relaying EasyAccess support in August 2022 was told the Bluetooth part was still under development ([community-reports.md](community-reports.md#bluetooth)). So a blue blink in the guide is generic text and does not prove a particular module has a working Bluetooth radio. Seeing it blink on the module in front of you does.

### Connect Module reset

1. Hold the reset button on the module for about 15 seconds.
2. Let go as soon as the orange LED blinks rapidly.
3. The module is reset and ready to pair again.
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

PIN codes survive re-pairing the Connect Module. A factory reset of the lock deletes them.

### Module not discovered during pairing

If the module never shows up in ZHA's "Add device", even after several attempts:

1. Reset the module first. After a Zigbee network change (HA moved to new hardware, a new coordinator, ZHA set up again without restoring the network backup), the module still holds the old network key and will not join the new network on its own.
2. Wait out pairing mode before resetting. On some modules the reset button behaves differently while pairing mode is active. If you have just started pairing, wait about 4 minutes for it to time out, then hold reset.
3. After a successful reset, the module can take a few minutes to appear in ZHA discovery.

### Lock not offered when adding the integration

If the module is paired and visible in ZHA but "Add integration" ends in "No devices found", no device met both criteria: manufacturer `Onesti Products AS` and a Door Lock cluster (0x0101). The model name is not checked, so a module reporting a sibling model such as `NimlyTwist` is still offered, with a warning in the log naming the unknown string.

Check manufacturer and clusters in ZHA under Device info → Zigbee info. A device with the right manufacturer but no Door Lock cluster has usually not finished its interview. Re-interview it from the same page.

A lock that is already set up is left out of the list too, so an existing config entry is the other reason it comes back empty.

## 1. Zigbee connectivity

### Lock not responding (sleepy device)

These locks are battery-powered Zigbee EndDevices, and the radio sleeps most of the time. Messages queued at the parent router are thrown away after **7.68 seconds**.

What wakes the radio:

- A complete PIN code + `#` on the keypad, which also unlocks the door
- Turning the knob
- A lock/unlock command from HA (ZHA uses an extended timeout)

Touching the keypad alone wakes the backlight, not the radio.

### How auto-wake works

When a command times out or Zigbee reports it undelivered, `ZhaLockTransport.send()` in `zha.py` wakes the lock with a `lock.lock` call to ZHA's lock entity, waits 1 second for the radio to settle, and retries once. The wake is a real lock command, so an unlocked door gets locked. Details in [technical.md](technical.md#auto-wake-mechanism).

The wake needs ZHA's lock entity for the device to exist and be enabled. Without it the log says `No ZHA lock entity found for <ieee>, so the lock cannot be woken`, and the retry runs without a wake, which usually fails on a sleeping lock. Enable the lock entity under the device in ZHA.

### Signal issues

Most unexplained flakiness on these locks is coverage. The radio is inside an aluminium lock body on the outermost point of the house, with no external antenna, and it sleeps, so it cannot route and lives off the nearest mains-powered node. 2.4 GHz is also the Wi-Fi band. There is no transmit-power setting, no antenna connector and no firmware knob on the lock; everything you can change is on your side of the door.

To see whether it is bad, enable the RSSI and LQI sensors under the device in ZHA (diagnostic entities, off by default) and let them record for a few days:

| | Reading | Verdict |
| --- | --- | --- |
| RSSI | above -60 dBm | as good as this lock gets |
| | -60 to -75 dBm | workable |
| | below -80 dBm | expect timeouts and missed reports |
| LQI | 150 and up | fine |
| | 100 to 150 | works, with dropouts |
| | below 100 | the lock will go unavailable |

The bands come from one door with 13 months of hourly statistics, and from the LQI values owners quote in the Home Assistant thread, 116 to 196 and no higher. Both numbers are the coordinator's measurement of the last hop, not of the lock's own transmission, so with a router by the door they partly describe that router.

That one door: a NimlyPRO with a Connect Module in an entry hall, on ZHA with a Home Assistant Connect ZBT-2, 8830 hours of recorder statistics. Getting it stable meant moving the 2.4 GHz Wi-Fi off the Zigbee channel, adding mains-powered Zigbee routers, and putting one in the entry hall itself.

| | Before | After |
| --- | --- | --- |
| Hours recorded | 2409 | 6421 |
| Median RSSI | -76 dBm | -61 dBm |
| 5th percentile RSSI | -87 dBm | -73 dBm |
| Median LQI | 139 | 156 |
| Hours with a sample at or below -90 dBm | 187 (7.8 %) | 36 (0.6 %) |

Roughly 15 dB, most of a factor of thirty in received power, from mains sockets and a channel plan. Nothing about the lock changed.

The floor is still bad. The worst sample in the 13 months is -107 dBm, LQI has read 0 in 14 separate hours, and the lock has gone silent for 431 hours in one stretch and 117 in another. The only other Zigbee device on that network with recorded history over the last 90 days, an Aqara sensor in a bathroom, averages -78 dBm against the lock's -60, so after the work the lock is no longer the worst link in the house. It took the most work to get there.

That is one door, possibly a bad house: the same thread has an owner with three locks and no trouble. Whether a newer module revision has a better radio or antenna placement is unknown. Nobody outside the vendor has published a board photo at chip level, and users tell the generations apart only by behaviour.

What helps, in order:

1. A mains-powered Zigbee router within a few metres of the door, on the inside. This is the fix every owner who solved it ended up with. A smart plug or a dedicated repeater; a battery-powered device is not a router. Bulbs route, but owners report them as poor at it, and a bulb switched off at the wall stops routing.
2. Move the Wi-Fi, not the Zigbee. Zigbee 15, 20 and 25 sit in the gaps between Wi-Fi channels 1, 6 and 11. Pick the Zigbee channel first, put your 2.4 GHz Wi-Fi where it does not land on top, and fix the Wi-Fi channel rather than leaving it on auto. Changing the Zigbee channel on a running network is worse: sleeping end devices often do not follow and have to be re-paired, the lock among them.
3. Give the coordinator a fair chance. An external antenna beats a bare USB stick, a USB extension cable beats a socket on the back of the server, and USB 3 ports and cables are loud on 2.4 GHz. Do not move the coordinator once things work; the mesh takes days to settle again.
4. Wait, and check who the parent is. The lock does not re-parent promptly. Owners report adding a repeater and seeing the lock keep talking to a distant coordinator for days before moving across on its own, with no way to force it. If it never moves, reset the Connect Module and pair it again with the new router powered and the coordinator further away.

What does not help: raising the coordinator's transmit power (it changes the downlink, not the lock's uplink), and replacing the Connect Module unless it is faulty.

[community-reports.md](community-reports.md#range-and-coverage) has what other owners measured and tried.

### After battery change

After new batteries the lock rejoins the network, but the bindings may reset. Then attribute reporting (0x0100 events) stops, `set_pin_code` times out every time, lock/unlock still works (a simpler command with ZHA's extended timeout), and Reconfigure in ZHA often fails because the binding setup times out.

1. Try **Reconfigure** in ZHA (see below).
2. If that fails, wait hours or days for the bindings to come back on their own.
3. As a last resort, remove and re-pair the lock in ZHA.

Reconfigure can restore lock/unlock reporting (`lock_state`) while the operation events (`0x0100`) stay silent for a while. Seen after a re-pair: `lock_state` and capability reads came back at once, but keypad lock and unlock produced no `0x0100` report for some time. Give the bindings time, or reconfigure again with the lock awake. `set_pin` and `clear_pin` work before the events do, since they do not depend on reporting.

### The lock says it locked, but the bolt does not move

A `lock` command can return success while the bolt stays put: the log shows `lock_door_response(status=SUCCESS)` and Home Assistant shows locked, but nothing moves. The firmware acknowledged the command; the motor or the mechanics did not carry it out. This is a hardware or mounting problem: the lock is usually not fully seated in the mortise, the door is not aligned, or the lock needs to relearn its direction after a reset. Try the thumbturn by hand, and check that the lock body is seated and screwed down.

### Reconfigure in ZHA

Reconfigure (Settings → Devices → [lock] → "Reconfigure device") sets up bindings and reporting again. On a sleepy device it often fails halfway. To raise the odds:

1. Enter a PIN + `#` on the keypad to wake the radio.
2. Click "Reconfigure" within 2-3 seconds.
3. Repeat if needed. The radio stays awake longer after an unlock than after touching the keypad.
4. If it never succeeds, remove the device from ZHA and re-pair it.

## 2. PIN code failures

### "Slot must be between 3 and N"

`set_pin` refuses slots above what the lock reports in NumberOfPINUsersSupported. The highest slot is N-1; NimlyPRO and NimlyCodePRO report 50. Until the lock has answered the capability read, 999 is the ceiling. The read is tried at startup and whenever the lock is awake (after a command reaches it, or when it reports anything), so setting one PIN or unlocking the door once is usually enough. After the first answer the lock is not asked again.

The lower bound is the reserved-slots setting under Configure > Settings. The default of 3 fits Touch Pro, PRO and Code, which have master codes on 0-2. A Code Pro has only slot 0 as master, so set it to 1 there. Slot 0 is never written.

### "PIN code must be 4-8 digits"

The range comes from the lock's MinPINCodeLength and MaxPINCodeLength. Until the lock has answered (see above), and for any value that makes no sense, 4-8 applies. A code shorter than 4 digits is never accepted, whatever the lock reports, because the log masking only hides runs of 4 digits or more.

### "Slot number must be between 3 and 999"

Fixed after 1.3.0. The Name a user slot form used to refuse the master slots 0-2, so the master code could not have a name. It now takes any slot from 0 to 999, like `set_name`. Names never reach the lock.

### "Could not reach the lock" in Options flow

Both attempts in `ZhaLockTransport.send()` failed: the first timed out or was not delivered (the lock was asleep), auto-wake sent `lock.lock`, and the second failed too. Any other Zigbee error fails at once, without a wake or a retry, and the log line names the error.

- Wake the lock by hand: turn the knob, or enter a PIN + `#`, which also unlocks the door.
- Retry within 5 seconds, while the radio is awake.
- Check that ZHA's lock entity works from the dashboard. If that does not respond either, the problem is Zigbee connectivity.

### IndexError quirk (Nimly response parsing)

PIN commands have raised `IndexError: tuple index out of range` when their response was read. The command reached the lock and was carried out; only reading the answer failed. The likely source is ZHA reading `response[1]` on a Set PIN Code Response that has a single field (see [technical.md](technical.md#nimly-response-quirk)), and since commands now go to the zigpy cluster directly the error may not occur at all. That has not been tested on a real lock, so `send()` still catches it, logs it at debug level and treats the command as sent. With debug logging off, nothing about it appears in the log.

Nothing confirms that the PIN was set, so test the code on the keypad: enter it with `#`, check that the lock opens, and check that the activity sensor shows the right user and slot.

## 3. Activity sensor not updating

### attribute_report (attrid 0x0100) not received

The activity sensor depends on the lock sending attribute reports with attrid `0x0100`. If it never updates, start with the event listener. If it could not be registered, Home Assistant shows the repair issue below. With debug logging on (section 4), a working setup logs this at startup, with the cluster's class name and the hook it listens through:

```
Event listener registered on DoorLock via add_listener
```

`via on_event` is equally fine: which one is used depends on the Zigbee library version in your Home Assistant, and both deliver the same events.

Next, check that reports arrive. With the integration's logger at `info` or `debug` (section 4), unlock the door. You should see:

```
Lock event: unlock by Kari via keypad (raw: 0x02020003)
```

If nothing is logged on unlock, the lock is not sending reports. See "After battery change" in section 1.

### Repair issue: Lock events are not being received

The integration could not find a part of ZHA it listens through. Setting PIN codes may still work, but the activity sensor and the event stay silent. The issue names the missing part:

- **ZHA gateway (get_zha_gateway_proxy)**: ZHA was not running when the integration started. Check that ZHA is loaded under Settings → Devices & services. When ZHA comes up with the lock, the integration reloads by itself and the issue goes away. If ZHA runs normally and the issue stays, a Home Assistant update has most likely changed ZHA's internals.
- **Door Lock cluster for (address)**: ZHA runs, but the lock is not among its devices or has no Door Lock cluster. Check the device in ZHA, re-interview it if the cluster is missing (see "Lock not offered when adding the integration"), then reload Onesti Lock.
- **(class).on_event, and no add_listener/remove_listener either**: the Zigbee library offers neither of the two hooks the integration can listen on. No zigpy release in use does this, so a Home Assistant update changed the library. Nothing on your side fixes it.

For the first case with ZHA running, and for the last, open an [issue](https://github.com/fredrik-lindseth/onesti-lock/issues) with your Home Assistant version and the text of the repair issue. The log has the same text on an error line starting `Lock events for`. Versions before this repair issue logged only `ZHA not found` or `ZHA gateway_proxy not found`, which meant the first case.

### Slot 0 shows as Unknown

Fixed after 1.3.0. Earlier versions treated slot 0 as "no user" for every source, so a master code unlock showed as "Unknown unlocked with code". Slot 0 events from the keypad, fingerprint reader or key tag reader now carry the name set on slot 0, or "Master" without one. Name it under Configure > Name a user slot with slot 0. Slot 0 with source zigbee, auto or unattributed still means no user.

### Auto-lock overwrites user events

Fixed. Older versions let auto-lock overwrite "Kari unlocked with code" with "Auto-lock" 5 seconds later. The activity sensor now ignores system-initiated locking, which is source `auto`, and on NimlyCodePRO an `unattributed` lock with no user slot. The `onesti_lock_activity` event still fires for every event, auto-lock included.

Locking from Home Assistant does update the sensor, as "Locked via Zigbee". The exception is the auto-wake before a PIN write, which also locks the door over Zigbee: a Zigbee lock within 30 seconds of a wake is taken as that echo and left out of the sensor, and so is a dashboard lock inside the same window. Whether 30 seconds fits every lock has not been measured, so if a PIN write on a sleeping lock still leaves "Locked via Zigbee" behind, report it with a debug log.

## 4. Debug logging

### Integration logging

Add to `configuration.yaml` and restart:

```yaml
logger:
  default: warning
  logs:
    custom_components.onesti_lock: debug
```

The log then shows the event listener registration at startup, every incoming operation event with its raw value, auto-wake attempts and results, a Zigbee lock taken as the wake echo, the Nimly response quirk when it occurs, and cluster lookup errors. Error messages from the send path have every run of 4 or more digits replaced with `****`, so a PIN code in an error does not reach the log from this integration.

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

`zigpy.zcl: debug` writes a lot. Turn it on while troubleshooting and off again afterwards.

### PIN codes appear in raw logs and diagnostics

A PIN code opens your door, and several parts of Home Assistant can write one to disk. This integration keeps codes out of its own states and log lines: it never reads the attribute where the lock reports the last used PIN, it masks digit runs of 4 or more when it logs a failed command, and it never accepts a PIN shorter than 4 digits, so the mask always covers a real code. It cannot keep a code out of everything, and one of the paths below is its own action:

- ZHA's quirk has its own last PIN code sensor. It is disabled by default, but enabled, the recorder stores every code used and the last one sits in clear text in Home Assistant's state.
- ZHA's **Download diagnostics** on the lock's device dumps zigpy's attribute cache, including the last reported 0x0101 value, which is the last used PIN.
- `zigpy.zcl: debug` prints raw ZCL frames. Frames for attribute 0x0101 carry the last used PIN in plaintext, and every command sent to the lock is printed too, so a PIN you set shows up in clear text.
- Calling the `onesti_lock.set_pin` action puts the code in the recorder database, since Home Assistant records every action call with its data, and from an automation or script also in that run's trace. The options flow does not.

Scrub those values before pasting a log, a diagnostics file or a trace into an issue or a forum post. If you already shared one, change the codes on the lock.

Versions 1.1.0 through 1.2.0 exposed the last used PIN as a state attribute, which put real codes in the recorder database. If you ran one of them, follow [section 6](#6-cleanup-after-versions-110-through-120).

### What to look for in the log

A successful operation event:

```
Lock event: unlock by Kari via keypad (raw: 0x02020003)
```

The raw value is a bitmap32: `0x02020003` → source=0x02 (keypad), action=0x02 (unlock), slot=3.

An auto-wake:

```
TimeoutError on attempt 1 for command 0x0005, waking lock and retrying
Waking lock via lock.onesti_products_as_nimlypro_door_lock
```

The first line says `DeliveryError` when Zigbee reported the frame as undelivered. The entity in the second line is ZHA's lock entity, so its id follows ZHA's naming.

A failed command:

```
TimeoutError sending command 0x0005 to f4:ce:36:... after wake and retry, lock may be unreachable: ...
```

The Nimly response quirk:

```
Nimly response quirk (IndexError) for command 0x0005, command was sent successfully
```

The event listener not registered:

```
Lock events for f4:ce:36:... cannot be received, ZHA internals missing: ZHA gateway (get_zha_gateway_proxy). Report the Home Assistant version in an issue if ZHA itself is running
```

It comes with the repair issue from section 3, usually after one of these:

```
ZHA has no running gateway, so the lock cannot be reached
Door Lock cluster not found for f4:ce:36:...
```

Older versions logged `ZHA not found` and `ZHA gateway_proxy not found` in the same situation.

A raw attribute report from zigpy (with `zigpy.zcl: debug`): zigpy logs every incoming frame twice, first raw (`Received ZCL frame: ...`) and then decoded. The decoded line for an operation event looks like this, with the exact repr depending on the zigpy version:

```
[0x...:11:0x0101] Decoded ZCL frame: DoorLock:Report_Attributes(attribute_reports=[Attribute(attrid=0x0100, ...)])
```

Reports with `attrid=0x0000` (lock state) but none with `attrid=0x0100` mean the lock has lost its reporting configuration. Try Reconfigure.

## 5. Common ZHA issues

### Device shows as "unavailable"

- Battery: a low battery means fewer reports and more command timeouts.
- Signal: the lock is too far from the nearest router, or never re-parented to the one you added. See "Signal issues" in section 1.
- After a battery change: the lock may have rejoined but lost its bindings. See section 1.

If Reconfigure fails repeatedly, follow "Reconfigure in ZHA" in section 1.

### Tips for stable operation

- Put a mains-powered Zigbee router near the lock, and check afterwards that the lock re-parents to it. "Signal issues" in section 1 has the numbers and the rest of the checklist.
- Do not move the coordinator. The network takes time to find new routes after the topology changes.
- Do not wait for a firmware update. The module lists the OTA Upgrade cluster and does ask for images (a ZHA diagnostics dump from a NimlyCodePRO shows its last Query Next Image request, with manufacturer code 0, image type 0 and version 0), but no image exists in the community zigbee-OTA index (checked 2026-09-19), so ZHA has nothing to offer. The vendor's BLE app does not update firmware either: a search of the decompiled app's own packages on 2026-09-20 (`reversing/nimly-ble-decompiled/sources/nimly/ekey`, `sources/com/nimly/ekey`, `sources/easyaccess/ekey`, 367 files, plus the manifest and string resources) found no DFU, OTA, firmware or bootloader, no Nordic DFU library and no DFU service UUID. The only BLE UUIDs the app knows are the Nimly service `ba4bfd00-c447-19bf-f38d-4890b3a824c8` with characteristic `ba4bfd03-...` and the standard CCCD `0x2902`. That says the shipped app has no update path, not that the lock cannot be updated some other way.
- Keep an eye on the battery. An automation that warns about low battery lets you avoid the problems that come with a battery change.

## 6. Cleanup after versions 1.1.0 through 1.2.0

Versions 1.1.0 through 1.2.0 published a `last_pin_code` attribute on `sensor.*_siste_aktivitet`. Attribute 0x0101 is the PIN itself, not an opaque id, so real access codes ended up in the recorder database. The attribute is gone, but old values stay until purged:

```yaml
service: recorder.purge_entities
target:
  entity_id: sensor.NAME_siste_aktivitet
data:
  keep_days: 0
```

This deletes all history for that entity, not only the PIN attribute; a single attribute cannot be purged.

Purging does not reach everything. zigpy keeps the last reported 0x0101 value in its own `zigbee.db` attribute cache, and ZHA diagnostics dumps that cache whatever this integration does. If a diagnostics file or a zigpy debug log has been shared publicly, the only reliable cleanup is to change the codes on the lock.
