# The vendor's own Zigbee spec for the module

Onesti wrote a Zigbee protocol document for the Connect Module, *E-life Zigbee Modul User Manual v2.0*. A customer attached it to [Z2M#6379](https://github.com/Koenkk/zigbee2mqtt/issues/6379) on 2021-02-20, where it is still downloadable:

```
https://github.com/Koenkk/zigbee2mqtt/files/6015013/E-life.Zigbee.Modul.User.Manual.v2.0.pdf
```

`python3 scripts/fetch_manuals.py` downloads it with the other vendor documents, as `docs/manuals/E-life-Zigbee-Modul-User-Manual-v2.0-260121.pdf` plus a text extract; both are gitignored.

Word metadata says it was created 2021-01-26 by Andrea Birkheim, and the title page is dated 25.01.2021 and headed "Easy Access E-Life Zigbee Module"; the "v2.0" is only in the attachment filename. It is 15 pages, and the only vendor-written description of the Zigbee side anyone has found. It describes the module as it was in early 2021, so it is the baseline, not the current firmware: our lock answers things this document does not mention, and does not answer some it does.

Everything below is quoted or condensed from it. Where it disagrees with what we have measured, the measurement wins and the disagreement is noted.

## What it says about the module

- Endpoint 11, Zigbee channel mask `0x07FFF800`.
- Server clusters: Basic, Power Configuration, Identify, Groups, Scenes, Door Lock, **EA v4 (proprietary)** and **EA v2 (proprietary)**. Client: OTA.
- Devices that want responses and attribute reports have to bind to the endpoint and cluster and subscribe to the reporting attributes.

EA v2 is almost certainly the `0xFEA2` cluster our interview shows and nobody has read (`zigbee-captures.md`). EA v4 would then be `0xFEA4`, which our module does not list, so it went away or was never on this model. The document names the two clusters and says nothing more: no attributes, no commands. That settles what 0xFEA2 is called and leaves what is in it as open as before.

Identify (0x0003), Groups (0x0004) and Scenes (0x0005) get a page each, and each is the plain ZCL attribute set with no commands supported: IdentifyTime, NameSupport, and SceneCount, CurrentScene, CurrentGroup, SceneValid, NameSupport. Nothing about the lock is in them.

## Basic cluster (0x0000)

| Attribute         | Id     | Documented default        | Note                     |
| ----------------- | ------ | ------------------------- | ------------------------ |
| ZCLVersion        | 0x0000 | 0x02                      |                          |
| ApplicationVersion| 0x0001 | 0x01 or higher            | **Module FW version**    |
| StackVersion      | 0x0002 | 10                        | Zigbee implementation    |
| HWVersion         | 0x0003 | 11 or higher              | **Module HW version**    |
| ManufacturerName  | 0x0004 | "Onesti Products AS"      |                          |
| ModelIdentifier   | 0x0005 | "easyCodeTouch_v1" or "EasyCode903G2" | Lock model, not module |
| DateCode          | 0x0006 | 20201211 or newer         | ISO 8601 YYYYMMDD        |
| PowerSource       | 0x0007 | 0x04                      | DC source                |
| LocationDescription | 0x0010 | "Entrance Door"          |                          |
| PhysicalEnvironment | 0x0011 | 0                        |                          |
| SWBuildId         | 0x4000 | n/a                       | "Not set" in 2021        |

HWVersion is the module hardware version and has read 11 on every module seen from 2021 to 2024, so it does not separate revisions. SWBuildId was empty in 2021 and carries `4.8.01` on a 2024 module, so the vendor started filling it in somewhere in between.

## Power Configuration (0x0001)

BatteryVoltage 0x0020 = 45 (100 mV steps, so 4.5 V), BatteryPercentageRemaining 0x0021 = 100 and the only reporting attribute here, BatterySize 0x0031 = 3, BatteryQuantity 0x0033 = 3, BatteryRatedVoltage 0x0034 = 15. Three AA cells at 1.5 V. No commands.

## Door Lock (0x0101)

Attributes the module is documented to support:

| Attribute                   | Id     | Documented value |
| --------------------------- | ------ | ---------------- |
| LockState                   | 0x0000 | reporting; LOCKED 0x01, UNLOCKED 0x02, no notion of the state at power-on |
| LockType                    | 0x0001 | 0x00, dead bolt  |
| ActuatorEnabled             | 0x0002 | true             |
| NumberOfTotalUsersSupported | 0x0011 | 100 (PIN and RFID together) |
| NumberOfPINUsersSupported   | 0x0012 | 50               |
| NumberOfRFIDUsersSupported  | 0x0013 | 50               |
| MaxPINCodeLength            | 0x0017 | 8                |
| MinPINCodeLength            | 0x0018 | 4                |
| MaxRFIDCodeLength           | 0x0019 | 14               |
| MinRFIDCodeLength           | 0x001A | 4                |
| AutoRelockTime              | 0x0023 | write, reporting; 0x00 or 0x01 only, not a time |
| SoundVolume                 | 0x0024 | write, reporting; 0x00 off, 0x01 low, 0x02 normal |

The 50 PIN users and the 4-8 digit range are what `pin_rules.py` enforces, now with a vendor source behind them. AutoRelockTime is explicitly a boolean here even though ZCL calls it a time.

Commands it says are the only ones supported:

- Lock/Unlock 0x00/0x01. A PIN parameter may be present but must have length 0; the lock does not take a PIN in the lock command.
- Set PIN Code 0x05, user id 1-50, UserStatus and UserType mandatory in the frame but ignored by the module, 4-8 digits.
- Clear PIN Code 0x07, user id 1-50.

Nothing else. No schedules, no user status or user type, no get_pin_code, no get_log_record, and no RFID command of any kind. That matches the manuals, which describe no schedules either. Sound volume and auto-relock are changed by writing their attributes, not by a command, and the document says so in two short sections.

Server-to-client:

- Lock/Unlock Response 0x00/0x01: status FAILURE 0x00 or SUCCESS 0x01.
- Set PIN Code Response 0x05, Clear PIN Code Response 0x07, Set RFID Code Response 0x16, Clear RFID Code Response 0x18: the same two statuses. For the two Set responses it adds that memory full (2) and duplicate code (3) are explicitly **not** implemented; the Clear responses only get the two statuses. The RFID responses are documented even though no RFID command is, and the Clear RFID section labels its id `CLEAR_PIN_CODE_RESPONSE 0x18`, which reads as a copy-paste slip.

A one-byte status is not what plain ZCL expects, and a response body shorter than the reader assumes is the shape that produces the `IndexError` in the stock quirk. This does not prove the cause, but it is the first vendor statement consistent with it.

## Operation Notification (command 0x20)

The document says the standard Operation Event Notification is "partially supported", with this payload and these tables:

```
[RSP_ID 0x20][SOURCE][CODE][USER_ID 0x00][PIN 0x00][LOCAL_TIME 0x00][DATA 0x00]
```

| Source | Meaning                                  |
| ------ | ---------------------------------------- |
| 0x00   | Keypad                                   |
| 0x02   | Manual (key, button or fingerprint)      |
| 0x03   | RFID                                     |
| 0xFF   | Other                                    |

| Event | Meaning             |
| ----- | ------------------- |
| 0x00  | Lock                |
| 0x01  | Unlock              |
| 0x08  | Key lock            |
| 0x09  | Key unlock          |
| 0x10  | Fingerprint lock    |
| 0x11  | Fingerprint unlock  |

This is a different encoding from the one the integration decodes. Ours reads the manufacturer-specific attribute `0x0100`, where byte 3 is the source with 0x02 keypad, 0x03 fingerprint, 0x04 rfid, 0x0A auto (`events.py`). The two tables share no values, so do not mix them. Our lock has never been seen to send command 0x20 at all (`docs/technical.md`), so the attribute is the only channel that works in practice, and the table above belongs to a path that may have been dropped after 2021.

User id, PIN, local time and data are all documented as 0x00, so even where the notification fires it carries no user.

## OTA (0x0019)

"The module implementation supports the OTA Upgrade cluster for FW update." The client cluster is in our interview too. No image has ever been published, so this stays a capability with nothing to feed it.
