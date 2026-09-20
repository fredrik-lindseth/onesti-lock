# Feature parity with the app and the hub

What the vendor's own software can do that this integration cannot, feature by
feature, and how much of the gap is work nobody has done yet as opposed to work
nobody can do.

"The app and the hub" is two different products. The Nimly Connect app talks to
the iotiliti cloud over REST, the cloud talks to the Connect Bridge over MQTT,
and the bridge talks Zigbee to the lock
([hardware-gateway.md](connect-bridge/hardware-gateway.md)). The separate Nimly
BLE app talks straight to the lock over Bluetooth with no cloud in the path for
the lock itself, which matters more than it sounds: two of the features where
the vendor clearly wins are BLE features, not cloud features.

## How to read the evidence

Claims on this page carry one of three weights, and mixing them up is how a
roadmap turns into wishful thinking.

**Verified** means someone read it off hardware or off a capture: a Zigbee frame
in [zigbee-captures.md](zigbee-protocol/zigbee-captures.md), an attribute read
from the lock, or behaviour observed on a running Home Assistant.

**From the app code** means it was read in the decompiled Nimly apps, in Java or
in smali, and checked against the app's own classes where crypto was involved.
The protocol and command tables in
[ble-protocol.md](nimly-ble-app/ble-protocol.md) and the library in
[ble-library.md](nimly-ble-app/ble-library.md) are that kind of knowledge. It
says what the app sends. It does not say what the lock answers.

**Unresolved** means nobody has the answer. The largest single unresolved item
sits under the whole BLE column: no advertisement has ever been observed from
this lock. The BLE library has never exchanged a byte with real hardware, and
Home Assistant only knows about Bluetooth devices it has heard from in the last
few minutes, so if the Connect Module only advertises inside a pairing window,
everything in that column is dead for this hardware. That question costs one
scan to answer and has not been answered.

## The table

Four separate questions, one per column. The confusion starts when they are
merged.

| Feature | The app and the hub today | This integration today | If BLE works | Never ours |
| --- | --- | --- | --- | --- |
| Who unlocked, and how | Cloud event history through the hub | Activity sensor with name and source, locally and without delay | Unchanged, Zigbee is the right channel for this | |
| Setting and clearing PINs | Cloud, or BLE `PinCodeSet` 0x52 | Works over ZCL, but without confirmation and with the bolt throw as the wake-up | `StatusId` gives a real receipt, and the code travels encrypted | |
| Fingerprint enrollment | BLE `FingerprintScan` 0x57, or the keypad | Nothing | An interactive step in the options flow | |
| RFID enrollment | BLE `ScanRfidCode` 0x56, or the keypad | Nothing | The same step. Deleting possibly over Zigbee | |
| The lock's own event log | Cloud history. BLE `DeviceLogGet` 0x44 exists, but the app throws the answer away | Only what Home Assistant hears while it is listening | The blob has to be reversed. ZCL `get_log_record` may give it for free if the firmware answers | |
| Waking without throwing the bolt | The BLE connection is the wake-up. The hub queues against Zigbee | We throw the bolt | Solved for administration. Zigbee-only users are left where they are | |
| Name, clock, volume, auto-lock, keypad | BLE 0x32, 0x41, 0x5A, 0x5B, 0x5C, and the cloud app | Nothing | All of it, with model gates. Volume, auto-lock and keypad may sit on Zigbee attributes we have never read | Master PIN and the keypad switch on NimlyPRO, which lacks the model flags |
| Sharing with other people | Ekeys to the guest's phone, through the ekey cloud. The cloud app shares users | A PIN per person, a Home Assistant user with an unlock button | An RFID tag per person | The vendor's ekeys to their app. The receiving end is theirs, not ours |
| One-time codes and schedules | The cloud app has OTP | Setting and clearing a PIN from an automation, which covers much of the need | | Real schedules in the lock, unless the firmware answers ZCL 0x0014-0x0016 |
| Remote access | Cloud, from anywhere | Home Assistant from outside gives the same, without a cloud | A BLE proxy at the door extends the range | |
| Battery level | Cloud, and BLE `BattInfoGet` 0x5D | ZHA's battery sensor | One more source, no new feature | |
| Firmware updates | Probably through the hub. No DFU found in the BLE app | Nothing | Nothing, there is no OTA command on BLE | Images and the manufacturer code. Onesti only |
| Plaintext PIN on 0x0101 | They have the same problem | We never read it, and we mask everything we log | Unchanged | The attribute is in the firmware. Onesti only |
| Door ajar | Neither of them has it either | Nothing | Nothing | The lock has no door sensor. Needs a contact sensor of its own |

## What the vendor actually delivers

The first column is shorter than people expect. There is no magic in it: a hub
that queues Zigbee commands towards a sleeping lock, and a cloud that stores
history and key material. The hub sitting on the Zigbee network is why the app
never sees a timeout, where a ZHA call from Home Assistant gets one 7.68-second
window ([app-architecture.md](nimly-connect-app/app-architecture.md)). That is
an inference from how the app behaves, not a captured payload: the MQTT traffic
is TLS and has never been read.

The two rows where the vendor wins outright, fingerprint and tag enrollment, are
not won through the cloud at all. They are won through the BLE app, which is
exactly as local as we want to be.

## What we have today, over Zigbee

The who-unlocked row is ours. It arrives with no cloud and no delay, with the
name you gave the slot and the method that was used, and it is the thing a
household sees every day. Setting and clearing PINs works, slots can be named,
and the activity event drives automations. Battery and lock state come from
ZHA's own entities.

Two honest dents in it. A PIN write is delivered but not confirmed, because the
stock quirk raises an `IndexError` when the lock's answer is read and the
integration counts the command as delivered anyway. And a sleeping lock is woken
by throwing the bolt, which can physically lock an open door. Both are described
in the README under Limitations, and both are BLE-shaped problems with
Zigbee-shaped workarounds.

A good part of the middle of the table may turn out to be Zigbee work rather
than BLE work. Standard ZCL has `auto_relock_time` 0x0023, `sound_volume`
0x0024, `operating_mode` 0x0025 and `supported_operating_modes` 0x0026, plus
`wrong_code_entry_limit` 0x0030 and `user_code_temporary_disable_time` 0x0031,
which line up neatly with the five-minute lockout the manuals describe. The
module also carries a manufacturer-specific cluster 0xFEA2 that nobody has ever
read, and Datek's comparable lock puts master PIN mode, RFID enable, lock mode
and relock settings in its equivalent. `get_log_record` 0x04 is standard too.
None of these have been read from the lock. If the firmware answers them,
volume, auto-lock, keypad enable and possibly the event log become plain Home
Assistant entities over Zigbee with no Bluetooth involved, which would be the
largest gain per hour of work on this page. If it does not answer, those
features move to the BLE column and inherit its one unresolved question.

## What BLE could give, if the hardware allows it

`custom_components/onesti_lock/ble/` is a full implementation of the lock's
Bluetooth protocol, written from the decompiled app: framing, ECDH key exchange,
AES-128-CBC, owner login, and enrollment of a factory-reset lock without the
vendor cloud. The integration does not import it, and it has never talked to a
lock. [ble-library.md](nimly-ble-app/ble-library.md) ends with a table that
separates what the app code settles from what only a lock can settle, and the
second list is not short.

Assuming it holds up, BLE would give four things Zigbee cannot:

Fingerprint enrollment (`FingerprintScan` 0x57, slots 150-199) and RFID
enrollment (`ScanRfidCode` 0x56, slots 900-999). Both are interactive by nature,
so they need an options flow step that keeps the session open while the user
presents a finger or holds a tag against the reader, within the app's single
20-second timeout. ZCL has no fingerprint command at all, so Zigbee can never do
the first one.

A PIN write with a real receipt. The BLE answer carries a `StatusId` where 0 is
success and ten other values are named errors, and the whole link is encrypted
under a key that is new per connection, so the code never crosses the air in
clear.

A wake-up that does not move the bolt, since connecting is the wake-up. That
solves administration, and leaves Zigbee-only users exactly where they are.

Two caveats travel with the whole column. The slot relationship between BLE
800-899 and the Zigbee slots is unmapped, and no command reads a slot back, so
every write is blind and every delete is one-way. And the model gates are real:
the app does not offer master PIN or the keypad switch on NimlyPRO, so those two
stay out of reach on that model whatever the channel.

## Sharing access with other people

This is the row where the honest answer is longer than the table cell, so here
it is in full.

The vendor has two ways to share. The BLE app creates a guest with
`EkeyUserAdd` 0x1B and hands back key material the guest's phone then uses to
log in, with the distribution itself going through the ekey cloud. The Connect
app shares users through the iotiliti cloud with access types `pin`, `finger`,
`tag`, `digitalKey` and `otp`.

The first one will never be ours, and not because a command is missing. Even if
the integration called `EkeyUserAdd` locally over BLE and got the key material
out, there is no app on the guest's phone that would accept it from us. Building
a guest app is a different project than a Home Assistant integration. That is
why `ServerKeyUpdate` 0x42 and the whole guest path were deliberately left out
of the BLE library.

What we can offer instead, and what it costs the guest in practice:

A **Home Assistant user with an unlock button** is the closest thing to a
digital key, and it needs no vendor and no Bluetooth. It is plain Home Assistant
configuration. The cost is real though: the guest installs the Home Assistant
app, gets an account on your instance, and needs your instance reachable from
outside to use it away from your wifi. For a partner or a housemate that is
fine. For a dog sitter coming once, it is more than they signed up for, and you
are handing out an account on your home automation system to do it.

A **PIN per person** works today, in the shipped integration, and costs the
guest nothing at all: four to eight digits and a keypad. The activity sensor
then names them by that slot every time they come in. The two honest drawbacks
are that setting the code may physically lock an open door, and that the code
passes through Home Assistant's recorder and any automation trace that sets it.

**Time-limited access** is a PIN plus an automation: set the code the morning
the job starts, clear it when the job ends. The README's plumber example is
exactly this. It is not a schedule in the lock, it is a schedule in Home
Assistant, which means it stops working while Home Assistant is down.

**An RFID tag per person** is the nicest of the four for the guest, and it is
the one that needs BLE enrollment first.

What we cannot give without firmware support is real one-time codes and real
schedules held by the lock itself. ZCL defines schedule commands 0x0B to 0x13
and `set_user_status` 0x09, but no vendor manual describes either feature, so
they are probably not implemented. Reading the capacity attributes 0x0014 to
0x0016 settles it cheaply and has not been done.

## Remote access, and what goes down with Home Assistant

Remote control is the one thing the cloud app does that sounds hard to match
locally, and it is the easiest of the lot if Home Assistant is already reachable
from outside. The path is your phone, your Home Assistant, ZHA, the lock, with
no cloud in it. Zigbee range is handled by a router next to the door, which the
README already recommends because the metal casing acts like a Faraday cage.
BLE, if it ever becomes a channel, needs an ESPHome Bluetooth proxy at the door,
since the Home Assistant host is rarely within Bluetooth range of a front door.

What breaks when Home Assistant is down should be said plainly: all of it. No
remote control, no PIN management, no events. The lock itself keeps working with
keypad, finger, tag and key, and auto-lock still runs. That is the same
dependency the vendor has, moved from their cloud to your machine. The
difference is that you can do something about yours. The hub has the identical
property: if the cloud or the internet goes, Nimly Connect is just as useless.

## What is never ours

Three items, and they are on this page precisely so nobody mistakes them for
work we simply have not got around to.

**The vendor's ekeys**, for the reason above: the receiving end is their app.

**Firmware updates.** The decompiled BLE app has no DFU service, no image
upload, and no update command anywhere in the table from 0x01 to 0x70. It reads
the firmware version from GATT Device Information 0x2A28 and refuses to connect
below 4.6.0, so it can see that firmware is too old and do nothing about it.
That is a negative finding from static analysis, not proof. The likely route is
the hub, which updates itself and can be told to update from the app. On the
Zigbee side the module advertises the OTA cluster 0x0019 as a client, so the
receiving machinery exists in the firmware; what is missing is an image.
Koenkk's zigbee-OTA index has over nine hundred images and not one for Nimly,
Onesti, EasyAccess or manufacturer code 4660, and zigpy's vendor providers have
no Onesti either. We cannot build a firmware image and should not try: a bricked
module is a bricked front door. This is vendor work, and the ask is that Onesti
publish images and register the manufacturer code, since 0x1234 is a
placeholder.

**The plaintext PIN on 0x0101.** The lock puts the last used PIN code in clear
on a manufacturer-specific attribute under manufacturer code 4660, as BCD. Not
an opaque reference to a user, the actual code that opens the front door. We
never read the attribute, we mask digit runs of four and up before anything is
logged, we refuse PINs shorter than four digits so the mask always covers a real
code, and we go around ZHA's `issue_zigbee_cluster_command` service because Home
Assistant records every service call with its data. All of that keeps our own
house clean. The attribute is still in the lock and still answers anyone who
asks: the stock quirk's `last_pin_code` sensor, the Zigbee2MQTT converter's
`last_used_pin_code`, a ZHA diagnostics download, or zigpy debug logging.
Removing it takes a firmware change at Onesti. Nothing in an integration, a
quirk or a Home Assistant release can do it. The rest of that thread is in
[upstream-status.md](upstream-status.md).

## Door ajar is a category of its own

Whether the door is standing open, as opposed to where the bolt is, is not a gap
against the app. The cloud app shows lock state, not door state. The BLE
`LockStatus` event carries locked and unlocked and nothing else. There is no
cloud event for an open door. The vendor has this hole exactly as much as we do,
because the lock has no door sensor in the hardware and no firmware update can
add one.

ZCL does define `door_state` 0x0003 with counters 0x0004 and 0x0005, and reading
0x0003 settles the question cheaply, but the expected answer is `NotFullyLocked`
or `Unspecified`. What actually answers the question is a contact sensor on the
door leaf, Zigbee or Z-Wave, any brand, and cheap. It becomes
a binary sensor in Home Assistant. The useful thing we could build on top is a
blueprint tying that sensor to the activity sensor, along the lines of "tell me
when the door has been open for five minutes after Kari unlocked it".

## Where the cloud tracks went

Reverse engineering the iotiliti cloud further would give parity on paper for
history and OTP, and it is tracked separately for that reason
([cloud-api-status.md](cloud-api-status.md)). It is out of scope here because it
buys parity by putting the cloud back in the path, which is the thing this
integration exists to remove.
