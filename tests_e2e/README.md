# The release ZIP in a real Home Assistant

`tests/` and `tests_ha/` test the source tree. This one tests the artifact:
the ZIP `scripts/release_publish.py` builds, unpacked flat into
`custom_components/onesti_lock/` the way HACS unpacks it, inside an official
Home Assistant container.

```bash
just e2e                    # newest pinned Home Assistant
just e2e target=minimum     # the release hacs.json promises
just e2e-harness            # the host-side harness itself, no Docker
python3 tests_e2e/run.py run --target current --keep   # leave it running
python3 tests_e2e/run.py cleanup                       # after a killed run
```

Needs Docker and Python 3.11 or newer. The ZIP is built from committed HEAD,
so uncommitted changes are not in it; `--sha <commit>` picks another one. Each
run gets its own Compose project, its own free loopback port and a temporary
config directory, and stops itself in a `finally`.

Both image tags are read from `uv.lock`, through the same chain as
`tests/test_version_sync.py`: the `ha-minimum` and `ha-current` groups pin the
plugin, and the plugin pins one exact Home Assistant. The container therefore
runs the same release as `just test-ha <target>`, and moving a pin moves both.
The tag is not pinned to a digest, because a digest would pin one CPU
architecture and this has to run on an amd64 runner and an arm64 laptop.

## What the run proves

| Check | Assertion |
| --- | --- |
| `component_loaded` | Home Assistant imported `onesti_lock` from the unpacked ZIP |
| `entry_loaded` | A stored config entry sets up to `loaded` without a Zigbee radio |
| `entities_created` | 14 sensors on the `onesti_lock` platform, the 3 diagnostics off by default |
| `entity_names_translated` | Frontend names are the ones in the ZIP's `translations/en.json` |
| `services_registered` | All four services exist, with the fields from `services.yaml` |
| `config_flow_runs` | The config flow starts and aborts with `zha_not_found` |
| `options_flow_opens` | The PIN menu opens with exactly the options the translations name |
| `translations_load` | Every English string in the ZIP is served by `frontend/get_translations` |
| `blueprints_parse` | Home Assistant loads all three blueprints without an error |
| `blueprints_instantiate` | An automation built from each blueprint validates and runs |
| `blueprint_goodnight_locks` | Triggering the goodnight automation locks the stand-in lock |
| `blueprint_connectivity_notifies` | A lock coming back from unavailable produces the blueprint's notification |
| `blueprint_unlock_notifies` | An unlock on the activity sensor notifies who did it and how, a lock does not |
| `migration_reaches_current_version` | The 2.1 and 2.2 entries are stored at the installed version and set up |
| `migration_2_1_strips_has_rfid` | An entry that skipped a step keeps its slot and loses `has_rfid` |
| `migration_rewrites_registry_keys` | Entity unique ids and the device identifier are keyed on the entry id, nothing duplicated |
| `migration_keeps_what_the_user_set` | Entity ids, a rename, a disabled entity, the device name and the slot data survive |
| `newer_entry_refused` | An entry from a newer major version does not load and creates nothing |

On top of that the host fails the run on any `ERROR` line naming
`onesti_lock`, and on the handful of messages that mean nothing of ours could
have worked (`Setup failed for`, `Unable to install package`, and so on).

The ZIP layout is checked before anything starts: a `custom_components/`
prefix, a missing `manifest.json` at the root or a different domain fails the
run, because that is what would leave HACS with an integration Home Assistant
never finds.

## What it does not prove

There is no Zigbee radio in the container, so ZHA has no gateway and no lock.
Nothing here says anything about talking to a lock: no PIN write, no attribute
report, no auto-wake, no event decoding. The sensors are therefore unavailable
and carry no attributes, so what a slot holds is read out of the entry rather
than off the sensor.

A green run means: what HACS installs loads, migrates a user's stored state
without losing any of it, names itself correctly, offers its services and
dialogs, and its blueprints run. It is a test of the package, not of the lock.

## The four seeded entries

The entries are seeded by the harness rather than created through the flow,
because the flow correctly refuses to make one without a lock. Each of the
four is a stored shape a user can start Home Assistant with, and three of them
exist to be migrated on the way up:

| Entry | Shape | What it proves |
| --- | --- | --- |
| current | the version the ZIP writes | an entry that needs no migration loads |
| 2.2 | registry keys on the IEEE address, an entity renamed by hand, one disabled by hand, the user's slot data | `async_migrate_entry` rewrites both registries in place: entity ids, names, the disabled flag, the device name and the slots all survive, and nothing is duplicated |
| 2.1 | slots still carry `has_rfid` | an installation that skipped a release still comes all the way up |
| one major version ahead | written by a release this one does not know | it is refused, loads nothing, and the ERROR Home Assistant logs about it is the only one this run allows |

The store files are written at storage version 1.1, the oldest format, so
Home Assistant's own migrations fill in every key added since and the harness
does not track a schema that is not ours. What is ours is the entry version
and the registry keys. `tests_ha/test_lifecycle.py` covers the same migration
against a mocked ZHA; this is the same code against a real registry store on
disk, which is where the risk of a 2.3 migration actually sits.

## The blueprints

The blueprints are repo files a user imports by hand, not part of the ZIP, so
they are copied from the working tree. Each one is instantiated through the
config API and then triggered: the goodnight automation by hand, since its own
trigger is a time of day, and the other two by the state changes they listen
for. The notifications they send are read back out of Home Assistant, so the
templates and the text in them are covered.

What triggers them is a state, not the `onesti_lock_activity` event: none of
the blueprints listen for the event. The activity sensor's state is written
over the API here, because nothing else can move it without a radio.

`lock.e2e_stand_in` is a template lock in `configuration.yaml`, standing in
for the ZHA lock entity the blueprints would be pointed at on a real system.

## Evidence

Kept in the gitignored `tests_e2e/artifacts/<project>/`: the redacted
container log, the named check report and a `version.json` with the SHA, the
ZIP's sha256 and the image. The lab's own throwaway credentials are replaced
before anything is written there, and CI uploads only that directory. The
temporary config directory, with `.storage` and the auth file, is deleted with
the lab unless `--keep` was given.

## Where it runs

`.github/workflows/e2e.yml`, on pull requests and by hand, as a matrix over
both targets. It is deliberately not part of `ci.yml` and therefore not part
of the release gate: it needs Docker and two 600 MB image pulls, and the rest
of CI should not wait for that. Wiring it into the gate is a decision to take
once the run has some history behind it.

## Checking the harness

```bash
just e2e-harness
```

Runs without Docker: version resolution, the four seeded entries and their
registry rows, the log filter and its one allowance, the redaction and the
guard that refuses to drive a Compose project this harness did not create. It
says nothing about container cleanup; that is only shown by a real run.

The harness has been checked against a broken release as well: an import error
planted in the unpacked ZIP fails `component_loaded` and lights up the log
filter, a blueprint whose action does not validate fails
`blueprints_instantiate` with Home Assistant's own message, and a
`_migrate_to_entry_id_keys` that skips the entity half fails
`migration_rewrites_registry_keys` with 18 entities where 14 belong, the four
seeded ones still on the IEEE address and a `sensor.front_door_slot_3_2`
beside the one the user had. Run one of those again after changing what a
check asserts, or you have a test that cannot fail.
