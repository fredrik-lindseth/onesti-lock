# Onesti Lock — Agent Guidelines

Home Assistant custom integration for Onesti/Nimly smart locks via ZHA.
Identifies **who** unlocked the door and **how** — something no other ZHA integration does.

## Critical Rules

1. Domain is `onesti_lock`, NOT `nimly_pro`. Classes still use `Nimly` prefix (brand name).
2. Never remove content from docs/ — this is active reverse engineering. All credentials, API keys, and hardware identifiers are intentional research data.
3. The lock is a battery-powered Zigbee EndDevice that sleeps. All ZCL commands must account for timeouts and use the auto-wake mechanism in `coordinator.py`.
4. The Nimly response quirk (`IndexError` in zigpy) is expected. The command reaches the lock despite the error. Do not "fix" it.

## Architecture

```
NimlyCoordinator (one per lock)
  ├── Slot data (config entry options, persisted in .storage)
  ├── ZHA cluster access (_get_cluster walks ZHADeviceProxy → Device → CustomDeviceV2)
  ├── Auto-wake (_wake_lock sends lock command via ZHA entity on timeout, retries once)
  ├── PIN operations (set_pin, clear_pin, clear_slot via ZHA issue_zigbee_cluster_command)
  └── Activity sensor registration

Event listener (in __init__.py)
  ├── cluster.on_event("attribute_report") — catches custom attrid 0x0100
  ├── Decodes bitmap32: [user_slot, reserved, action, source]
  ├── Updates activity sensor (skips auto-lock to preserve "Kari låste opp med kode")
  └── Fires onesti_lock_activity HA event (always, including auto-lock)
```

## Source Map (byte 3 of attrid 0x0100)

Final correct values used in code (`__init__.py` `_SOURCE_MAP`):

| Byte | Source      |
| ---- | ----------- |
| 0x00 | zigbee      |
| 0x02 | keypad      |
| 0x03 | fingerprint |
| 0x04 | rfid        |
| 0x0A | auto        |

Session notes and stale plans contain earlier incorrect guesses. Code is authoritative.

## Key Files

| File                                           | Purpose                                                           |
| ---------------------------------------------- | ----------------------------------------------------------------- |
| `custom_components/onesti_lock/__init__.py`    | Setup, event listener, operation event decoding                   |
| `custom_components/onesti_lock/coordinator.py` | Slot storage, ZHA cluster wrapper, auto-wake, PIN operations      |
| `custom_components/onesti_lock/config_flow.py` | Config flow (device selection) + Options flow (PIN management UI) |
| `custom_components/onesti_lock/sensor.py`      | Slot sensors (3-12) + Activity sensor                             |
| `custom_components/onesti_lock/services.py`    | set_pin, clear_pin, set_name, clear_slot services                 |
| `custom_components/onesti_lock/const.py`       | Constants, source/action enums, supported models, slot ranges     |

## Gotchas

1. **ZHA device chain depth**: Clusters live on depth-2 object (CustomDeviceV2), not the ZHADeviceProxy. `_get_cluster()` walks .device chain up to 4 levels.
2. **Slot numbering**: Zigbee ZCL uses 0-199 (0-2 master, 3+ users). BLE uses 800-899. UI shows 10 sensors for slots 3-12.
3. **Options flow progress**: HA's `async_show_progress` requires step `foo_progress` with action `foo_progress` — then auto-calls `foo_progress_done` → `async_step_foo_result`.
4. **Activity sensor auto-lock suppression**: Auto-lock events fire the HA event but do NOT update the activity sensor, to avoid overwriting "Kari låste opp med kode" with "Auto-lås".
5. **CI/release workflows**: Both `.github/workflows/` files must reference `custom_components/onesti_lock/` (not `nimly_pro`).
6. **NimlyCoordinator is NOT DataUpdateCoordinator**: Custom pattern — event-driven, no polling. Intentional for battery-powered devices.

## Documentation Map

| Doc                                               | Content                                                                                      |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `README.md`                                       | User-facing: features, comparison, install, setup, supported devices                         |
| `docs/technical.md`                               | Integration internals: event decoding, coordinator, auto-wake, sleepy device, community refs |
| `docs/zigbee-protocol/zigbee-captures.md`         | Raw ZCL frames and verified protocol values (canonical for attrid 0x0100)                    |
| `docs/nimly-connect-app/app-architecture.md`      | iotiliti cloud ecosystem, white-label hierarchy, DoorlockTypes, cloud events                 |
| `docs/nimly-connect-app/reversing-notes.md`       | Nimly Connect APK reverse engineering, REST API, CAS error codes                             |
| `docs/nimly-connect-app/iotiliti-api-spec.yaml`   | OpenAPI spec for iotiliti cloud (reverse-engineered)                                         |
| `docs/nimly-ble-app/ble-protocol.md`              | BLE protocol from decompiled nimly BLE app (not used by integration)                         |
| `docs/connect-bridge/hardware-gateway.md`         | Connect Bridge hardware, network stack, firmware                                             |
| `docs/plans/2026-03-30-options-flow-ux-design.md` | Current: options flow UX design                                                              |

## Testing

```bash
pytest tests/ -v            # Run all tests
pytest tests/ -v -k event   # Run event-related tests
```

Tests mock ZHA entirely. No real hardware needed.

## Common Tasks

- **Add new source type**: Update `_SOURCE_MAP` in `__init__.py` + `SOURCE_*` in `const.py` + display string in `sensor.py`
- **Change slot range**: Update `SLOT_FIRST_USER`, `NUM_USER_SLOTS`, `MAX_SLOTS` in `const.py`
- **Add new lock model**: Add to `SUPPORTED_MODELS` in `const.py`
- **Add new service**: Follow pattern in `services.py`, add schema + handler, register in `async_setup_services`

## White-label Context

All locks are manufactured by **Onesti Products AS** with identical hardware/firmware.
The Zigbee Connect Module (ZMNC010) is the same across all brands.
The cloud platform (**iotiliti** by Safe4 Security Group) powers: Nimly, EasyAccess, Keyfree, Salus, Homely, Forebygg, Copiax, Conficare, and others.
See `docs/nimly-connect-app/app-architecture.md` for the full ecosystem.
