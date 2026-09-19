# Test targets. Requires `just` (https://github.com/casey/just) and uv.

set shell := ["bash", "-uc"]

# The coverage flags both suites share, locally and in CI.
cov_args := "--cov=custom_components/onesti_lock --cov-branch --cov-report=term-missing"

default:
    @just --list

# Real Home Assistant. target=minimum is the version hacs.json promises,
# target=current the newest release pinned in pyproject.toml. Both must be
# green. Each target has its own venv, and neither touches tests/, which
# runs without Home Assistant installed.
test-ha target="current" *args:
    #!/usr/bin/env bash
    set -euo pipefail
    # `just test-ha target=minimum` passes the whole string positionally,
    # so strip the prefix rather than reject the documented spelling.
    target="{{target}}"; target="${target#target=}"
    case "$target" in
        minimum) python=3.13 ;;
        current) python=3.14 ;;
        *) echo "Unknown target '$target'. Use minimum or current." >&2; exit 2 ;;
    esac
    UV_PROJECT_ENVIRONMENT=".venv-ha-$target" uv run --frozen --python "$python" \
        --group "ha-$target" pytest tests_ha -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function {{args}}

# tests/ against the homeassistant stubs, in an environment without Home
# Assistant (group unit). This is the suite CI's test job runs.
test-unit *args:
    UV_PROJECT_ENVIRONMENT=.venv-unit uv run --frozen --python 3.14 --group unit pytest tests/ {{args}}

# The BLE validation tool, scripts/ble_cli.py, against a real lock, in the
# unit environment, which has bleak and cryptography. `just ble --help` lists
# the steps; docs/nimly-ble-app/ble-library.md has the order to run them in.
# Positional arguments, so a quoted argument with a space stays one argument.
[positional-arguments]
ble *args:
    UV_PROJECT_ENVIRONMENT=.venv-unit uv run --frozen --python 3.14 --group unit python scripts/ble_cli.py "$@"

# Combined branch coverage of tests/ and tests_ha on current, held to the
# 95 % the quality scale's test-coverage rule demands. CI runs the same three
# recipes: one per suite in their own jobs, then the gate in a job after both.
coverage: (coverage-unit "-q") (coverage-ha "-q") coverage-gate

# tests/ with coverage, into .coverage.unit and coverage-unit.xml.
coverage-unit *args:
    COVERAGE_FILE=.coverage.unit just test-unit {{cov_args}} --cov-report=xml:coverage-unit.xml {{args}}

# tests_ha on current with coverage, into .coverage.ha and coverage-ha.xml.
# Minimum is left out: it runs the same tests against an older HA, so the
# rule is measured once, on the release users install today.
coverage-ha *args:
    COVERAGE_FILE=.coverage.ha just test-ha current {{cov_args}} --cov-report=xml:coverage-ha.xml {{args}}

# Merges .coverage.unit and .coverage.ha, prints the missing lines and fails
# under 95 %. Only the combined number counts: each suite alone leaves code
# the other covers, and neither is meant to stand on its own.
coverage-gate:
    UV_PROJECT_ENVIRONMENT=.venv-unit uv run --frozen --python 3.14 --group unit \
        coverage combine --data-file=.coverage .coverage.unit .coverage.ha
    UV_PROJECT_ENVIRONMENT=.venv-unit uv run --frozen --python 3.14 --group unit \
        coverage report --data-file=.coverage --show-missing --fail-under=95

# The same core .github/workflows/release.yml runs, that is
# scripts/release_publish.py. None of the recipes below write anything on
# GitHub; publishing happens in the workflow, where the attestation is made.

# Build the ZIP HACS installs, from the git objects at a commit, and print its
# sha256. Two runs on the same commit give a byte-identical file.
release-zip sha="HEAD":
    python3 scripts/release_publish.py build --sha {{sha}} --output dist/onesti_lock.zip

# What would the release flow do with this commit? Reads GitHub, writes nothing.
release-plan sha="HEAD":
    python3 scripts/release_publish.py plan --sha {{sha}}

# Check a release that is already out: do the tag, the ZIP and the attestation
# point at the same artifact?
release-verify tag:
    python3 scripts/release_publish.py verify --sha {{tag}}
