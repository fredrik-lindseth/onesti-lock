"""Run the test suite the way CI sees it.

CI runs tests/ in the uv group `unit`, which has pytest and the few libraries
the tests need (pyyaml, and cryptography for the BLE library) but no
homeassistant, voluptuous or zigpy, so a test that imports one of those passes
locally and fails there. This runs the same ruff check as CI, then blocks
those modules through an import hook and runs the suite, which is the only
way to catch a stray import before pushing.

    python3 scripts/ci_sim.py
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUFF_PATHS = ["custom_components/onesti_lock/", "tests/", "tests_ha/", "scripts/"]
BLOCKED = {"voluptuous", "homeassistant", "zigpy", "pytest_asyncio", "hypothesis"}


class Blocker:
    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in BLOCKED:
            raise ModuleNotFoundError(f"No module named {name!r} (blocked to simulate CI)", name=name)
        return None


try:
    lint = subprocess.run(["ruff", "check", *RUFF_PATHS], cwd=REPO_ROOT)
except FileNotFoundError:
    sys.exit("ruff is not installed; CI runs it, so install it with `pip install ruff`.")
if lint.returncode != 0:
    sys.exit(lint.returncode)

for mod in list(sys.modules):
    if mod.split(".")[0] in BLOCKED:
        del sys.modules[mod]
sys.meta_path.insert(0, Blocker())

sys.exit(pytest.main(["tests/", "-q", "-p", "no:asyncio", "-p", "no:hypothesis", "-p", "no:cacheprovider"]))
