# Slot numbering: known facts and unknowns

Onesti locks store user credentials (PIN codes, RFID tags, fingerprints) in
numbered slots. The numbering differs between access methods.

## Known (verified)

### Zigbee ZCL (DoorLock cluster 0x0101)

The split between master and user slots differs per model. The manuals:

| Slot range | Touch Pro, PRO, Code                | Code Pro                            | Source                                                                  |
| ---------- | ----------------------------------- | ----------------------------------- | ----------------------------------------------------------------------- |
| 0          | Master PIN (factory: 123)           | Master PIN (factory: 123)           | All manuals. Verified: `attrid 0x0100` reports `user_slot=0` on unlock |
| 1-2        | Additional master codes             | User codes                          | Manuals, see quotes below                                               |
| 3-999      | User codes, RFID tags, fingerprints | User codes, RFID tags, fingerprints | Manuals. Slots 3-4 verified via `attrid 0x0100` events                  |

What the manuals say, quoted from the English PDFs on nimly.se:

- [Touch Pro manual](https://nimly.se/wp-content/uploads/2024/09/EN-Touch-Pro-Installation-Manual-150324.pdf) (dated 15.03.2024): "User slot 000 is reserved for your first master code", "User slot 001 and 002 are reservered for more master codes", "User slot 003 to 999 are reservered user codes". The master finger is 000 with 001-002 for more master fingers, user fingers are 003-199, key tags 003-999. "Master codes cannot be deleted, only overwritten to new master codes."
- [Code installation guide](https://nimly.se/wp-content/uploads/2023/11/EN-Code-Installation-Guide-130922.pdf) (dated 13.09.2022): "User slot 000, 001 and 002 are reserved for the master code(s)", user codes from 003, "Key tags can be added to user slots 000 to 999."
- [Code Pro product guide](https://nimly.se/wp-content/uploads/2026/04/EN-Code-Pro-Product-Guide-120126.pdf) (dated 12.01.2026): "000 Master codes, 001-999 user codes", "User codes can be added to user slot 001 to 999", "Master codes can not be removed, only overwritten." The master code unlocks by default, but the Code Pro can be set to use it for programming only.

The model string cannot pick the right column. A Code Pro reported itself as NimlyTwist ([#5](https://github.com/fredrik-lindseth/onesti-lock/issues/5)), so the integration leaves the choice to the user (see Current implementation).

ZCL commands that use slot numbers:

- `set_pin_code` (0x0005): `user_id` = slot number
- `get_pin_code` (0x0006): `user_id` = slot number
- `clear_pin_code` (0x0007): `user_id` = slot number
- `attrid 0x0100` (operation event): bytes 0-1 = slot number used

### BLE ekey protocol

Decompiled from `easyaccess.ekey.app` v1.5.1 (see `docs/nimly-ble-app/ble-protocol.md`):

| Slot range | Purpose    | Source                                                      |
| ---------- | ---------- | ----------------------------------------------------------- |
| 0          | Master PIN | Decompiled code                                             |
| 800-899    | User PINs  | Decompiled code (`PinCodeSet` 0x52, `slotNumber` uint16 LE) |

Example: setting PIN "8832" on BLE slot 803 sends `23 03 04 38 38 33 32`
(slot 803 little-endian + length + ASCII).

### Cloud API (iotiliti)

The cloud API (`POST /devices/{id}/access`) uses abstract user IDs, not raw
slot numbers. The gateway translates between cloud users and ZCL slot numbers
internally.

### Confirmed facts

- **PIN codes survive re-pairing.** PIN 2510 set via ZHA (slot 4) still worked after the lock was removed from ZHA and paired with the Connect Bridge hub. Storage is local on the lock. (Tested 2026-03-30.)
- **RFID uses the same slot numbering as ZCL.** RFID tag on slot 1 reported `user_slot=1` in `attrid 0x0100`. (Tested 2026-03-30.)
- **Fingerprint uses the same slot numbering as ZCL.** Fingerprint on slot reported correctly in `attrid 0x0100`. (Tested 2026-03-30.)

## Unknown (not yet verified)

**Is BLE slot 800 the same as Zigbee slot 3?** The hypothesis is that BLE
slots 800-899 and ZCL slots 3+ refer to the same physical storage with
different offsets, but they may also be separate storage areas in firmware.

**Cloud API slot assignment.** When the cloud API receives a new PIN, the
gateway picks a slot automatically. We don't know which slot it picks or
whether it coordinates with BLE numbering.

**Fingerprint and RFID slot ranges via BLE.** The BLE protocol has
`FingerprintClear` (0x58) and `RfidCodeClear` (0x55) with `slotNumber`
parameters. The numbering for these has not been mapped.

## Current implementation

```python
# const.py
MAX_SLOTS = 1000          # ZCL slots 0-999 (per manual)
SLOT_FIRST_USER = 3       # Default for the reserved_slots option
CONF_RESERVED_SLOTS = "reserved_slots"
RESERVED_SLOTS_MIN = 1    # Slot 0 stays protected whatever is stored
RESERVED_SLOTS_MAX = 3
NUM_USER_SLOTS = 10       # Slots shown in the options flow lists
```

- **Reserved slots setting**: per lock, under Configure > Settings, 1-3 with default 3. `pin_rules.first_user_slot()` reads it and clamps it to 1-3, so slot 0 is never written even if the stored value is wrong. Touch Pro, PRO and Code users keep 3; Code Pro users can set 1.
- **Write and clear floor**: `set_pin`, `clear_pin` and `clear_slot` refuse slots below the setting, from both the services and the options flow. The Set PIN list starts at the first user slot, and the Clear PIN list leaves the reserved slots out.
- **Naming**: every slot 0-999 can be named, through `set_name` and the options flow. Names are stored in Home Assistant only. An empty name in the options flow removes it, which is the only way to unname a reserved slot.
- **View slots**: lists the reserved slots, marked as master, followed by the first ten user slots.
- **set_pin capacity check**: when the lock has reported `NumberOfPINUsersSupported` (50 on both NimlyPRO and NimlyCodePRO), `set_pin` rejects slots at or above it (`pin_rules.py`). Before the attribute has been read (sleepy lock at setup, or a variant without the attribute) 999 is the ceiling. Whether slots >= 50 actually work on real hardware is still unverified; see the capacity test below.
- **Sensors**: 10 slot sensors (3-12), showing name and PIN status. They do not follow the setting.
- **Event decoding**: `attrid 0x0100` bytes 0-1 give the slot number, always in ZCL numbering regardless of how the credential was enrolled. Slot 0 counts as the master user when the source is keypad, fingerprint or rfid, and gets the name set on slot 0, or "Master" without one. With source zigbee, auto, unattributed or unknown, slot 0 means no user.

## Verification plan

1. **BLE/Zigbee cross-test:** Set PIN via BLE on slot 800. Unlock. Check whether `attrid 0x0100` reports slot 3 or slot 800.
2. **Cloud/Zigbee cross-test:** Set PIN via Nimly Connect app. Unlock. Check which slot `attrid 0x0100` reports.
3. **Slot 1-2 test and outside locking with slot 0:** Try `set_pin_code` on slots 1 and 2 via ZCL on each model. Does the lock accept or reject? Also lock from the outside (palm on the keypad, or `#`) and capture `attrid 0x0100`. It is unverified whether that reports `0x02010000` (slot 0, lock, keypad). If it does, the integration shows it as the master user locking, and the slot 0 attribution must be narrowed to unlock (tracked in dcat issues-5dko16f).
4. **Capacity test:** Set PINs on slot 3 and slot 800 via ZCL. Are both valid?
