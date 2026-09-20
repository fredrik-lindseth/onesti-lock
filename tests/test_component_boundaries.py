"""The boundaries inside the integration, the way tests/ble/test_package.py holds the ones in ble/.

Three of them, and none shows itself when it breaks:

* events.py, pin_rules.py and redact.py are pure logic. tests/ runs them with
  homeassistant stubbed into sys.modules, so an import added to one of them
  would pass here and only fail in scripts/ci_sim.py, or not at all.
* every ZCL command goes through ZhaLockTransport.send(), which is what handles
  the sleeping radio, the retry and the redaction. A `cluster.command(...)`
  anywhere else skips all three, and HA's own
  `issue_zigbee_cluster_command` service records the PIN in an event.
* manifest.json names no Python requirement. Home Assistant brings bleak and
  cryptography itself, and a pin here would fight the one HA sets. The
  Bluetooth stack is set up through the `bluetooth_adapters` dependency, which
  belongs there exactly when something in the integration imports bluetooth.py,
  and not a release earlier.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from .conftest import COMPONENT_DIR

COMPONENT = Path(COMPONENT_DIR).resolve()
# The integration's own modules. ble/ is a library with its own boundary test.
MODULES = sorted(COMPONENT.glob("*.py"))

PURE_MODULES = ("events.py", "pin_rules.py", "redact.py")
FORBIDDEN_ROOTS = {"homeassistant", "zigpy", "voluptuous"}

# The one module that talks to a zigpy cluster.
TRANSPORT = COMPONENT / "zha.py"
COMMAND_CALL = re.compile(r"\.command\(|issue_zigbee_cluster_command")

BLUETOOTH_DEPENDENCY = "bluetooth_adapters"


def _name(path: Path) -> str:
    return path.name


def _manifest() -> dict:
    return json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))


def _module_level_imports(path: Path) -> list[tuple[int, str]]:
    """Imports executed when the module loads: (line, root package).

    Only the direct children of the module body count. An import inside
    `if TYPE_CHECKING:` or inside a function never runs, and both are how a
    pure module names a Home Assistant type or reaches for a helper lazily.
    """
    found = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name.split(".")[0]) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


@pytest.mark.parametrize("name", PURE_MODULES)
def test_the_pure_modules_load_without_home_assistant(name):
    path = COMPONENT / name
    wrong = [f"line {line}: {root}" for line, root in _module_level_imports(path) if root in FORBIDDEN_ROOTS]
    assert not wrong, (
        f"{name} imports {wrong} when it loads. It is pure logic that tests/ runs with no Home "
        f"Assistant installed. Put the name under `if TYPE_CHECKING:` or take the value as an argument."
    )


@pytest.mark.parametrize("path", MODULES, ids=_name)
def test_only_the_transport_sends_a_cluster_command(path):
    if path == TRANSPORT:
        return
    wrong = [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if COMMAND_CALL.search(line)
    ]
    assert not wrong, (
        f"{path.name} sends a ZCL command itself:\n  " + "\n  ".join(wrong) + "\n"
        "The lock is a sleeping end device: every command goes through ZhaLockTransport.send() in "
        "zha.py, which handles the timeout, the auto-wake and the redaction of the PIN. Home "
        "Assistant's issue_zigbee_cluster_command service is worse still, because it records the "
        "call and its data, PIN included, as an event."
    )


def test_the_manifest_requires_no_python_package():
    requirements = _manifest()["requirements"]
    assert requirements == [], (
        f"manifest.json requires {requirements}. Home Assistant installs bleak and cryptography "
        f"itself, and a pin here would fight the one HA sets. Keep requirements empty."
    )


def test_bluetooth_adapters_is_a_dependency_exactly_when_bluetooth_py_is_imported():
    importers = []
    for path in MODULES:
        if path.name == "bluetooth.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level and node.module == "bluetooth":
                importers.append(path.name)
            elif isinstance(node, ast.ImportFrom) and node.level and node.module is None:
                importers += [path.name for alias in node.names if alias.name == "bluetooth"]

    dependencies = _manifest()["dependencies"]
    if importers:
        assert BLUETOOTH_DEPENDENCY in dependencies, (
            f"{sorted(set(importers))} import bluetooth.py, so manifest.json must list "
            f"{BLUETOOTH_DEPENDENCY!r} in dependencies. Without it Home Assistant does not set the "
            f"Bluetooth stack up and the import fails on a machine that has no other Bluetooth user."
        )
    else:
        assert BLUETOOTH_DEPENDENCY not in dependencies, (
            f"manifest.json lists {BLUETOOTH_DEPENDENCY!r}, but nothing in the integration imports "
            f"bluetooth.py. It would set the Bluetooth stack up on every installation for nothing."
        )


# Registry lookups Home Assistant deprecated because an identifier or a
# connection is only unique within one config entry from HA 2026.9. Calling
# one logs a warning that names this integration and asks the user to file a
# bug against it, and HA 2027.8 removes them. The replacements take the config
# entry, but they do not exist on the minimum HA, so the way out is to look in
# the entry's own devices (dr.async_entries_for_config_entry) or to reach the
# replacement through getattr with that fallback, as zha.py does.
DEPRECATED_REGISTRY_CALLS = ("async_get_device",)


@pytest.mark.parametrize("path", MODULES, ids=_name)
def test_no_deprecated_registry_lookups(path: Path):
    called = [
        (node.lineno, node.func.attr)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in DEPRECATED_REGISTRY_CALLS
    ]
    assert not called, (
        f"{path.name} calls {', '.join(f'{name} (line {line})' for line, name in called)}. "
        f"Home Assistant deprecated it: the call logs a warning naming this integration and "
        f"telling the user to report a bug, and it stops working in 2027.8. Look the device up "
        f"among the entry's own devices instead, or reach the per-entry replacement through "
        f"getattr with that fallback, since the minimum HA does not have it."
    )
