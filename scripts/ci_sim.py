"""Run the test suite the way CI sees it.

CI runs tests/ in the uv group `unit` (`just coverage-unit`), which has pytest
and the libraries the tests need (pyyaml, cryptography and bleak for the BLE
library) but no homeassistant, voluptuous or zigpy, so a test that imports one
of those passes locally and fails there. This runs the same ruff check as CI,
then the suite in that same environment (`.venv-unit`, the one `just
test-unit` builds), with those modules blocked through an import hook, which
is the only way to catch a stray import before pushing.

The suite runs in the unit environment and not in whatever Python started
this script, because the outcome has to be CI's. A Python without bleak skips
the bleak tests (pytest.importorskip), so a run there is green where CI could
be red. The blocker stays on top: the unit group has none of the blocked
modules today, and it catches the day one of them arrives as a transitive
dependency.

    python3 scripts/ci_sim.py

Needs ruff on PATH, as in CI, and uv.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUFF_PATHS = ["custom_components/onesti_lock/", "tests/", "tests_ha/", "tests_e2e/", "scripts/"]
BLOCKED = {"voluptuous", "homeassistant", "zigpy", "bleak_retry_connector", "habluetooth", "pytest_asyncio", "hypothesis"}
# How the justfile's test-unit recipe starts the unit environment.
UNIT_ENV = ".venv-unit"
UNIT_PYTHON = "3.14"
# Marks the second run of this script, inside the unit environment.
INNER_FLAG = "--in-unit-env"


class Blocker:
    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in BLOCKED:
            raise ModuleNotFoundError(f"No module named {name!r} (blocked to simulate CI)", name=name)
        return None


def run_suite() -> int:
    """Inside the unit environment: block the modules and run tests/."""
    import pytest

    for mod in list(sys.modules):
        if mod.split(".")[0] in BLOCKED:
            del sys.modules[mod]
    sys.meta_path.insert(0, Blocker())
    return int(pytest.main(["tests/", "-q", "-p", "no:asyncio", "-p", "no:hypothesis", "-p", "no:cacheprovider"]))


def main() -> int | str:
    try:
        lint = subprocess.run(["ruff", "check", *RUFF_PATHS], cwd=REPO_ROOT)
    except FileNotFoundError:
        return "ruff is not installed; CI runs it, so install it with `pip install ruff`."
    if lint.returncode != 0:
        return lint.returncode

    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": UNIT_ENV}
    command = ["uv", "run", "--frozen", "--python", UNIT_PYTHON, "--group", "unit", "python", __file__, INNER_FLAG]
    try:
        return subprocess.run(command, cwd=REPO_ROOT, env=env).returncode
    except FileNotFoundError:
        return "uv is not installed; CI runs tests/ in its unit group, see https://docs.astral.sh/uv/."


if __name__ == "__main__":
    if INNER_FLAG in sys.argv[1:]:
        os.chdir(REPO_ROOT)
        sys.exit(run_suite())
    sys.exit(main())
