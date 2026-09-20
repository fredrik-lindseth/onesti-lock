# Test environments

How the test suites are set up and why they are kept apart. The suites
themselves, what each one covers and the commands that run them are listed
in the Testing section of [AGENTS.md](../AGENTS.md). This page holds the
reasoning behind the environments, the pins and the gates, so that a change
to one of them can be made with the whole picture in view.

## The unit suite runs without Home Assistant

`tests/` runs against stubbed `homeassistant`, `voluptuous` and `zigpy`
modules from `tests/conftest.py`, which holds the one shared stub set and
`load_component_module()`. `tests/test_coordinator_behavior.py` has the fake
hass harness that runs real coordinator code on top of it. Home Assistant is
not installed: CI runs the suite through `just coverage-unit` in the uv group
`unit` (pytest, pytest-cov, pyyaml and, through the `ble` group, `cryptography`
and `bleak` for the BLE library), so no test there may import `homeassistant`
or `voluptuous` without stubbing them.

`python3 scripts/ci_sim.py` runs the same ruff check as CI and then the suite
in the unit environment (`.venv-unit` through uv, as `just test-unit`) with
those modules blocked, which is the only way to catch a stray import before CI
does. It runs there and not in the Python that started it because a Python
without bleak skips the bleak tests, and a run with skips is not CI's answer.

`pytest tests/ -q` works in any Python with pytest and cryptography, and skips
the bleak tests without bleak. `pyyaml` is only read by tests: the ones that
parse the workflow files and `quality_scale.yaml` skip without it
(`pytest.importorskip`), and without them nothing checks that `release.yml`
still attests before it publishes.

## Two Home Assistant targets, one venv each

`tests_ha/` loads the integration into a real Home Assistant from
`pytest-homeassistant-custom-component`, with ZHA mocked at the gateway proxy
(`tests_ha/conftest.py` explains how). It needs `just` and `uv`.

Each target has its own venv (`.venv-ha-minimum`, `.venv-ha-current`) and its
own dependency group in `pyproject.toml`, locked in `uv.lock`. The two trees
never share an environment: the stubs in `tests/conftest.py` would collide
with the real package. `[tool.uv] conflicts` in `pyproject.toml` makes uv
refuse the combination, and `default-groups = []` keeps a bare `uv run` from
pulling Home Assistant into the unit environment.

Each group also pins `zigpy` to exactly the version that target's Home
Assistant gets through `zha` (0.80.1 on minimum, 2.2.0 on current), because
which listener hook a Door Lock cluster offers changed with the version;
`tests_ha/test_zigpy_listener.py` builds a real cluster from it. The Bluetooth
stack (bleak, bleak-retry-connector, habluetooth and what they pull in) is
pinned the same way, to the requirements of that Home Assistant's own
`components/bluetooth/manifest.json`, because `bluetooth.py` runs on whatever
HA ships and the API moved between the two releases. The comments above the
groups in `pyproject.toml` say where each pin was read from.

To move a target, change the plugin pin in `pyproject.toml` (each plugin
release pins one exact HA version), run `uv lock`, move the zigpy and
Bluetooth pins to what that Home Assistant's `zha` and `bluetooth` manifests
require, and update `hacs.json` when the minimum moves. CI runs both targets.
`tests/test_version_sync.py` fails when `hacs.json`, the HA version the
`ha-minimum` group resolves to in `uv.lock`, and every HA version written out
in `README.md`, `AGENTS.md`, `justfile` or `pyproject.toml` disagree.

## The Python floor

Development and CI run on the newest stable Python (`.python-version`). The
floor for the integration itself is the lowest Python its minimum Home
Assistant runs on (3.13.2 for HA 2025.6), and `requires-python` and ruff's
`target-version` follow that floor, not the dev Python. `requires-python` also
bounds the whole of `uv.lock`, so raising it to the dev Python would drop the
ha-minimum branch. CI compiles the integration on the floor as well
(`compileall` in the test job). mypy is the one exception; see below.

## Type checking

```bash
just mypy               # the whole component, 0 errors required
just mypy --no-incremental
```

`mypy --strict` covers all of `custom_components/onesti_lock`, `ble/` and
`bluetooth.py` included, and CI runs the same recipe as a step in the
`test-ha` job on `current`. The settings are `[tool.mypy]` in `pyproject.toml`;
`files` is set there, so `just mypy` takes no path.

It runs in the `ha-current` environment because that is the only one where
every import resolves at once: the real Home Assistant for `bluetooth.py`,
`zigpy` for `zha.py`, `bleak` and `cryptography` for `ble/`. That also settles
`python_version`, which is the dev Python and not the runtime floor, unlike
ruff's: mypy parses the Home Assistant it checks against, and the current
release has syntax the floor Python cannot read. The floor is proved by the
`compileall` step in CI instead. `mypy` itself is pinned in the `ha-current`
group.

Two rules the check enforces that are easy to undo by accident: every config
and options flow step annotates `user_input: dict[str, Any] | None = None`,
and `OnestiConfigEntry` rather than a bare `ConfigEntry` is the type in
`async_get_options_flow` and `OnestiCoordinator.__init__`, which is what
hassfest's `runtime-data` validator looks for. Objects from the `zha` library,
which is not installed for the check, are typed `Any` with a comment; zigpy's
own types (`zigpy.zcl.Cluster`) are used where they exist.

## Quality scale and the coverage gate

`custom_components/onesti_lock/quality_scale.yaml` is the self-declaration
against Home Assistant's Integration Quality Scale: every rule is `done`,
`todo` or `exempt` with a comment saying why. No tier is declared:
`manifest.json` has no `quality_scale` key, and the test only checks a tier's
rules once one is written there. hassfest does not validate the file for
custom integrations (`validate_iqs_file` returns early when the integration is
not core), so `tests/test_quality_scale.py` does it instead, with the same
rule list and schema hassfest uses for core. Solving a rule means moving its
status in the same change, not later: nothing else tracks it. When the rule
list upstream grows, copy the new list into the test, bump the core commit
written in its docstring and give the rule a status.

`just coverage` is the port the `test-coverage` rule stands on. It runs
`tests/` and `tests_ha` on current with coverage into separate data files,
then `coverage-gate` combines them and fails under 95 % branch coverage. Only
the combined number counts: each suite alone leaves code the other covers
(`ble/` is reached from `tests/` only, the HA lifecycle from `tests_ha` only).
CI runs the same three recipes, one job per suite and the gate in a job after
both, so a local `just coverage` is the same answer. Codecov gets both reports
under the flags `unit` and `ha` for reading the numbers; it never decides
whether CI is green.

## Deploying to the real lock

Fredrik's Home Assistant is reachable as `ssh ha-local` (the SSH add-on, so
`/config` is the HA config directory). `scripts/ha.sh` wraps the common calls
(`states`, `state`, `logs`, `grep`, `call`, `debug`) so a session does not
re-type the SSH and curl boilerplate; it uses the same `ssh ha-local` alias.

`scripts/deploy_ha.sh deploy` writes the backup tarball to
`/config/onesti_lock-backup-<timestamp>.tar.gz` and reads it back before it
touches anything else, copies the working tree into `onesti_lock.new` without
`__pycache__`, proves that staging directory is complete (manifest,
`__init__.py`, the same number of Python files as here) and only then removes
and replaces the installed copy in one command, so a dropped connection cannot
leave `/config` without the component. Then `ha core check`, `ha core restart`
and a states grep. It prints the restore line for the tarball it just made,
and `scripts/deploy_ha.sh restore <tarball>` puts a backup back and restarts.
`tests/test_deploy_script.py` holds that order in place through the dry-run
output (`--dry-run deploy` prints every command and runs none).

The integration's own entities are `sensor.dorlasen_*` on that instance. The
`sensor.onesti_products_as_nimlypro_*` entities belong to the ZHA quirk, not
to us. Logs are `scripts/ha.sh grep onesti_lock`.

Restore afterwards unless the new version is the one meant to ship, and leave
the backup tarball in place. Slot names and PIN status live in `.storage`, not
in the integration directory, so they survive a swap either way.
