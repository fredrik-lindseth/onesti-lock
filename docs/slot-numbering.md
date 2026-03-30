# Slot numbering — known facts and unknowns

Onesti locks store user credentials (PIN codes, RFID tags, fingerprints) in numbered slots. The numbering differs between access methods.

## Known (verified)

### Zigbee ZCL (DoorLock cluster 0x0101)

| Slot range | Purpose | Source |
|-----------|---------|--------|
| 0 | Master PIN (factory: 123) | Verified: `attrid 0x0100` reports `user_slot=0` on master code unlock |
| 1-2 | Additional master codes | Per Nimly manual: "User slot 001 and 002 are reserved for more master codes" |
| 3-999 | User codes, RFID tags, fingerprints | Per manual. Slots 3-4 verified via `attrid 0x0100` events |

ZCL commands that use slot numbers:
- `set_pin_code` (0x0005): `user_id` = slot number
- `get_pin_code` (0x0006): `user_id` = slot number
- `clear_pin_code` (0x0007): `user_id` = slot number
- `attrid 0x0100` (operation event): byte 0-1 = slot number used

### BLE ekey protocol

Decompiled from `easyaccess.ekey.app` v1.5.1 (see `docs/nimly-ble-app/ble-protocol.md`):

| Slot range | Purpose | Source |
|-----------|---------|--------|
| 0 | Master PIN | Decompiled code |
| 800-899 | User PINs | Decompiled code (`PinCodeSet` 0x52, `slotNumber` uint16 LE) |

Example: setting PIN "8832" on BLE slot 803 sends `23 03 04 38 38 33 32` (slot 803 little-endian + length + ASCII).

### Cloud API (iotiliti)

The cloud API (`POST /devices/{id}/access`) uses abstract user IDs, not raw slot numbers. The gateway translates between cloud users and ZCL slot numbers internally.

### Confirmed facts

- **PIN codes survive re-pairing.** PIN 2510 set via ZHA (slot 4) still worked after the lock was removed from ZHA and paired with the Connect Bridge hub. Storage is local on the lock. (Tested 2026-03-30.)
- **RFID uses the same slot numbering as ZCL.** RFID tag on slot 1 reported `user_slot=1` in `attrid 0x0100`. (Tested 2026-03-30.)
- **Fingerprint uses the same slot numbering as ZCL.** Fingerprint on slot reported correctly in `attrid 0x0100`. (Tested 2026-03-30.)

## Unknown (not yet verified)

### Is BLE slot 800 the same as Zigbee slot 3?

**Hypothesis:** BLE slots 800-899 and ZCL slots 3+ refer to the same physical storage but with different offsets.

**Alternative:** They may be separate storage areas in firmware.

**To verify:** Set a PIN via BLE on slot 800, unlock with it, check if `attrid 0x0100` reports slot 3 or slot 800.

### Cloud API slot assignment

When the cloud API receives a new PIN, the gateway picks a slot automatically. We don't know which slot it picks or whether it coordinates with BLE numbering.

### Fingerprint and RFID slot ranges via BLE

The BLE protocol has `FingerprintClear` (0x58) and `RfidCodeClear` (0x55) with `slotNumber` parameters. The numbering for these has not been mapped.

## Current implementation

```python
# const.py
MAX_SLOTS = 1000       # ZCL slots 0-999 (per manual)
SLOT_FIRST_USER = 3    # First user slot
NUM_USER_SLOTS = 10    # UI shows slots 3-12
```

- **Options flow**: shows slots 3-12 in dropdown for PIN management
- **Name slot**: any slot number (0-999) can be named for RFID/fingerprint identification
- **Sensors**: 10 slot sensors (3-12), showing name and PIN status
- **Event decoding**: `attrid 0x0100` bytes 0-1 give the slot number, always in ZCL numbering regardless of how the credential was enrolled

## Verification plan

To resolve remaining unknowns:

1. **BLE/Zigbee cross-test:** Set PIN via BLE on slot 800. Unlock. Check `attrid 0x0100` — does it report slot 3 or slot 800?
2. **Cloud/Zigbee cross-test:** Set PIN via Nimly Connect app. Unlock. Check which slot `attrid 0x0100` reports.
3. **Slot 1-2 test:** Try `set_pin_code` on slots 1 and 2 via ZCL. Does the lock accept or reject?
4. **Capacity test:** Set PINs on slot 3 and slot 800 via ZCL. Are both valid?
