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
report, no auto-wake, no event decoding. The config entry is seeded by the
harness rather than created through the flow, because the flow correctly
refuses to make one without a lock; the entry is written in the oldest config
entry store format so Home Assistant's own migration fills in the rest, which
also means this is not a test of *our* `async_migrate_entry` (that is
`tests_ha/test_lifecycle.py`).

The blueprints are repo files a user imports by hand, not part of the ZIP, so
they are copied from the working tree. `blueprints_instantiate` proves each
one validates and starts; it does not fire the triggers, so nothing here says
the notification text or the lock action is right.

A green run means: what HACS installs loads, names itself correctly, offers
its services and dialogs, and its blueprints are usable. It is a smoke test of
the package, not of the lock.

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

Runs without Docker: version resolution, the seeded entry, the log filter, the
redaction and the guard that refuses to drive a Compose project this harness
did not create. It says nothing about container cleanup; that is only shown by
a real run.

The harness has been checked against a broken release as well: an import error
planted in the unpacked ZIP fails `component_loaded` and lights up the log
filter, and a blueprint whose action does not validate fails
`blueprints_instantiate` with Home Assistant's own message. Run one of those
again after changing what a check asserts, or you have a test that cannot
fail.
