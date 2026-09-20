# Onesti Lock: agent guidelines

Home Assistant custom integration for Onesti/Nimly smart locks via ZHA. It
tells **who** unlocked the door and **how**. ZHA's stock quirk decodes the same attribute
only into raw numbers.

## Critical rules

1. The domain is `onesti_lock`, NOT `nimly_pro`. Our own classes and types follow it (`Onesti*`); `Nimly` is kept only where it means the vendor's brand, such as model strings and the app docs.
2. Credentials, API keys and secrets do NOT go in git. They belong in `secrets.md` (gitignored). Docs hold API URLs and technical references only, never secrets.
3. The lock is a battery-powered Zigbee EndDevice that sleeps. Every ZCL command goes through `ZhaLockTransport.send()` in `zha.py`, which handles the timeout and the auto-wake, and `send()` calls `cluster.command()` on the zigpy cluster directly. It must never go through ZHA's `issue_zigbee_cluster_command` service: Home Assistant records every `call_service` event with its data, so the service writes each PIN to the recorder in clear text. `tests_ha/test_pin_canary.py` checks for that. The direct call is why the transport looks more involved than the official API; do not "simplify" it back.
4. The Nimly response quirk (`IndexError` when the lock's answer is read) is expected on HA 2025.x. The command reaches the lock despite the error, so `send()` counts it as delivered. Do not "fix" it. The source is zha 0.0.x reading `response[1]` from a one-field Set PIN Code Response, fixed in zha 2.x; see "Nimly response quirk" in `docs/technical.md`.
5. The repo is public and written in English: code, comments, docs and commit messages. Work is tracked outside the repo, so no tracker ids or tracker names in files or commits. GitHub issue numbers (#6) are fine.
6. Vendor manuals are the source for slot rules and lock behaviour. Run `python3 scripts/fetch_manuals.py` once, then read the `.txt` extracts in `docs/manuals/`. The same script fetches the vendor's 2021 Zigbee spec, two 2021 Zigbee sniffs, a Z2M log and a ZHA diagnostics dump plus debug log from a Code Pro nobody here owns; `docs/zigbee-protocol/zigbee-captures.md` says what each of them answers. The files are gitignored, and `docs/manuals/README.md` lists what exists and where it came from. `pdftotext` drops footnotes from some of the PDFs, so render the page before concluding that a sentence is not there.
   - The same README's "Living sources" table is the archive of what other people have written: every forum thread, every GitHub issue and PR in the four upstream projects, the converter and quirk sources, and the vendor's pages and app listings. `python3 scripts/fetch_manuals.py --living` refetches them all, says which ones grew since last time, and writes the new date and size into the table, so `git diff` on that file is the answer to "what is new". `--check` reports without writing. Read the archive before searching the web again, and say in `docs/community-reports.md` what the reading found.

## Architecture

Three layers, each described in full in `docs/technical.md`; the file names below are the map.

- **Entry lifecycle and ZHA access**: `__init__.py` (setup, migration, services, ZHA watch, repair issue), `zha.py` (`ZhaLockTransport`: cluster lookup, `send()` and its `SendOutcome`, `wake()`, wake echo, capability read), `entity.py` (the device and unique ids, keyed on the entry id). Sections "Reaching the lock through ZHA", "Sending commands" and "Auto-wake mechanism".
- **Coordinator, events and sensors**: `coordinator.py` (one `OnestiCoordinator` per lock on `entry.runtime_data`, slot storage in `entry.options`, PIN operations, capabilities), `events.py` (attrid 0x0100 decoding, the two zigpy listener hooks, the system-lock rule), `sensor.py` (slot row and restored activity sensor). Sections "How user identification works", "Listening for reports" and "Coordinator pattern".
- **BLE library**: `ble/` (protocol, crypto, client; never run against a lock) and `bluetooth.py`, which nothing imports yet. Layers and the rules the code keeps are in `docs/nimly-ble-app/ble-library.md`; the Home Assistant side is "Reaching the lock over Bluetooth" in `docs/technical.md`.

`SOURCE_MAP` in `events.py` is the canonical decoder of the source byte in attrid 0x0100; `docs/zigbee-protocol/zigbee-captures.md` has the table with what verified each value. Session notes and old plans contain earlier wrong guesses. The code is authoritative.

## Key files

| File                                           | Purpose                                                                                                          |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `custom_components/onesti_lock/__init__.py`    | Services registered in async_setup, migration, entry setup/unload, repair issue, ZHA watch, update listener      |
| `custom_components/onesti_lock/coordinator.py` | Slot storage, PIN operations, reserved-slot guard, lock capabilities                                             |
| `custom_components/onesti_lock/zha.py`         | All ZHA/zigpy internals: gateway lookup, chain walk, `ZhaLockTransport` (send, wake, wake echo, capability read) |
| `custom_components/onesti_lock/bluetooth.py`   | Home Assistant Bluetooth and bleak-retry-connector: find the lock by its 0xFD00 advertisement, connect, open a `ble` Session; unused so far |
| `custom_components/onesti_lock/events.py`      | Operation event decoding, system-lock rule, event listener (no HA imports)                                       |
| `custom_components/onesti_lock/config_flow.py` | Config flow (device selection, discovery, reconfigure) + Options flow (PIN management UI, reserved-slots setting) |
| `custom_components/onesti_lock/entity.py`      | OnestiEntity and the device every entity hangs on: keys, model, serial number, link to ZHA's device              |
| `custom_components/onesti_lock/sensor.py`      | Slot sensor row that follows `reserved_slots` + restored Activity sensor                                         |
| `custom_components/onesti_lock/services.py`    | set_pin, clear_pin, set_name, clear_slot; lock picked by device_id or ieee                                       |
| `custom_components/onesti_lock/services.yaml`  | Service fields, including the device selector                                                                    |
| `custom_components/onesti_lock/pin_rules.py`   | Slot/PIN validation, reserved slots, PIN length floor (pure logic, no HA imports)                                |
| `custom_components/onesti_lock/redact.py`      | Masks digit runs in error text before it is logged (pure logic, no HA imports)                                   |
| `custom_components/onesti_lock/const.py`       | Constants, source/action enums, known models, slot ranges, wake echo window                                      |
| `custom_components/onesti_lock/localize.py`    | Runtime string lookup (reads the `common` section of translations/*.json)                                        |
| `custom_components/onesti_lock/strings.json`   | English source for every string; identical to `translations/en.json`                                             |
| `custom_components/onesti_lock/icons.json`     | Entity and service icons, keyed by translation key; no entity sets `_attr_icon`                                  |
| `custom_components/onesti_lock/ble/`           | BLE protocol library, unused by the integration so far; modules, API, fake lock and `scripts/ble_cli.py` in `docs/nimly-ble-app/ble-library.md` |
| `tools/esphome/`                               | ESPHome firmware for the BLE debug proxy by the door; `tools/esphome/README.md` covers flashing and reading it    |
| `blueprints/automation/`                       | Blueprints users import by hand; HACS never updates imported copies                                              |
| `scripts/release_publish.py`                   | The release state machine: deterministic ZIP, tag, draft, attestation check, publish (see Releasing)             |
| `.github/workflows/release.yml`                | Only on a manifest change plus the version gate: runs CI for the candidate SHA, then builds, attests and publishes through `release_publish.py` |
| `SECURITY.md`                                  | How a user verifies the ZIP HACS installed; the release body links here                                         |
| `.github/ISSUE_TEMPLATE/`                      | Bug report and new lock model forms                                                                              |

## Gotchas

1. **ZHA device chain depth**: clusters live on the depth-2 object (CustomDeviceV2), not on the ZHADeviceProxy. `zha.py` walks the `.device` chain up to 4 levels, in one place used by both the coordinator and the config flow.
2. **Slot numbering**: Zigbee ZCL uses 0-999. Slot 0 is master on every model. Slots 1-2 are master on Touch Pro, PRO and Code but user slots on Code Pro, and the model string cannot tell them apart (#5). The per-lock option `reserved_slots` (1-3, default 3, `pin_rules.first_user_slot`) is the floor for set_pin/clear_pin/clear_slot, enforced by the coordinator itself, and slot 0 is never written. What else follows from the setting (naming, the sensor row, the capacity ceiling, slot 0 in events, BLE's 800-899) is under "Current implementation" in `docs/slot-numbering.md`.
3. **Options flow progress**: when the `progress_task` passed to `async_show_progress` finishes, HA calls the same progress step again. Nothing named `*_done` is ever called for you. The step must check `task.done()` and, once it is, return `async_show_progress_done(next_step_id=...)`, which HA follows to that step (`set_pin_done` on success, back to the `set_pin` form with the error on failure). HA starts tasks eagerly, so a task can already be done on the first call, and the step it routes to then receives the submitted `user_input` again: form steps check a pending error before `user_input`, or they would send the command a second time.
4. **Activity sensor suppression**: system-initiated locking (source `auto`, and on NimlyCodePRO an `unattributed` lock with no user slot) fires the HA event but does NOT update the activity sensor, so "Kari unlocked with code" is not overwritten by "Auto-lock". A `zigbee` lock with no user is someone locking from HA and stays visible, except within `WAKE_ECHO_WINDOW_S` of our own auto-wake, which the lock reports the same way. The window is a guess nobody has measured on hardware.
5. **CI/release workflows**: `ci.yml` and `release.yml` in `.github/workflows/` must reference `custom_components/onesti_lock/` (not `nimly_pro`), and so must `COMPONENT`/`ASSET_NAME` in `scripts/release_publish.py` and `filename` in `hacs.json`. The ZIP HACS installs is named from the domain. `e2e.yml`, `hassfest.yml` and `validate.yml` are not part of the release gate.
6. **OnestiCoordinator is NOT a DataUpdateCoordinator**: it is a custom, event-driven pattern with no polling, on purpose for a battery-powered device.
7. **No user-facing strings in Python**: sensor states and options flow labels come from the `common` section of `translations/*.json` via `localize.py`, entity names and service errors from HA's own `entity`/`exceptions` sections, and `strings.json` stays identical to `translations/en.json`. `tests/test_no_hardcoded_language.py` and `test_strings_json_equals_en` in `tests/test_translations_files.py` fail the build otherwise.
8. **PIN length floor**: `pin_rules.PIN_LENGTH_SANE_MIN` (4) is the shortest PIN accepted, whatever the lock reports, because `redact.py` masks digit runs of that length and up. Lowering either one alone lets a PIN reach the log in clear text. Anything that logs an exception on the send path uses `redact_digits` and no `exc_info`: an error from zigpy or from building the frame can quote `pin_code`.
9. **Services live for the whole HA run**: they are registered in `async_setup` (hence `CONFIG_SCHEMA = cv.config_entry_only_config_schema`) and never removed on unload. Each call looks the lock up among loaded entries, by `device_id` (our own device, not the ZHA one), then `ieee`, and only falls back to the single lock when there is exactly one.
10. **Entry version**: config flow `VERSION = 2`, `MINOR_VERSION = 3`, so entries are at 2.3. A change to the stored shape bumps the minor version and gets a step in `async_migrate_entry`; an entry from a newer major version refuses to load. The stored shape includes the device and entity registries, which the 2.3 step rewrites (see "Slot data storage" in `docs/technical.md`).
11. **Repair issue `zha_internals`**: raised when ZHA runs and lists the lock, but the gateway, the Door Lock cluster or both listener hooks are missing. A zigpy without `on_event` is not a fault: the `add_listener` fallback covers it, and no release has neither. PIN writes still work then, but no activity arrives. The issue is per entry and removed when the listener registers or the entry unloads. A lock entirely missing from ZHA is not a repair issue: setup raises `ConfigEntryNotReady` and Home Assistant retries until the lock is back.
12. **Options writes trigger the update listener**: slot and capability writes go to `entry.options` too, so the listener reloads only when the first user slot moved, never on every PIN operation. `test_changing_reserved_slots_reloads` in `tests_ha/test_lifecycle.py` holds it.
13. **BLE library boundaries**: nothing in `ble/` imports `homeassistant`, `zigpy`, `voluptuous` or anything outside `ble/`, the layers import downwards only, and everything raised is a `BleError`; `tests/ble/test_package.py` enforces it, so a Home Assistant Bluetooth transport lives outside `ble/`. No PIN, key, challenge or payload in an exception message, a `repr` or a log call, and `Enrollment.to_dict()` holds the owner key and is a secret. `cryptography` and `bleak` come with Home Assistant and are NOT in `manifest.json`; `bluetooth_adapters` goes into the manifest in the same change that first imports `bluetooth.py`, and `tests/test_coordinator.py` and `tests_ha/test_bluetooth.py` hold the manifest to that (see "Reaching the lock over Bluetooth" in `docs/technical.md`).

## Documentation map

| Doc                                             | Content                                                                                       |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `README.md`                                     | User-facing: why this on top of ZHA, supported devices, install, setup, PIN management, links to the rest |
| `docs/user-guide.md`                            | Entities, actions, the event, multiple locks, automation examples, limitations, removal        |
| `docs/buying-a-lock.md`                         | The case for and against these locks, and every alternative checked                           |
| `docs/technical.md`                             | Integration internals: event decoding, ZHA access, sending, coordinator, auto-wake, Bluetooth, community refs |
| `docs/testing.md`                               | The test environments: unit stubs, the two HA venvs and their pins, Python floor, mypy, coverage gate, deploying to the real lock |
| `docs/zigbee-protocol/zigbee-captures.md`       | Raw ZCL frames and verified protocol values (canonical for attrid 0x0100)                     |
| `docs/zigbee-protocol/elife-module-spec.md`     | Onesti's own 2021 Zigbee spec for the module, and where it disagrees with what we measure     |
| `docs/zigbee-interrogation.md`                  | Runbook for asking the lock what it has (ZCL discovery, block by block), run by `scripts/interrogate_lock.sh` |
| `docs/nimly-connect-app/app-architecture.md`    | iotiliti cloud ecosystem, white-label hierarchy, DoorlockTypes, cloud events                  |
| `docs/nimly-connect-app/reversing-notes.md`     | Nimly Connect APK reverse engineering, REST API, white-label hosts                            |
| `docs/nimly-connect-app/iotiliti-api-spec.yaml` | OpenAPI spec for iotiliti cloud (reverse-engineered)                                          |
| `docs/nimly-ble-app/ble-protocol.md`            | BLE protocol from decompiled nimly BLE app (not used by integration)                          |
| `docs/nimly-ble-app/ble-auth-provisioning.md`   | Owner enrollment over BLE: local ECDH owner key, factory-reset default cred, cloud only for guests |
| `docs/nimly-ble-app/ble-library.md`             | The `ble/` library: layers, API, transports, Enrollment storage, errors, vector provenance, verified vs lock-only |
| `tools/esphome/README.md`                       | The BLE debug proxy: board and output power, secrets, USB-first flashing, core dumps, NVS counters, Active scanning |
| `docs/nimly-ble-app/unloc-app.md`               | The unloc app: same ekey BLE SDK, guest half only, how it scans and where its keys come from   |
| `docs/connect-bridge/hardware-gateway.md`       | Connect Bridge hardware, network stack, firmware                                              |
| `docs/hardware-generations.md`                  | Per-report log of model string, IEEE OUI, module name and firmware fields, one row per observed lock |
| `docs/community-reports.md`                     | Forum sweep: what owners measured, relayed or claimed about Bluetooth, firmware, battery and pairing |
| `docs/slot-numbering.md`                        | Slot numbering across Zigbee, BLE and cloud, verified and unverified                          |
| `docs/manuals/README.md`                        | Index of vendor manuals per model and brand, fetched locally by `scripts/fetch_manuals.py`    |
| `docs/debugging.md`                             | Troubleshooting guide for common problems                                                     |
| `docs/cloud-api-status.md`                      | Cloud API reversing status, what has been tried and what comes next                           |
| `docs/upstream-status.md`                       | Open threads in the ZHA quirk and the Z2M converter, and why we do not build dual transport   |
| `docs/feature-parity.md`                        | What the vendor app and hub do that we do not, what BLE could add, and what is never ours     |

## Testing

| Suite                        | Runs against                                                                          | Command                                         | Covers                                                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `tests/`                     | Stubbed `homeassistant`/`voluptuous`/`zigpy` from `tests/conftest.py`                 | `just test-unit`, `python3 scripts/ci_sim.py`   | Decoding, pin_rules, redact, coordinator, services, release flow, guards against PIN leaks and hardcoded language |
| `tests_ha/`                  | Real HA from `pytest-homeassistant-custom-component`, ZHA mocked at the gateway proxy, real zigpy | `just test-ha minimum`, `just test-ha current`  | Setup, migration, repair issue, ZHA reload, options flow, sensors, restore, services, transport, both zigpy listener hooks, Bluetooth lookup and connect on both stacks |
| `tests/test_version_sync.py` | `hacs.json`, `uv.lock`, prose in README/AGENTS/justfile/pyproject                     | part of `pytest tests/`                         | The minimum HA version agrees everywhere it is written                                              |
| `tests/ble/`                 | The `ble/` package alone, with `tests/ble/fake_lock.py` as the lock; no HA stubs needed | part of `pytest tests/`, or `pytest tests/ble`  | Every builder and parser, framing, crypto against NIST and app-executed vectors, session, owner login, full enrollment, package boundary |
| `tests/ble/java/`            | The app's decompiled crypto classes on a JDK (sources local only)                     | by hand, see `docs/nimly-ble-app/ble-library.md` | Prints the `executed` vectors in `tests/ble/crypto_vectors.py`; rerun when crypto code or vectors change |
| `tests_e2e/`                 | The release ZIP unpacked into an official HA container, no radio and no ZHA gateway    | `just e2e`, `just e2e target=minimum`           | That what HACS installs loads: component, seeded entry, the whole sensor row with translated names (`EXPECTED_ENTITIES` in `driver.py`), services, config and options flow, translations, and the blueprints validating and running. Not a word about talking to a lock; `tests_e2e/README.md` has the limits |

```bash
just test-unit              # tests/ in the unit group, as CI runs it
pytest tests/ -q            # any Python with pytest and cryptography; skips the bleak tests without bleak
python3 scripts/ci_sim.py   # ruff, then tests/ with homeassistant/voluptuous/zigpy blocked, as CI sees it
just test-ha minimum        # HA 2025.6.0, the version hacs.json promises (Python 3.13)
just test-ha current        # newest pinned HA (Python 3.14)
just mypy                   # mypy --strict over the whole component, 0 errors required
just coverage               # both suites, combined branch coverage held at 95 %
uv lock --check             # uv.lock matches pyproject.toml
```

Two rules the environments depend on: no test in `tests/` imports `homeassistant` or `voluptuous` without stubbing them (Home Assistant is not installed there, and `ci_sim.py` blocks the modules to prove it), and `tests/` and `tests_ha/` never share a venv, since the stubs would collide with the real package. Why each environment is pinned the way it is, how to move an HA target, the Python floor, where mypy runs and what the coverage gate combines are in `docs/testing.md`.

### Testing on the real lock

Fredrik's Home Assistant is reachable as `ssh ha-local`; `scripts/ha.sh` wraps the states, logs and service calls, and `scripts/deploy_ha.sh` does the deployment (`--dry-run deploy` prints every command, `deploy` backs up, copies, swaps, checks and restarts, `restore <tarball>` puts a backup back). Use it when something cannot be settled without a running instance. Tests do miss things here: `_attr_name` was once added as a harmless-looking fallback for entity names and silently disabled every translated name, since HA checks `_attr_name` before the translation key. Only a deployment showed it. Our entities there are `sensor.dorlasen_*`; `sensor.onesti_products_as_nimlypro_*` belong to the ZHA quirk. Restore afterwards unless the new version is the one meant to ship, and leave the backup tarball in place. What the script does in which order, and why, is in `docs/testing.md`.

## Releasing

`release.yml` runs only on a push to `main` that touches the manifest, and its version gate stops a run whose version is already published. Past both it calls `ci.yml` for the candidate SHA, waits for the whole graph and runs `scripts/release_publish.py`, where the flow lives; nothing else publishes a release. Why the workflows are split, why a release commit gets two CI runs, and what the path filter and the gate each catch, is in the comments at the top of `release.yml` and `ci.yml`. The candidate, the deterministic ZIP and idempotent re-runs are in the docstring of `release_publish.py`, and how a user verifies the result in `SECURITY.md`.

1. Run the gates CI runs: `just test-unit`, `python3 scripts/ci_sim.py`, `just test-ha minimum`, `just mypy`, `just coverage`, `uv lock --check`. `just e2e` runs on pull requests only and is not in the release gate.
2. Write the release note in `CHANGELOG.md` under `## [X.Y.Z]`, and mark the bullets a user would notice with `<!--short-->`. The marked ones become the release body; CI fails without them.
3. Bump `version` in `custom_components/onesti_lock/manifest.json`. It is the only version that counts: `pyproject.toml` holds a `0.0.0` placeholder that nothing reads, so leave it.
4. Commit as `chore: release X.Y.Z`, without `[skip ci]`. GitHub skips every workflow for a push whose head commit carries it, the release included. That happened with 1.3.0: the bump commit had `[skip ci]`, so the tag landed on the next push, a docs commit.
5. Push to `main` and wait for the run: `gh run watch -R fredrik-lindseth/onesti-lock`.
6. Check the result: `just release-verify vX.Y.Z`.

HACS installs `onesti_lock.zip` from the release (`zip_release` in `hacs.json`), not the tag's source tree, because a source tree cannot be attested. `hide_default_branch` is required alongside `zip_release`; without it, installing the default branch 404s because there is no ZIP there. Releases up to 1.3.0 predate the flow, and `FIRST_ZIP_VERSION` in `release_publish.py` says how they are treated.

## Release notes

HACS shows release notes inside Home Assistant, so the readers are people
running the lock, not developers browsing the repo. Lead with what such a user
would have noticed, then why. Leave documentation, tooling and refactors out
entirely.

Match the existing releases: `### Features`, `### Security`, `### Bug fixes`,
`### Breaking changes`, one bullet per change with a bold lead-in, and the
`**Full changelog**` compare link last. The release body is no longer written
by hand afterwards: `release_publish.py` builds it from the `<!--short-->`
bullets in `CHANGELOG.md` through `scripts/release_notes.py`, and appends a
Verification section with the commit, the sha256 and a link to `SECURITY.md`.
Editing the release on GitHub afterwards puts the text somewhere the repo
cannot review it, so change `CHANGELOG.md` instead.

## Common tasks

- **Add a source type**: update `SOURCE_MAP` in `events.py`, `SOURCE_*` in `const.py`, and `lock_<source>`/`unlock_<source>` in the `common` section of all four `translations/*.json` and `strings.json`.
- **Change the slot range**: the master/user split is the `reserved_slots` option, which a user changes in Settings, not in code. In `const.py`, `SLOT_FIRST_USER` is only its default, and `RESERVED_SLOTS_MIN`/`RESERVED_SLOTS_MAX` are its bounds (keep MIN at 1 so slot 0 stays protected). `NUM_USER_SLOTS` sets the list length and `MAX_SLOTS` the absolute ceiling. Update the model table in README and `docs/slot-numbering.md` in the same change.
- **Add a lock model**: add the model string to `SUPPORTED_MODELS` in `const.py` and the model table in README. The list is informational: the config flow offers any Onesti Products AS device with a Door Lock cluster and only logs a warning for an unknown model string.
- **Change the stored shape**: keep `DEFAULT_SLOT` in `const.py` as the whole slot schema, bump `MINOR_VERSION` in `config_flow.py`, and add a step to `async_migrate_entry` with a test in `tests_ha/test_lifecycle.py`.
- **Add a user-facing string**: add it to `strings.json`, all four `translations/*.json` (`en.json` identical to `strings.json`), and read it through `localize.py` or HA's `entity`/`exceptions`/`issues` sections.
- **Add a service**: follow the pattern in `services.py`, add a schema and a handler, and register it in `async_setup_services`.

## White-label context

Onesti Products AS makes all the locks, and the Connect Module (ZMNC010) is the same across every brand the iotiliti cloud runs (Nimly, EasyAccess, Keyfree, Salus, Homely and more; `docs/nimly-connect-app/app-architecture.md` has the hierarchy). The firmware on that module is not one thing, and an older EasyAccess generation on a Datek/Ember module answers "Datek Wireless" and is not covered: `docs/hardware-generations.md`.
