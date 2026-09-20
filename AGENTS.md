# Onesti Lock: agent guidelines

Home Assistant custom integration for Onesti/Nimly smart locks via ZHA. It
tells **who** unlocked the door and **how**. ZHA's stock quirk decodes the same attribute
only into raw numbers.

## Critical rules

1. The domain is `onesti_lock`, NOT `nimly_pro`. Our own classes and types follow it (`Onesti*`); `Nimly` is kept only where it means the vendor's brand, such as model strings and the app docs.
2. Credentials, API keys and secrets do NOT go in git. They belong in `secrets.md` (gitignored). Docs hold API URLs and technical references only, never secrets.
3. The lock is a battery-powered Zigbee EndDevice that sleeps. Every ZCL command must handle timeouts and go through `ZhaLockTransport.send()` in `zha.py`, which handles the timeout and the auto-wake.
4. The Nimly response quirk (`IndexError` when the lock's answer is read) is expected on HA 2025.x. The command reaches the lock despite the error, so `send()` counts it as delivered. Do not "fix" it. The source is zha 0.0.x's `issue_cluster_command` reading `response[1]` from a one-field Set PIN Code Response; zha 2.x reads the field by name, and so does `send()` (see `docs/technical.md`).
5. The repo is public and written in English: code, comments, docs and commit messages. Work is tracked outside the repo, so no tracker ids or tracker names in files or commits. GitHub issue numbers (#6) are fine.
6. Vendor manuals are the source for slot rules and lock behaviour. Run `python3 scripts/fetch_manuals.py` once, then read the `.txt` extracts in `docs/manuals/`. The same script fetches the vendor's 2021 Zigbee spec, two 2021 Zigbee sniffs, a Z2M log and a ZHA diagnostics dump plus debug log from a Code Pro nobody here owns; `docs/zigbee-protocol/zigbee-captures.md` says what each of them answers. The files are gitignored, and `docs/manuals/README.md` lists what exists and where it came from. `pdftotext` drops footnotes from some of the PDFs, so render the page before concluding that a sentence is not there.
   - The same README's "Living sources" table is the archive of what other people have written: every forum thread, every GitHub issue and PR in the four upstream projects, the converter and quirk sources, and the vendor's pages and app listings. `python3 scripts/fetch_manuals.py --living` refetches them all, says which ones grew since last time, and writes the new date and size into the table, so `git diff` on that file is the answer to "what is new". `--check` reports without writing. Read the archive before searching the web again, and say in `docs/community-reports.md` what the reading found.

## Architecture

```
__init__.py (entry lifecycle)
  ├── async_setup: registers the four services once, for all locks; never removed on unload
  ├── async_migrate_entry: 2.1 -> 2.2 strips has_rfid from stored slots;
  │   2.2 -> 2.3 stores the model in entry.data and rewrites device
  │   identifiers and entity unique ids from the IEEE to the entry id
  ├── async_setup_entry: coordinator on entry.runtime_data, sensor platform,
  │   event listener, ZHA watch, update listener, background capability read;
  │   ConfigEntryNotReady (retried by HA) when ZHA runs without the lock's IEEE
  ├── Event listener registration; on ZhaInternalsMissing an ERROR log and a
  │   repair issue (zha_internals_<entry_id>), deleted again on success or unload
  ├── ZHA watch: ConfigEntry.async_on_state_change on every ZHA entry; reloads
  │   this entry when ZHA comes back LOADED with a different Door Lock cluster
  └── Update listener: reloads only when reserved_slots moved the first user slot

OnestiCoordinator (coordinator.py, one per lock; OnestiConfigEntry = ConfigEntry[OnestiCoordinator])
  ├── entry.options: "slots" (name, has_pin per slot), "reserved_slots", "capabilities"
  ├── set_pin / clear_pin / clear_slot: refuse slots below first_user_slot(),
  │   one at a time (asyncio.Lock), local state changes only after a delivered send
  ├── Capabilities: async_refresh_capabilities reads until the lock answers once,
  │   then keeps the answer in entry.options["capabilities"]; rescheduled after
  │   every delivered command and every attribute report (radio awake)
  └── Activity sensor registration and slot listeners

ZhaLockTransport (zha.py, injected into the coordinator; tests pass a fake)
  ├── cluster(): find_door_lock_cluster via get_zha_gateway_proxy, then walks
  │   ZHADeviceProxy → Device → CustomDeviceV2
  ├── send(): cluster.command(id, **params) on that zigpy cluster, never ZHA's
  │   issue_zigbee_cluster_command service (HA records every call_service event
  │   with its data, PIN included); returns a SendOutcome and never raises:
  │   DELIVERED when the lock took the command, REJECTED with the ZCL status
  │   when it answered with a failure status, UNREACHED when nothing got
  │   through; on TimeoutError or zigpy DeliveryError wake() and retry once,
  │   any other Zigbee error is UNREACHED without waking; no tracebacks,
  │   messages pass through redact.py
  ├── SendOutcome: delivered, lock_answered (anything but UNREACHED, so the
  │   radio is awake right now) and error_key, the translation key the
  │   services and the options flow raise or show. A rejection is REJECTED
  │   with the status; duplicate code and memory full are told apart only
  │   for Set PIN Code's own response, where those status values mean that.
  │   The coordinator writes its own slot state only after DELIVERED, leaves
  │   the slot untouched on REJECTED and UNREACHED, and schedules a
  │   capability read whenever lock_answered
  ├── wake(): physically locks the door through ZHA's lock entity (found by
  │   zigbee connection among the devices of ZHA's config entries); why that
  │   works and a plain read does not is unverified
  ├── wake_echo_pending(): True for WAKE_ECHO_WINDOW_S (30 s) after a wake
  │   whose lock.lock call did not fail
  └── read_capabilities(): ZCL 0x0012/0x0017/0x0018 as a dict, None when the lock
      was not reached (so the read is repeated), {} when it answered without them

Event listener (events.py, no HA imports at module level)
  ├── Two hooks on coordinator.transport.cluster(), one handler behind both:
  │   cluster.on_event("attribute_report") where zigpy has it (0.91 and up),
  │   else a listener object via cluster.add_listener whose attribute_updated
  │   zigpy calls (HA 2025.6-2026.1 ship zigpy 0.80.1-0.90.0, no on_event);
  │   catches custom attrid 0x0100; ZhaInternalsMissing only without both
  ├── Decodes bitmap32: bits 0-15 user_slot (uint16 LE), bits 16-23 action, bits 24-31 source
  ├── Slot 0 from keypad/fingerprint/rfid is the master user, otherwise no user (None)
  ├── Updates activity sensor unless is_system_lock(decoded, wake_echo_pending) (gotcha 4)
  └── Fires onesti_lock_activity HA event (always, including auto-lock and wake echo)

OnestiEntity (entity.py, the base class of every sensor)
  ├── unique_id <entry_id>-<key>, device identifiers {(DOMAIN, entry_id)}: a
  │   replaced Connect Module changes the IEEE, the entry id it does not
  └── build_device_info: model from entry.data, serial_number = IEEE,
      connections {(CONNECTION_ZIGBEE, ieee)}, name "<model> (<last four)";
      via_device_id to ZHA's device where DeviceInfo has the field (HA
      2026.9 and up), where a connection is unique per config entry; below
      that the shared connection makes the two one device and there is no
      link to draw (HAS_VIA_DEVICE_ID in entity.py is the switch)

Sensors (sensor.py)
  ├── Slot row: range(first_user_slot, first_user_slot + NUM_USER_SLOTS); registry
  │   entries for slots that fell out of the row are removed on setup
  └── Activity: RestoreEntity with ExtraStoredData of the raw fields, so the last
      activity survives a restart; timestamp is UTC (dt_util.utcnow)

BLE library (ble/, imported only by bluetooth.py, which nothing uses yet; never run against a lock)
  ├── __init__.py: the public API; layers import downwards only (gotcha 13)
  ├── protocol/: wire format, no crypto, no I/O: Layer 1-3 framing, blobs,
  │   one builder per command, one parser per answer, advertisement, enums
  ├── crypto.py: secp256r1 ECDH and AES-128-CBC in the app's byte order
  ├── client/: Transport protocol (a Bluetooth stack implements it), Session
  │   (key exchange, one command at a time, events), owner login, enrollment
  └── errors.py: BleError tree, used by all three layers
```

## Source map (byte 3 of attrid 0x0100)

The values the code uses (`SOURCE_MAP` in `events.py`):

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
| `custom_components/onesti_lock/ble/`           | BLE protocol library, unused by the integration so far; layers and API in `docs/nimly-ble-app/ble-library.md`    |
| `ble/protocol/`                                | Wire format: `const`, `packet`, `blob`, `command`, `commands` (builders), `response`, `responses` (parsers), `advertisement` |
| `ble/crypto.py`                                | Key exchange, link and owner keys, owner challenge answer, AES in the app's two modes                            |
| `ble/client/`                                  | `transport` (the seam), `session`, `auth` (owner login), `enrollment` (factory-reset takeover, `Enrollment` storage form) |
| `tests/ble/fake_lock.py`                       | A lock played in software behind `Transport`; lists what it assumes about the real lock                           |
| `scripts/ble_cli.py`                           | Runs the BLE library against a real lock over bleak (`just ble`): scan to enroll, `--yes` for writes, redacted frame trace; see "Running it against a lock" in `ble-library.md` |
| `tools/esphome/ble-debug-proxy.yaml`           | ESPHome firmware for the BLE debug proxy by the door: 0xFD00 logging, persistent NVS diagnostics, core dump partition; `tools/esphome/README.md` covers flashing |
| `blueprints/automation/`                       | Blueprints users import by hand; HACS never updates imported copies                                              |
| `scripts/release_publish.py`                   | The release state machine: deterministic ZIP, tag, draft, attestation check, publish (see Releasing)             |
| `.github/workflows/release.yml`                | Only on a manifest change plus the version gate: runs CI for the candidate SHA, then builds, attests and publishes through `release_publish.py` |
| `SECURITY.md`                                  | How a user verifies the ZIP HACS installed; the release body links here                                         |
| `.github/ISSUE_TEMPLATE/`                      | Bug report and new lock model forms                                                                              |

## Gotchas

1. **ZHA device chain depth**: clusters live on the depth-2 object (CustomDeviceV2), not on the ZHADeviceProxy. `zha.py` walks the `.device` chain up to 4 levels, in one place used by both the coordinator and the config flow.
2. **Slot numbering**: Zigbee ZCL uses 0-999. Slot 0 is master on every model. Slots 1-2 are master on Touch Pro, PRO and Code but user slots on Code Pro, and the model string cannot tell them apart (#5). Details in `pin_rules.py` and `docs/slot-numbering.md`.
   - The per-lock option `reserved_slots` (1-3, default 3, `pin_rules.first_user_slot`) is the floor for set_pin/clear_pin/clear_slot. The coordinator itself enforces it, and slot 0 is never written.
   - Every slot 0-999 can be named.
   - Slot 0 events from keypad/fingerprint/rfid are the master user. From zigbee/auto/unattributed they are no user.
   - `set_pin` rejects slots at or above the lock's reported `NumberOfPINUsersSupported` (50 on NimlyPRO, read from the lock, and on NimlyCodePRO, from a device interview posted in a Zigbee2MQTT issue).
   - BLE uses 800-899. The sensor row is `NUM_USER_SLOTS` (10) slots from the first user slot, so 3-12 by default and 1-10 with one reserved slot. Changing `reserved_slots` reloads the entry and removes the sensors that fell out of the row.
3. **Options flow progress**: when the `progress_task` passed to `async_show_progress` finishes, HA calls the same progress step again. Nothing named `*_done` is ever called for you. The step must check `task.done()` and, once it is, return `async_show_progress_done(next_step_id=...)`, which HA follows to that step (`set_pin_done` on success, back to the `set_pin` form with the error on failure). HA starts tasks eagerly, so a task can already be done on the first call, and the step it routes to then receives the submitted `user_input` again: form steps check a pending error before `user_input`, or they would send the command a second time.
4. **Activity sensor suppression**: system-initiated locking (source `auto`, and on NimlyCodePRO an `unattributed` lock with no user slot) fires the HA event but does NOT update the activity sensor, so "Kari unlocked with code" is not overwritten by "Auto-lock". A `zigbee` lock with no user is someone locking from HA and stays visible, except within `WAKE_ECHO_WINDOW_S` of our own auto-wake, which the lock reports the same way. The window is a guess nobody has measured on hardware.
5. **CI/release workflows**: `ci.yml` and `release.yml` in `.github/workflows/` must reference `custom_components/onesti_lock/` (not `nimly_pro`), and so must `COMPONENT`/`ASSET_NAME` in `scripts/release_publish.py` and `filename` in `hacs.json`. The ZIP HACS installs is named from the domain. `e2e.yml`, `hassfest.yml` and `validate.yml` are not part of the release gate.
6. **OnestiCoordinator is NOT a DataUpdateCoordinator**: it is a custom, event-driven pattern with no polling, on purpose for a battery-powered device.
7. **No user-facing strings in Python**: sensor states and options flow labels come from the `common` section of `translations/*.json` via `localize.py` (`common` because hassfest rejects top-level keys outside HA's strings schema). Entity names and service errors go through HA's own `entity`/`exceptions` sections. `tests/test_no_hardcoded_language.py` fails the build if a Norwegian literal reappears. `strings.json` is the English source and must stay identical to `translations/en.json`.
8. **PIN length floor**: `pin_rules.PIN_LENGTH_SANE_MIN` (4) is the shortest PIN accepted, whatever the lock reports, because `redact.py` masks digit runs of that length and up. Lowering either one alone lets a PIN reach the log in clear text. Anything that logs an exception on the send path uses `redact_digits` and no `exc_info`: an error from zigpy or from building the frame can quote `pin_code`.
9. **Services live for the whole HA run**: they are registered in `async_setup` (hence `CONFIG_SCHEMA = cv.config_entry_only_config_schema`) and never removed on unload. Each call looks the lock up among loaded entries, by `device_id` (our own device, not the ZHA one), then `ieee`, and only falls back to the single lock when there is exactly one.
10. **Entry version**: config flow `VERSION = 2`, `MINOR_VERSION = 3`, so entries are at 2.3. A change to the stored shape bumps the minor version and gets a step in `async_migrate_entry`; an entry from a newer major version refuses to load. The stored shape is not only `entry.data` and `entry.options`: the 2.3 step also rewrites the device and entity registries, where identifiers and unique ids moved from the IEEE to the entry id.
11. **Repair issue `zha_internals`**: raised when ZHA runs and lists the lock, but the gateway, the Door Lock cluster or both listener hooks are missing. A zigpy without `on_event` is not a fault: the `add_listener` fallback covers it, and no release has neither. PIN writes still work then, but no activity arrives. The issue is per entry and removed when the listener registers or the entry unloads. A lock entirely missing from ZHA is not a repair issue: setup raises `ConfigEntryNotReady` and Home Assistant retries until the lock is back.
12. **Options writes trigger the update listener**: slot and capability writes go to `entry.options` too, so the listener compares the first user slot and reloads only when it moved. A listener that reloads on any change reloads after every PIN operation.
13. **BLE library boundaries**: nothing in `ble/` imports `homeassistant`, `zigpy` or `voluptuous`, and no relative import leaves `ble/`, not even for `redact.py`. Inside, `protocol/` imports neither `crypto.py` nor `client/`, and `crypto.py` not `client/`. Everything raised is a `BleError`. `tests/ble/test_package.py` enforces all of it. A Home Assistant Bluetooth transport therefore lives outside `ble/`.
    - No PIN, key, challenge or payload in an exception message, a `repr` or a log call, and no traceback in the log. Fields holding them are `repr=False`; `Enrollment.to_dict()` holds the owner key and must be stored and handled as a secret.
    - `cryptography` comes with Home Assistant and is NOT in `manifest.json`, where a pin could fight HA's. The tests get it from the `unit` group in `pyproject.toml`; keep `crypto.py` to API that both HA ends of the supported range ship.
    - `bluetooth.py` reads `bleak_retry_connector.BleakClientWithServiceCache` at call time: habluetooth swaps in its own wrapper, which routes through adapters and proxies, once Bluetooth is set up. The manifest names neither `bluetooth_adapters` nor a `bluetooth` matcher while nothing imports `bluetooth.py`; the dependency goes back in the change that first does (see `docs/technical.md`). Each HA group in `pyproject.toml` pins the Bluetooth stack of that release's bluetooth manifest, like zigpy.
    - Protocol values come from the decompiled app with the Java source named next to them. A value nobody could trace stays marked as a guess, and the vectors say where each one came from (`documented`, `derived`, `kat`, `executed`).

## Documentation map

| Doc                                             | Content                                                                                       |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `README.md`                                     | User-facing: why this on top of ZHA, supported devices, install, setup, PIN management, links to the rest |
| `docs/user-guide.md`                            | Entities, actions, the event, multiple locks, automation examples, limitations, removal        |
| `docs/buying-a-lock.md`                         | The case for and against these locks, and every alternative checked                           |
| `docs/technical.md`                             | Integration internals: event decoding, coordinator, auto-wake, sleepy device, community refs  |
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
pytest tests/ -q -k event   # Run event-related tests
uv lock --check             # uv.lock matches pyproject.toml
```

Tests mock ZHA entirely, so no hardware is needed. Home Assistant is not
installed for `tests/`: CI runs it through `just coverage-unit` in the uv group
`unit` (pytest, pytest-cov, pyyaml and `cryptography` for the BLE library), so
no test there may import `homeassistant` or `voluptuous` without stubbing them.
`tests/conftest.py` holds the one shared stub set and `load_component_module()`,
and `tests/test_coordinator_behavior.py` has the fake hass harness that runs
real coordinator code on top of it. `python3 scripts/ci_sim.py` runs the same
ruff check as CI and then the suite in the unit environment (`.venv-unit`
through uv, as `just test-unit`) with those modules blocked, which is the only
way to catch a stray import before CI does. It runs there and not in the
Python that started it because a Python without bleak skips the bleak tests,
and a run with skips is not CI's answer.

### Tests against real Home Assistant

`tests_ha/` loads the integration into a real Home Assistant from
`pytest-homeassistant-custom-component`, with ZHA mocked at the gateway proxy
(`conftest.py` explains how). It needs `just` and `uv`:

```bash
just test-ha minimum   # HA 2025.6.0, the version hacs.json promises (Python 3.13)
just test-ha current   # newest pinned HA (Python 3.14)
```

Each target has its own venv (`.venv-ha-minimum`, `.venv-ha-current`) and
its own dependency group in `pyproject.toml`, locked in `uv.lock`. The two
trees never share an environment: the stubs in `tests/conftest.py` would
collide with the real package. Each group also pins `zigpy` to exactly the
version that target's Home Assistant gets through `zha` (0.80.1 on minimum,
2.2.0 on current), because which listener hook a Door Lock cluster offers
changed with the version; `tests_ha/test_zigpy_listener.py` builds a real
cluster from it. Move the zigpy pin whenever the HA pin moves, and read the
new one out of that Home Assistant's `components/zha/manifest.json` and the
zha release's own dependencies. To move a target, change the plugin pin in
`pyproject.toml` (each plugin release pins one exact HA version), run `uv
lock`, and update `hacs.json` when the minimum moves. CI runs both targets.
`tests/test_version_sync.py` fails when `hacs.json`, the HA version the
`ha-minimum` group resolves to in `uv.lock`, and every HA version written out
in `README.md`, `AGENTS.md`, `justfile` or `pyproject.toml` disagree.

Development and CI run on the newest stable Python (`.python-version`). The
floor for the integration itself is the lowest Python its minimum HA runs on,
and `requires-python` and ruff's `target-version` follow that floor, not the
dev Python. CI compiles the integration on the floor as well. mypy is the one
exception; see below.

### Type checking

```bash
just mypy               # the whole component, 0 errors required
just mypy --no-incremental
```

`mypy --strict` covers all of `custom_components/onesti_lock`, `ble/` and
`bluetooth.py` included, and CI runs the same recipe as a step in the
`test-ha` job on `current`. The settings are `[tool.mypy]` in
`pyproject.toml`; `files` is set there, so `just mypy` takes no path.

It runs in the `ha-current` environment because that is the only one where
every import resolves at once: the real Home Assistant for `bluetooth.py`,
`zigpy` for `zha.py`, `bleak` and `cryptography` for `ble/`. That also
settles `python_version`, which is the dev Python and not the runtime floor,
unlike ruff's: mypy parses the Home Assistant it checks against, and the
current release has syntax the floor Python cannot read. The floor is proved
by the `compileall` step in CI instead. `mypy` itself is pinned in the
`ha-current` group.

Two rules the check enforces that are easy to undo by accident: every config
and options flow step annotates `user_input: dict[str, Any] | None = None`,
and `OnestiConfigEntry` rather than a bare `ConfigEntry` is the type in
`async_get_options_flow` and `OnestiCoordinator.__init__`, which is what
hassfest's `runtime-data` validator looks for. Objects from the `zha`
library, which is not installed for the check, are typed `Any` with a
comment; zigpy's own types (`zigpy.zcl.Cluster`) are used where they exist.

### Quality scale and the coverage gate

`custom_components/onesti_lock/quality_scale.yaml` is the self-declaration
against Home Assistant's Integration Quality Scale: every rule is `done`,
`todo` or `exempt` with a comment saying why. No tier is declared:
`manifest.json` has no `quality_scale` key, and the test only checks a tier's
rules once one is written there. hassfest does not validate the
file for custom integrations (`validate_iqs_file` returns early when the
integration is not core), so `tests/test_quality_scale.py` does it instead,
with the same rule list and schema hassfest uses for core. Solving a rule
means moving its status in the same change, not later: nothing else tracks
it. When the rule list upstream grows, copy the new list into the test, bump
the core commit written in its docstring and give the rule a status.

`just coverage` is the port the `test-coverage` rule stands on. It runs
`tests/` and `tests_ha` on current with coverage into separate data files,
then `coverage-gate` combines them and fails under 95 % branch coverage. Only
the combined number counts: each suite alone leaves code the other covers
(`ble/` is reached from `tests/` only, the HA lifecycle from `tests_ha` only).
CI runs the same three recipes, one job per suite and the gate in a job after
both, so a local `just coverage` is the same answer.

### Testing on the real lock

Fredrik's Home Assistant is reachable as `ssh ha-local` (the SSH add-on, so
`/config` is the HA config directory). Use it when something cannot be settled
without a running instance. `scripts/ha.sh` wraps the common calls (`states`,
`state`, `logs`, `grep`, `call`, `debug`) so a session does not re-type the SSH
and curl boilerplate; it uses the same `ssh ha-local` alias. Tests do miss things here. `_attr_name` was once
added as a harmless-looking fallback for entity names and silently disabled
every translated name, since HA checks `_attr_name` before the translation key.
Only a deployment showed it.

`scripts/deploy_ha.sh` does the deployment itself:

```bash
scripts/deploy_ha.sh --dry-run deploy   # print every command, run none of them
scripts/deploy_ha.sh deploy             # back up, copy, swap, check, restart, verify
scripts/deploy_ha.sh restore <tarball>  # put a backup back and restart
```

`deploy` writes the backup tarball to `/config/onesti_lock-backup-<timestamp>.tar.gz`
and reads it back before it touches anything else, copies the working tree into
`onesti_lock.new` without `__pycache__`, proves that staging directory is
complete (manifest, `__init__.py`, the same number of Python files as here) and
only then removes and replaces the installed copy in one command. Then `ha core
check`, `ha core restart` and a states grep. It prints the restore line for the
tarball it just made. `tests/test_deploy_script.py` holds that order in place
through the dry-run output.

The integration's own entities are `sensor.dorlasen_*` on that instance. The
`sensor.onesti_products_as_nimlypro_*` entities belong to the ZHA quirk, not
to us. Logs are `scripts/ha.sh grep onesti_lock`.

Restore afterwards unless the new version is the one meant to ship, and leave
the backup tarball in place. Slot names and PIN status live in `.storage`, not
in the integration directory, so they survive a swap either way.

## Releasing

The two workflows are split by what they are for. `ci.yml` runs on every push
to `main` and on every pull request, and is the test graph. `release.yml` only
runs when a push to `main` touches
`custom_components/onesti_lock/manifest.json`, and its first job, the version
gate, stops the run when a release for that manifest version is already
published. Only past both does it call `ci.yml` for the pushed commit, wait for
the whole graph, and run `scripts/release_publish.py`, which is where the flow
actually lives. Nothing else publishes a release.

That split is why a release commit gets two CI runs: the one from the push, and
the one inside the release graph. The release has to start and wait for a graph
of its own, because the candidate is repo + SHA + version and the verdict must
belong to that run. One extra run per release is the price; before this split
every docs push produced a run named "Release" that ended in "Nothing to do".

The path filter and the gate catch different things. The filter decides whether
a run is created at all, and GitHub matches it against every commit in the
push, so a bump in the middle of a push or one arriving through a merge commit
still triggers (the candidate is the head of the push either way). The gate
decides whether the run does anything, because a manifest edit is not
necessarily a version bump, and a version can already be out. A draft release
or a bare tag is not "already out": a flow that stopped after tagging must
still be resumable on the same SHA. `workflow_dispatch` bypasses the gate and
still runs the whole flow, including `dry_run` and `trial_release`.

The candidate is one thing: repo + full commit SHA + the manifest version at
that SHA. Tag, ZIP and attestation are all bound to it, and `draft=false` is
the last call, so a failure anywhere leaves no public half release. Every step
is idempotent: a re-run on the same SHA reuses the tag, the draft and an asset
that is already correct.

HACS installs `onesti_lock.zip` from the release (`zip_release` in
`hacs.json`), not the tag's source tree, because a source tree cannot be
attested. The ZIP is packed flat from the git objects at the candidate SHA,
with fixed timestamps and git's file modes, so two builds of the same commit
are byte-identical and anyone can rebuild and compare. `hide_default_branch` is
required alongside `zip_release`; without it, installing the default branch
404s because there is no ZIP there.

1. Run the gates CI runs: `just test-unit`, `python3 scripts/ci_sim.py`, `just test-ha minimum`, `just mypy`, `just coverage`, `uv lock --check`. `just e2e` runs on pull requests only and is not in the release gate.
2. Write the release note in `CHANGELOG.md` under `## [X.Y.Z]`, and mark the bullets a user would notice with `<!--short-->`. The marked ones become the release body; CI fails without them.
3. Bump `version` in `custom_components/onesti_lock/manifest.json`. It is the only version that counts: `pyproject.toml` holds a `0.0.0` placeholder that nothing reads, so leave it.
4. Commit as `chore: release X.Y.Z`, without `[skip ci]`. GitHub skips every workflow for a push whose head commit carries it, the release included. That happened with 1.3.0: the bump commit had `[skip ci]`, so the tag landed on the next push, a docs commit.
5. Push to `main` and wait for the run: `gh run watch -R fredrik-lindseth/onesti-lock`.
6. Check the result: `just release-verify vX.Y.Z`.

Locally, `just release-zip` builds the ZIP and prints its sha256, and `just
release-plan` reads the state on GitHub without writing. Neither publishes: the
attestation can only be made by the workflow run that built the file.

Releases up to and including 1.3.0 predate this flow. Each carries a hand-packed
`onesti_lock.zip` that keeps the `custom_components/onesti_lock/` prefix and is
not the tag's tree. `FIRST_ZIP_VERSION` in `release_publish.py` is where the
flow starts owning the artifact: below it a mismatch is reported but does not
block, so history nobody can change does not turn every push to main red.
`just release-verify` still fails on those tags, which is the honest answer.

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

Onesti Products AS makes all the locks, with identical hardware and firmware,
and the Connect Module (ZMNC010) is the same across all brands: a Nordic
nRF5x part with Zigbee and Bluetooth LE on one die, silkscreened "e-Life",
manufacturer code 4660 left at the ZBOSS default. Its firmware is not one
thing: the 2021 vendor spec and a 2021 sniff have no operation event
attribute, and the source byte and PIN encoding differ between later builds
(`docs/hardware-generations.md`). An older EasyAccess lock generation on a
Datek/Ember module answers "Datek Wireless" and is not covered. The cloud
platform, iotiliti by Safe4 Security Group, developed by Neurosys in Poland,
runs Nimly, EasyAccess, Keyfree, Salus, Homely, Forebygg, Copiax, Tekam,
Folklarm, Tryg Smart, Safe4 Care, LF, Larmify and others. See
`docs/nimly-connect-app/app-architecture.md` for the full ecosystem.
