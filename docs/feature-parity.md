# Feature parity with the app and the hub

What the vendor's software can do that this integration cannot, feature by feature, and how much of the gap is work nobody has done as opposed to work nobody can do.

"The app and the hub" is two products. The Nimly Connect app talks to the iotiliti cloud over REST, the cloud talks to the Connect Bridge over MQTT, and the bridge talks Zigbee to the lock ([hardware-gateway.md](connect-bridge/hardware-gateway.md)). The separate Nimly BLE app talks straight to the lock over Bluetooth, with no cloud in the path for the lock itself. Two of the features where the vendor wins are BLE features, not cloud features.

## How to read the evidence

Every claim here has one of three weights.

Verified: someone read it off hardware or a capture. A Zigbee frame in [zigbee-captures.md](zigbee-protocol/zigbee-captures.md), an attribute read from the lock, or behaviour seen on a running Home Assistant.

From the app code: read in the decompiled Nimly apps, in Java or smali, and checked against the app's own classes where crypto was involved. The command tables in [ble-protocol.md](nimly-ble-app/ble-protocol.md) and the library in [ble-library.md](nimly-ble-app/ble-library.md) are this kind. It says what the app sends, not what the lock answers.

Unresolved: nobody has the answer. The largest one sits under the whole BLE column. No advertisement has ever been seen from this lock, not by an ESPHome proxy 50 cm away, not by the Home Assistant host, not by a Shelly scanner, awake lock included. The one report from anyone else ([upstream-status.md](upstream-status.md#another-implementation-ariddernimly-manager)) says the same about normal use, and adds that the lock appeared the moment the vendor's BLE app opened "Add device", with a device name and ten bytes of service data where the app's code reads eight. The BLE library has never exchanged a byte with real hardware, and Home Assistant only knows Bluetooth devices it has heard in the last few minutes. So if the module only advertises inside a pairing window, or only when provoked, everything in that column becomes a flow the user starts at the lock, or is dead for this hardware. The best reading so far comes from the unloc app ([unloc-app.md](nimly-ble-app/unloc-app.md)), which opens doors by scanning for an enrolled lock in ordinary use: an enrolled module presumably advertises all the time, and an unenrolled one, which Fredrik's has always been, perhaps only in the pairing window after a power cycle. Three cheap measurements settle it (a phone scan, a scan with the app's Add device open, a scan across a power cycle), and none has been run. The vendor's module guide also says Bluetooth is only on "newer versions" of the module without saying which; the radio is a Nordic part with BLE on the die, so that line is more likely about firmware than about missing hardware.

## The table

Four questions, one per column. They are usually merged, which is where the confusion starts.

| Feature | The app and the hub today | This integration today | If BLE works | Never ours |
| --- | --- | --- | --- | --- |
| Who unlocked, and how | Cloud event history through the hub | Activity sensor with name and source, locally, no delay | Unchanged, Zigbee is the right channel | |
| Setting and clearing PINs | Cloud, or BLE `PinCodeSet` 0x52 | Over ZCL, without confirmation, with the bolt throw as wake-up | `StatusId` gives a real receipt, and the code travels encrypted | |
| Fingerprint enrollment | BLE `FingerprintScan` 0x57, or the keypad | Nothing | An interactive options flow step | |
| RFID enrollment | BLE `ScanRfidCode` 0x56, or the keypad | Nothing | The same step. The 2021 vendor spec has no RFID command over Zigbee, only responses, so deleting over Zigbee is doubtful | |
| The lock's own event log | Cloud history. BLE `DeviceLogGet` 0x44 exists, but the app throws the answer away | Only what Home Assistant hears while listening | The blob has to be reversed. ZCL `get_log_record` is not in the 2021 spec's command list | |
| Waking without throwing the bolt | The BLE connection is the wake-up. The hub queues against Zigbee | We throw the bolt | Solved for administration. Zigbee-only users stay where they are | |
| Name, clock, volume, auto-lock, keypad | BLE 0x32, 0x41, 0x5A, 0x5B, 0x5C, and the cloud app | Nothing from us. Volume and auto-lock are ZHA's already: the stock quirk exposes `sound_volume` 0x0024 and `auto_relock_time` 0x0023, both writable per the 2021 spec | Name, clock and the keypad switch, with model gates. Keypad may be `operating_mode` 0x0025 on Zigbee, never read | Master PIN and the keypad switch on NimlyPRO, which lacks the model flags |
| Sharing with other people | Ekeys to the guest's phone through the ekey cloud. The cloud app shares users | A PIN per person, or a Home Assistant user with an unlock button | An RFID tag per person | The vendor's ekeys to their app. The receiving end is theirs |
| One-time codes and schedules | The cloud app has OTP | Setting and clearing a PIN from an automation, which covers much of the need | | Real schedules in the lock, unless the firmware answers ZCL 0x0014-0x0016 |
| Remote access | Cloud, from anywhere | Home Assistant from outside gives the same, without a cloud | A BLE proxy at the door extends the range | |
| Battery level | Cloud, and BLE `BattInfoGet` 0x5D | ZHA's battery sensor | One more source, no new feature | |
| Firmware updates | Probably through the hub. No DFU in the BLE app | Nothing | Nothing, no OTA command on BLE | Images and the manufacturer code. Onesti only |
| Plaintext PIN on 0x0101 | Same problem | We never read it and mask everything we log | Unchanged | The attribute is in the firmware. Onesti only |
| Door ajar | Neither has it | Nothing | Nothing | No door sensor in the lock. Needs a contact sensor |

## What the vendor delivers

The first column is shorter than people expect: a hub that queues Zigbee commands towards a sleeping lock, and a cloud that stores history and key material. The hub sitting on the Zigbee network is why the app never sees a timeout, where a ZHA call from Home Assistant gets one 7.68-second window ([app-architecture.md](nimly-connect-app/app-architecture.md)). That is inferred from how the app behaves; the MQTT traffic is TLS and has never been read.

The two rows the vendor wins outright, fingerprint and tag enrollment, are won through the BLE app, which is as local as we want to be.

## What we have today, over Zigbee

The who-unlocked row is ours: no cloud, no delay, the name you gave the slot and the method used, and it is what a household sees every day. Setting and clearing PINs works, slots can be named, and the activity event drives automations. Battery and lock state come from ZHA.

Two dents. A PIN write is delivered but not confirmed, because the stock quirk raises an `IndexError` when the lock's answer is read and the integration counts the command as delivered anyway. And a sleeping lock is woken by throwing the bolt, which can lock an open door. Both are under [Limitations](user-guide.md#limitations) in the user guide, and both are problems BLE would solve that Zigbee only works around.

Much of the middle of the table is Zigbee work, some of it done by others. The vendor's 2021 spec ([elife-module-spec.md](zigbee-protocol/elife-module-spec.md)) documents `auto_relock_time` 0x0023 (a boolean there, not a time) and `sound_volume` 0x0024 as writable and reporting attributes, the stock ZHA quirk exposes them as a switch and a number, and a ZHA diagnostics dump from a NimlyCodePRO shows both cached. So volume and auto-lock are in Home Assistant today through ZHA's own entities, without this integration and without Bluetooth. Standard ZCL also has `operating_mode` 0x0025 and `supported_operating_modes` 0x0026, plus `wrong_code_entry_limit` 0x0030 and `user_code_temporary_disable_time` 0x0031, which line up with the five-minute lockout the manuals describe; none of the four is in the 2021 spec and none has been read from a lock. The module also carries a manufacturer-specific cluster 0xFEA2, "EA v2" in the spec, whose contents the spec does not describe and nobody has read; Datek's comparable lock puts master PIN mode, RFID enable, lock mode and relock settings in its equivalent. `get_log_record` 0x04 is standard ZCL but absent from the spec's command list (lock, unlock, set PIN, clear PIN and nothing else), so the event log over Zigbee is unlikely on that firmware. Reading 0x0025, 0x0030, 0x0031 and 0xFEA2 once, while the lock is awake, is the cheapest experiment on this page. Whatever does not answer moves to the BLE column and inherits its unresolved question.

## What BLE could give, if the hardware allows it

`custom_components/onesti_lock/ble/` is a full implementation of the lock's Bluetooth protocol, written from the decompiled app: framing, ECDH key exchange, AES-128-CBC, owner login, and enrollment of a factory-reset lock without the vendor cloud. The integration does not import it, and it has never talked to a lock. [ble-library.md](nimly-ble-app/ble-library.md) ends with a table separating what the app code settles from what only a lock can settle, and the second list is not short.

If it holds up, BLE gives four things Zigbee cannot.

Fingerprint enrollment (`FingerprintScan` 0x57, slots 150-199) and RFID enrollment (`ScanRfidCode` 0x56, slots 900-999). Both are interactive, so they need an options flow step that keeps the session open while the user presents a finger or holds a tag against the reader, within the app's 20-second timeout. ZCL has no fingerprint command at all, so Zigbee can never do the first.

A PIN write with a receipt. The BLE answer carries a `StatusId` where 0 is success and ten other values are named errors, and the link is encrypted under a key that is new per connection, so the code never crosses the air in clear.

A wake-up that does not move the bolt, since connecting is the wake-up. That solves administration and leaves Zigbee-only users where they are.

Two caveats travel with the whole column. The relationship between BLE slots 800-899 and the Zigbee slots is unmapped, and no command reads a slot back, so every write is blind and every delete one-way. And the model gates are real: the app does not offer master PIN or the keypad switch on NimlyPRO, so those two stay out of reach on that model whatever the channel.

## Sharing access with other people

The vendor has two ways to share. The BLE app creates a guest with `EkeyUserAdd` 0x1B and hands back key material the guest's phone uses to log in, with distribution through the ekey cloud. The Connect app shares users through the iotiliti cloud with access types `pin`, `finger`, `tag`, `digitalKey` and `otp`.

The first will never be ours, and not because a command is missing. Even if the integration called `EkeyUserAdd` over BLE and got the key material out, no app on the guest's phone would accept it from us. A guest app is a different project from a Home Assistant integration, which is why `ServerKeyUpdate` 0x42 and the whole guest path were left out of the BLE library.

What we can offer instead, and what it costs the guest:

A Home Assistant user with an unlock button is the closest thing to a digital key, and needs no vendor and no Bluetooth. The cost is real: the guest installs the Home Assistant app, gets an account on your instance, and needs it reachable from outside to use it away from your wifi. Fine for a partner or a housemate. For a dog sitter coming once it is more than they signed up for, and you are handing out an account on your home automation to do it.

A PIN per person works today and costs the guest nothing: four to eight digits and a keypad. The activity sensor then names them by that slot every time. The drawbacks are that setting the code may lock an open door, and that the code passes through Home Assistant's recorder and any automation trace that sets it.

Time-limited access is a PIN plus an automation: set the code the morning the job starts, clear it when it ends. The plumber example in the [user guide](user-guide.md#automation-examples) is this. It is a schedule in Home Assistant, not in the lock, so it stops working while Home Assistant is down.

An RFID tag per person is the nicest of the four for the guest, and needs BLE enrollment first.

Real one-time codes and real schedules held by the lock need firmware support we cannot see. ZCL defines schedule commands 0x0B to 0x13 and `set_user_status` 0x09, but no vendor manual describes either feature, and the 2021 Zigbee spec lists lock, unlock, set PIN and clear PIN as the only commands the module implements. Reading the capacity attributes 0x0014 to 0x0016 would settle it for current firmware and has not been done.

## Remote access, and what goes down with Home Assistant

Remote control sounds hard to match locally and is the easiest of the lot if Home Assistant is already reachable from outside: your phone, your Home Assistant, ZHA, the lock, no cloud. Zigbee range is a router next to the door, which the [user guide](user-guide.md#limitations) already recommends because the metal casing acts like a Faraday cage. BLE, if it ever becomes a channel, needs an ESPHome Bluetooth proxy at the door, since the Home Assistant host is rarely within Bluetooth range of a front door.

When Home Assistant is down, all of it goes: no remote control, no PIN management, no events. The lock keeps working with keypad, finger, tag and key, and auto-lock still runs. That is the same dependency the vendor has, moved from their cloud to your machine, and the hub has the identical property when the cloud or the internet goes. The difference is that you can do something about yours.

## What is never ours

Three items, listed so nobody mistakes them for work we have not got around to.

The vendor's ekeys, for the reason above: the receiving end is their app.

Firmware updates. The decompiled BLE app has no DFU service, no image upload, and no update command anywhere in the table from 0x01 to 0x70. It reads the firmware version from GATT Device Information 0x2A28 and refuses to connect below 4.6.0, so it can see that firmware is too old and do nothing about it. That is a negative finding from static analysis, not proof. The likely route is the hub, which updates itself and can be told to update from the app. On the Zigbee side the module advertises the OTA cluster 0x0019 as a client and sends Query Next Image requests (a ZHA dump from a NimlyCodePRO records one, with manufacturer code 0, image type 0, version 0 and hardware version 52), so the receiving machinery exists and runs; what is missing is an image, and the zeros in that request are their own puzzle for whoever gets one. Koenkk's zigbee-OTA index has over nine hundred images and none for Nimly, Onesti, EasyAccess or manufacturer code 4660, and zigpy's vendor providers have no Onesti either. We cannot build a firmware image and should not try: a bricked module is a bricked front door. The ask is that Onesti publish images and register the manufacturer code, since 0x1234 is a placeholder.

The plaintext PIN on 0x0101. The lock puts the last used PIN in clear on a manufacturer-specific attribute under manufacturer code 4660, as BCD: the actual code that opens the door, not a reference to a user. We never read the attribute, mask digit runs of four and up before anything is logged, refuse PINs shorter than four digits so the mask always covers a real code, and go around ZHA's `issue_zigbee_cluster_command` service because Home Assistant records every service call with its data. That keeps our own house clean. The attribute is still in the lock and still answers anyone who asks: the stock quirk's `last_pin_code` sensor, the Zigbee2MQTT converter's `last_used_pin_code`, a ZHA diagnostics download, or zigpy debug logging. Removing it takes a firmware change at Onesti; nothing in an integration, a quirk or a Home Assistant release can do it. The rest of that thread is in [upstream-status.md](upstream-status.md).

## Door ajar

Whether the door is standing open, as opposed to where the bolt is, is not a gap against the app. The cloud app shows lock state, not door state, the BLE `LockStatus` event carries locked and unlocked and nothing else, and there is no cloud event for an open door. The lock has no door sensor in the hardware, so no firmware update can add one.

ZCL defines `door_state` 0x0003 with counters 0x0004 and 0x0005, and reading 0x0003 settles it cheaply, but the expected answer is `NotFullyLocked` or `Unspecified`. What answers the question is a contact sensor on the door leaf, Zigbee or Z-Wave, any brand, cheap, which becomes a binary sensor in Home Assistant. The useful thing to build on top is a blueprint tying that sensor to the activity sensor, along the lines of "tell me when the door has been open for five minutes after Kari unlocked it".

## Where the cloud tracks went

Reverse engineering the iotiliti cloud further would give parity on paper for history and OTP, and is tracked separately ([cloud-api-status.md](cloud-api-status.md)). It is out of scope here because it buys parity by putting the cloud back in the path, which is what this integration exists to remove.
