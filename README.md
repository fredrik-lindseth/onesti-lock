# Onesti Lock

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/fredrik-lindseth/nimly-touch-pro-integration.svg)](https://github.com/fredrik-lindseth/nimly-touch-pro-integration/releases)

Home Assistant integration for PIN code management and activity tracking on Onesti/Nimly smart locks via ZHA. Identifies **who** unlocked the door and **how** — something no other ZHA integration has achieved for these locks.

## Why this instead of the Nimly app?

The official Nimly ecosystem requires the **Nimly Connect Bridge** (gateway hub) and routes everything through **iotiliti cloud** — and even then, automations are locked behind an additional **"PRO Hub"** upsell. This integration replaces all of that with a direct, local Zigbee connection.

|                            | Nimly App (no hub)                | Nimly App + Connect Hub       | Nimly App + PRO Hub     | **This integration**                      |
| -------------------------- | --------------------------------- | ----------------------------- | ----------------------- | ----------------------------------------- |
| **Extra hardware**         | None (BLE only)                   | Connect Bridge (~1500 kr)     | PRO Hub (?)             | Any Zigbee coordinator                    |
| **Cloud dependency**       | Partial (BLE + cloud)             | Yes — iotiliti.cloud          | Yes — iotiliti.cloud    | **None — 100% local**                     |
| **Internet required**      | For remote features               | Yes                           | Yes                     | **No — fully offline**                    |
| **PIN management**         | Via BLE (phone must be near lock) | Via cloud → hub → lock        | Via cloud → hub → lock  | Via HA UI → ZHA → lock                    |
| **User identification**    | In-app history                    | Cloud event history           | Cloud event history     | **Real-time: "Kari låste opp med kode"** |
| **Automations**            | None                              | **None — "requires PRO Hub"** | Yes (via Nimly cloud)   | **Full HA automations**                   |
| **Digital keys**           | BLE unlock (nearby)               | Remote unlock via cloud       | Remote unlock via cloud | HA lock entity (local)                    |
| **OTP (one-time codes)**   | No                                | Yes (cloud-managed)           | Yes (cloud-managed)     | Planned (set_pin + auto-clear)            |
| **RFID enrollment**        | Via BLE scan mode                 | Via cloud → hub               | Via cloud → hub         | Not yet (needs BLE)                       |
| **Fingerprint enrollment** | Via BLE scan mode                 | Via cloud → hub               | Via cloud → hub         | Not yet (needs BLE)                       |
| **Cost**                   | Free app                          | Hub + cloud account           | Hub + PRO Hub + cloud   | **Free and open source**                  |
| **Privacy**                | Events to cloud                   | All events to AWS             | All events to AWS       | **Everything stays local**                |

**In short:** The official Nimly setup charges for three tiers of hardware just to get automations — and still routes everything through their cloud. This integration gives you PIN management, real-time user identification, and full Home Assistant automations with zero cloud dependency, zero extra hardware cost, and zero internet requirement.

## About the Nimly/Onesti lock family

All locks in this ecosystem — Nimly Touch Pro, Nimly Code, EasyCodeTouch, EasyFingerTouch, and others — are manufactured by **Onesti Products AS**. They are the same hardware with different branding. The **Zigbee Connect Module** (ZMNC010) is a separate add-on sold independently and is identical across all models.

The cloud platform behind these locks is **iotiliti**, owned by Safe4 Security Group. It powers a wide range of white-label brands: Nimly, EasyAccess, Keyfree (Sweden), Salus (UK), Homely, Forebygg, Copiax, Conficare, and others. The Connect Bridge (gateway hub) is also white-labeled — sold as "EasyAccess Connect Bridge", manufactured by Develco/Squid.Link. This is primarily a **B2B platform** sold to security companies, housing cooperatives, and smart home providers who rebrand it for their customers. The consumer brand "Nimly" is just one of many frontends to the same underlying system.

## Zigbee limitations of these locks

If you are choosing a smart lock specifically for Home Assistant, there are easier options. But if you already have a Nimly/Onesti lock, this integration makes the best of it. These are the real Zigbee limitations you should be aware of:

1. **Not a standard Zigbee Door Lock.** The lock uses custom cluster attributes (0x0100, 0x0101) that are not in the ZCL specification. Standard ZHA and Zigbee2MQTT integrations will show lock/unlock state, but cannot decode _who_ unlocked or _how_ — you just get a generic state change. This integration exists specifically to solve that.

2. **Battery-powered sleepy EndDevice.** The lock sleeps aggressively to preserve battery. Zigbee commands — especially `set_pin` — frequently timeout because the radio is not listening. You have to wake the lock first (press the keypad or trigger a lock/unlock). This integration auto-retries with a wake cycle on timeout, but it is inherently less reliable than mains-powered locks that are always listening.

3. **Malformed ZCL responses.** PIN commands reach the lock and execute, but the lock returns a broken response that crashes zigpy's ZCL parser (`IndexError`). The integration catches the error and assumes success, but there is no programmatic confirmation that a PIN was actually set. You must verify by testing the code on the keypad.

4. **No Zigbee slot querying.** The lock does not reliably respond to "get current PIN slots" queries. Slot state is tracked optimistically (locally) after set/clear commands, which means it can drift from reality if PINs are changed via the physical keypad or the BLE app.

5. **RFID and fingerprint enrollment require BLE.** There are no Zigbee commands to enroll new RFID tags or fingerprints — this can only be done via the Nimly BLE app or the cloud hub. The integration can detect RFID and fingerprint unlock events, but cannot manage those credentials.

6. **Placeholder manufacturer code.** The Connect Module identifies itself with manufacturer code `0x1234`, which is not registered with the Zigbee Alliance. This suggests the Zigbee implementation was not a high priority for Onesti — it works, but it was not built to integrate cleanly with the broader Zigbee ecosystem.

## What works

- **"Kari låste opp med kode"** — activity sensor identifies user and method (keypad, RFID, manual, auto-lock)
- **PIN code management** — set and clear PIN codes via UI (Settings → Configure) or services
- **Slot→name mapping** — "Slot 4: Kari (PIN aktiv)" persisted across restarts
- **Options flow UI** — manage PINs without Developer Tools (Norwegian + English)
- **Slot sensors** — 10 sensor entities showing who has access
- **HA events** — `onesti_lock_activity` event fired for automations ("send notification when someone unlocks")

## Known limitations

- **PIN verification** — Nimly returns a malformed ZCL response causing `IndexError` in zigpy. The command reaches the lock, but we can't confirm success programmatically. Test the code on the keypad.

## Supported devices

All Onesti Products AS locks with Zigbee Connect Module:

| Zigbee model     | Brand name                 | Status    |
| ---------------- | -------------------------- | --------- |
| NimlyPRO         | Nimly Touch Pro            | Verified  |
| NimlyPRO24       | Nimly Touch Pro 24         | Supported |
| easyCodeTouch_v1 | EasyAccess / EasyCodeTouch | Supported |
| EasyCodeTouch    | EasyAccess                 | Supported |
| EasyFingerTouch  | EasyAccess                 | Supported |

These are all the same hardware with different branding.

## Installation

### Via HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/fredrik-lindseth/nimly-touch-pro-integration` as Integration
3. Install "Onesti Lock"
4. Restart Home Assistant

### Manual

1. Copy `custom_components/onesti_lock` to your `config/custom_components/`
2. Restart Home Assistant

## Setup

1. **Settings → Devices & Services → Add Integration → Onesti Lock**
2. Select your lock from the list
3. Done — slot sensors and activity sensor are created automatically

**Prerequisite:** ZHA must be configured and the lock paired.

## Managing PIN codes

### Via UI (recommended)

**Settings → Devices & Services → Onesti Lock → Configure**

Menu options:

- **Sett PIN-kode** — select slot, enter name and 4-8 digit code
- **Fjern PIN-kode** — select active user to remove
- **Vis brukerslots** — overview of all slots

### Via services

```yaml
service: onesti_lock.set_pin
data:
  slot: 3 # User slots: 3-199 (0-2 reserved for master codes)
  name: "Ola"
  code: "5478"
```

| Service                  | Description                                 |
| ------------------------ | ------------------------------------------- |
| `onesti_lock.set_pin`    | Set PIN code with name for a slot           |
| `onesti_lock.clear_pin`  | Remove PIN code from a slot                 |
| `onesti_lock.set_name`   | Change slot name without changing PIN       |
| `onesti_lock.clear_slot` | Remove all credentials and name from a slot |

## Entities

Per configured lock:

- `sensor.*_slot_3` through `sensor.*_slot_12` — shows slot occupant ("Ola" or "Ledig"), with `has_pin` and `has_rfid` attributes
- `sensor.*_siste_aktivitet` — last lock activity ("Kari låste opp med kode", "Auto-lås")

## Important: Slot numbering

Per the Nimly/EasyAccess manual:

- **Slots 0-2**: Reserved for master codes (programming codes)
- **Slots 3-199**: User codes
- **PIN entry**: code followed by `#` on the keypad

The default factory master code is `123`. **Change it immediately** — anyone with the manual can use it.

## Important: Lock must be awake

These locks are battery-powered and sleep. The integration auto-wakes the lock on timeout (sends a lock command, waits, retries), but if that also fails: press any key on the keypad, then retry within 5 seconds.

## Technical details

See [docs/technical.md](docs/technical.md) for implementation details — how user identification works, why standard ZHA approaches fail, the Nimly response quirk, and alternatives considered.

## License

MIT License
