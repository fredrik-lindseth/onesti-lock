"""Run the test suite the way CI sees it.

CI installs only ruff and pytest, so a test that imports homeassistant or
voluptuous passes locally and fails there. This blocks those modules through
an import hook and runs the suite, which is the only way to catch that
before pushing.

    python3 scripts/ci_sim.py
"""
import sys

BLOCKED = {"voluptuous", "homeassistant", "pytest_asyncio", "hypothesis"}


class Blocker:
    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in BLOCKED:
            raise ModuleNotFoundError(f"No module named {name!r} (blocked to simulate CI)", name=name)
        return None


for mod in list(sys.modules):
    if mod.split(".")[0] in BLOCKED:
        del sys.modules[mod]
sys.meta_path.insert(0, Blocker())

import pytest
sys.exit(pytest.main(["tests/", "-q", "-p", "no:asyncio", "-p", "no:hypothesis", "-p", "no:cacheprovider"]))
