# Onesti Lock: agent guidelines

Home Assistant custom integration for Onesti/Nimly smart locks via ZHA. It
tells **who** unlocked the door and **how**, which no other ZHA integration does.

## Critical rules

1. The domain is `onesti_lock`, NOT `nimly_pro`. Classes still use the `Nimly` prefix (the brand name).
2. Credentials, API keys and secrets do NOT go in git. They belong in `secrets.md` (gitignored). Docs hold API URLs and technical references only, never secrets.
3. The lock is a battery-powered Zigbee EndDevice that sleeps. Every ZCL command must handle timeouts and go through the auto-wake mechanism in `coordinator.py`.
4. The Nimly response quirk (`IndexError` in zigpy) is expected. The command reaches the lock despite the error. Do not "fix" it.
5. The repo is public and written in English: code, comments, docs and commit messages. Work is tracked outside the repo, so no tracker ids or tracker names in files or commits. GitHub issue numbers (#6) are fine.
6. Vendor manuals are the source for slot rules and lock behaviour. Run `python3 scripts/fetch_manuals.py` once, then read the `.txt` extracts in `docs/manuals/`. The files are gitignored, and `docs/manuals/README.md` lists what exists and where it came from.

## Architecture

```
NimlyCoordinator (one per lock)
  ├── Slot data (config entry options, persisted in .storage)
  ├── ZHA cluster access (_get_cluster walks ZHADeviceProxy → Device → CustomDeviceV2)
  ├── Auto-wake (_wake_lock physically locks the door via the ZHA lock entity;
  │   why that works and a plain read does not is unverified; retries once)
  ├── PIN operations (set_pin, clear_pin, clear_slot via ZHA issue_zigbee_cluster_command)
  └── Activity sensor registration

Event listener (in __init__.py)
  ├── cluster.on_event("attribute_report"), catches custom attrid 0x0100
  ├── Decodes bitmap32: bits 0-15 user_slot (uint16 LE), bits 16-23 action, bits 24-31 source
  ├── Updates activity sensor (skips system-initiated locking, see gotcha 4)
  └── Fires onesti_lock_activity HA event (always, including auto-lock)
```

## Source map (byte 3 of attrid 0x0100)

The values the code uses (`_SOURCE_MAP` in `__init__.py`):

| Byte | Source                      |
| ---- | --------------------------- |
| 0x00 | zigbee                      |
| 0x02 | keypad                      |
| 0x03 | fingerprint                 |
| 0x04 | rfid                        |
| 0x05 | unattributed (NimlyCodePRO) |
| 0x0A | auto                        |

Session notes and old plans contain earlier wrong guesses. The code is authoritative.

## Key files

| File                                           | Purpose                                                                    |
| ---------------------------------------------- | -------------------------------------------------------------------------- |
| `custom_components/onesti_lock/__init__.py`    | Setup, event listener, operation event decoding                            |
| `custom_components/onesti_lock/coordinator.py` | Slot storage, ZHA cluster wrapper, auto-wake, PIN operations               |
| `custom_components/onesti_lock/config_flow.py` | Config flow (device selection) + Options flow (PIN management UI)          |
| `custom_components/onesti_lock/sensor.py`      | Slot sensors (3-12) + Activity sensor                                      |
| `custom_components/onesti_lock/services.py`    | set_pin, clear_pin, set_name, clear_slot services                          |
| `custom_components/onesti_lock/pin_rules.py`   | Slot/PIN validation from reported capabilities (pure logic, no HA imports) |
| `custom_components/onesti_lock/const.py`       | Constants, source/action enums, supported models, slot ranges              |
| `custom_components/onesti_lock/localize.py`    | Runtime string lookup (reads the `runtime` section of translations/*.json) |

## Gotchas

1. **ZHA device chain depth**: clusters live on the depth-2 object (CustomDeviceV2), not on the ZHADeviceProxy. `_get_cluster()` walks the `.device` chain up to 4 levels.
2. **Slot numbering**: Zigbee ZCL uses 0-999. Slot 0 is master on every model. Slots 1-2 are master on Touch Pro, PRO and Code but user slots on Code Pro, and the model string cannot tell them apart (#5). Details in `pin_rules.py` and `docs/slot-numbering.md`.
   - The per-lock option `reserved_slots` (1-3, default 3, `pin_rules.first_user_slot`) is the floor for set_pin/clear_pin/clear_slot. The coordinator itself enforces it, and slot 0 is never written.
   - Every slot 0-999 can be named.
   - Slot 0 events from keypad/fingerprint/rfid are the master user. From zigbee/auto/unattributed they are no user.
   - `set_pin` rejects slots at or above the lock's reported `NumberOfPINUsersSupported` (50 on NimlyPRO, read from the lock, and on NimlyCodePRO, from a device interview posted in a Zigbee2MQTT issue).
   - BLE uses 800-899. The UI shows 10 sensors for slots 3-12.
3. **Options flow progress**: HA's `async_show_progress` needs step `foo_progress` with action `foo_progress`, which then calls `foo_progress_done` → `async_step_foo_result` on its own.
4. **Activity sensor suppression**: system-initiated locking (source `auto`, and on NimlyCodePRO an `unattributed` lock with no user slot) fires the HA event but does NOT update the activity sensor, so "Kari unlocked with code" is not overwritten by "Auto-lock".
5. **CI/release workflows**: both `.github/workflows/` files must reference `custom_components/onesti_lock/` (not `nimly_pro`).
6. **NimlyCoordinator is NOT a DataUpdateCoordinator**: it is a custom, event-driven pattern with no polling, on purpose for a battery-powered device.
7. **No user-facing strings in Python**: sensor states and options flow labels come from the `runtime` section of `translations/*.json` via `localize.py`. Entity names and service errors go through HA's own `entity`/`exceptions` sections. `tests/test_no_hardcoded_language.py` fails the build if a Norwegian literal reappears. `strings.json` is the English source and must stay identical to `translations/en.json`.

## Documentation map

| Doc                                             | Content                                                                                       |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `README.md`                                     | User-facing: features, comparison, install, setup, supported devices                          |
| `docs/technical.md`                             | Integration internals: event decoding, coordinator, auto-wake, sleepy device, community refs  |
| `docs/zigbee-protocol/zigbee-captures.md`       | Raw ZCL frames and verified protocol values (canonical for attrid 0x0100)                     |
| `docs/nimly-connect-app/app-architecture.md`    | iotiliti cloud ecosystem, white-label hierarchy, DoorlockTypes, cloud events                  |
| `docs/nimly-connect-app/reversing-notes.md`     | Nimly Connect APK reverse engineering, REST API, CAS error codes                              |
| `docs/nimly-connect-app/iotiliti-api-spec.yaml` | OpenAPI spec for iotiliti cloud (reverse-engineered)                                          |
| `docs/nimly-ble-app/ble-protocol.md`            | BLE protocol from decompiled nimly BLE app (not used by integration)                          |
| `docs/connect-bridge/hardware-gateway.md`       | Connect Bridge hardware, network stack, firmware                                              |
| `docs/slot-numbering.md`                        | Slot numbering across Zigbee, BLE and cloud, verified and unverified                          |
| `docs/manuals/README.md`                        | Index of vendor manuals per model and brand, fetched locally by `scripts/fetch_manuals.py`    |
| `docs/debugging.md`                             | Troubleshooting guide for common problems                                                     |
| `docs/cloud-api-status.md`                      | Cloud API reversing status, what has been tried and what comes next                           |
| `docs/upstream-status.md`                       | Open threads in the ZHA quirk and the Z2M converter, and why we do not build dual transport   |

## Testing

```bash
pytest tests/ -v            # Run all tests
pytest tests/ -v -k event   # Run event-related tests
```

Tests mock ZHA entirely, so no hardware is needed. Home Assistant is not
installed here, and CI installs only `ruff` and `pytest`, so no test may import
`homeassistant` or `voluptuous` without stubbing them.
`tests/test_coordinator_behavior.py` has the harness that runs real coordinator
code under stubs. `python3 scripts/ci_sim.py` runs the suite with those modules
blocked, which is the only way to catch a stray import before CI does.

### Testing on the real lock

Fredrik's Home Assistant is reachable as `ssh ha-local` (the SSH add-on, so
`/config` is the HA config directory). Use it when something cannot be settled
without a running instance. Tests do miss things here. `_attr_name` was once
added as a harmless-looking fallback for entity names and silently disabled
every translated name, since HA checks `_attr_name` before the translation key.
Only a deployment showed it.

Back up first, then copy into a staging directory and swap, so a failed
transfer never leaves a half-written integration behind:

```bash
ssh ha-local 'cd /config/custom_components && tar czf /config/onesti_lock-backup-$(date +%Y%m%d-%H%M%S).tar.gz onesti_lock'
ssh ha-local 'rm -rf /config/custom_components/onesti_lock.new && mkdir -p /config/custom_components/onesti_lock.new'
scp -r custom_components/onesti_lock/. ha-local:/config/custom_components/onesti_lock.new/
ssh ha-local 'rm -rf /config/custom_components/onesti_lock && mv /config/custom_components/onesti_lock.new /config/custom_components/onesti_lock'
```

Strip `__pycache__` from the copy first. Then run `ha core check` and `ha core
restart`, and read the result. States and entity names come back through the
Supervisor proxy, which needs no token of its own:

```bash
ssh ha-local 'curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/core/api/states'
ssh ha-local 'ha core logs | grep -i onesti_lock'
```

The integration's own entities are `sensor.dorlasen_*` on that instance. The
`sensor.onesti_products_as_nimlypro_*` entities belong to the ZHA quirk, not
to us.

Restore afterwards unless the new version is the one meant to ship, and
restart once more:

```bash
ssh ha-local 'cd /config/custom_components && rm -rf onesti_lock && tar xzf /config/onesti_lock-backup-<timestamp>.tar.gz'
```

Leave the backup tarball in place. Slot names and PIN status live in
`.storage`, not in the integration directory, so they survive a swap either
way.

## Release notes

HACS shows release notes inside Home Assistant, so the readers are people
running the lock, not developers browsing the repo. Lead with what such a user
would have noticed, then why. Leave documentation, tooling and refactors out
entirely.

Match the existing releases: `### Features`, `### Security`, `### Bug fixes`,
`### Breaking changes`, one bullet per change with a bold lead-in, and the
`**Full changelog**` compare link last. On push, the release workflow builds a
body from commit subjects. Treat it as a draft and replace it.

## Common tasks

- **Add a source type**: update `_SOURCE_MAP` in `__init__.py`, `SOURCE_*` in `const.py`, and `lock_<source>`/`unlock_<source>` in the `runtime` section of all four `translations/*.json` and `strings.json`.
- **Change the slot range**: the master/user split is the `reserved_slots` option, which a user changes in Settings, not in code. In `const.py`, `SLOT_FIRST_USER` is only its default, and `RESERVED_SLOTS_MIN`/`RESERVED_SLOTS_MAX` are its bounds (keep MIN at 1 so slot 0 stays protected). `NUM_USER_SLOTS` sets the list length and `MAX_SLOTS` the absolute ceiling. Update the model table in README and `docs/slot-numbering.md` in the same change.
- **Add a lock model**: add it to `SUPPORTED_MODELS` in `const.py`.
- **Add a service**: follow the pattern in `services.py`, add a schema and a handler, and register it in `async_setup_services`.

## White-label context

Onesti Products AS makes all the locks, with identical hardware and firmware,
and the Zigbee Connect Module (ZMNC010) is the same across all brands. The
cloud platform, iotiliti by Safe4 Security Group, developed by Neurosys in
Poland, runs Nimly, EasyAccess, Keyfree, Salus, Homely, Forebygg, Copiax,
Tekam, Folklarm, Tryg Smart, Safe4 Care, LF, Larmify and others. See
`docs/nimly-connect-app/app-architecture.md` for the full ecosystem.
