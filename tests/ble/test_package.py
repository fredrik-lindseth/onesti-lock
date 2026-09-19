"""The shape of the ble package: its boundary, its layers and its public API.

The library has to stay usable without Home Assistant and on its own, so
nothing in it imports Home Assistant or reaches outside ble/. Inside, the
layers import downwards only: protocol/ knows nothing of crypto or the client,
crypto.py nothing of the client, and errors.py only the protocol constants it
names statuses with.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from ..conftest import COMPONENT_DIR, PACKAGE, load_component_module

# Loading any module sets up the stub package and runs ble/__init__.py.
errors = load_component_module("ble.errors")
ble = importlib.import_module(f"{PACKAGE}.ble")

BLE_DIR = Path(COMPONENT_DIR).resolve() / "ble"
MODULES = sorted(BLE_DIR.rglob("*.py"))

FORBIDDEN_ROOTS = {"homeassistant", "zigpy", "voluptuous"}
# The wire format does no crypto and no I/O.
PROTOCOL_FORBIDDEN_ROOTS = {"cryptography", "asyncio", "logging"}

# What each part of the package may import from the rest of it, by the first
# path component under ble/. ble/__init__.py, the public API, may import all.
ALLOWED_LAYERS = {
    "protocol": {"protocol", "errors"},
    "errors": {"protocol.const"},
    "crypto": {"protocol.const", "errors"},
    "client": {"protocol", "crypto", "errors", "client"},
}


def _name(path: Path) -> str:
    return str(path.relative_to(BLE_DIR))


def _package(path: Path) -> list[str]:
    """The package path/to/module.py lives in, as ["ble", ...]."""
    return ["ble", *path.relative_to(BLE_DIR).parent.parts]


def _layer(path: Path) -> str | None:
    parts = path.relative_to(BLE_DIR).parts
    if parts == ("__init__.py",):
        return None
    return parts[0].removesuffix(".py")


def _imports(path: Path) -> list[tuple[int, list[str]]]:
    """Every import in the module: (level, absolute target parts).

    A relative import is resolved against the module's package, so
    ["ble", "protocol", "const"] for `from .const import X` in protocol/. An
    import that climbs out of ble/ resolves to ["<outside>", ...], which the
    boundary test catches.
    """
    found: list[tuple[int, list[str]]] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found += [(0, alias.name.split(".")) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module.split(".") if node.module else []
            if node.level == 0:
                found.append((0, module))
                continue
            package = _package(path)
            climb = node.level - 1
            base = ["<outside>"] if climb >= len(package) else package[: len(package) - climb]
            if module:
                found.append((node.level, base + module))
            else:
                found += [(node.level, base + [alias.name]) for alias in node.names]
    return found


@pytest.mark.parametrize("path", MODULES, ids=_name)
def test_no_home_assistant_and_no_reaching_out(path):
    for level, target in _imports(path):
        if level == 0:
            assert target[0] not in FORBIDDEN_ROOTS, f"{_name(path)} imports {'.'.join(target)}"
        else:
            # from ...x would tie the library to the integration around it.
            assert target[0] == "ble", f"{_name(path)} imports from outside ble/"


@pytest.mark.parametrize("path", MODULES, ids=_name)
def test_layers_import_downwards(path):
    layer = _layer(path)
    if layer is None:
        return
    allowed = ALLOWED_LAYERS[layer]
    wrong = []
    for level, target in _imports(path):
        if level == 0:
            if layer == "protocol" and target[0] in PROTOCOL_FORBIDDEN_ROOTS:
                wrong.append(target[0])
        elif target[0] == "ble":
            inner = ".".join(target[1:])
            if not any(inner == rule or inner.startswith(f"{rule}.") for rule in allowed):
                wrong.append(f"ble.{inner}")
    assert not wrong, f"{_name(path)} ({layer}) imports {wrong}"


@pytest.mark.parametrize("path", sorted(BLE_DIR.rglob("__init__.py")), ids=_name)
def test_subpackages_load_nothing_on_import(path):
    # Importing one protocol module must not drag in the rest, and a cycle
    # through errors.py stays impossible while these hold no imports.
    if path.parent == BLE_DIR:
        return
    imports = [
        node
        for node in ast.parse(path.read_text()).body
        if isinstance(node, ast.Import) or (isinstance(node, ast.ImportFrom) and node.module != "__future__")
    ]
    assert not imports, f"{_name(path)} imports at package level"


# Calls whose result is raised and that return a BleError themselves.
BLE_ERROR_FACTORIES = {"error_for_status", "_not_connected"}


@pytest.mark.parametrize("path", MODULES, ids=_name)
def test_raises_only_ble_errors(path):
    """Everything the library raises is a BleError, so one except clause catches it all.

    A bare `raise` re-raises what was caught and is fine. Anything else must
    construct a Ble* class or call one of the factories that return one.
    """
    wrong = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        call = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        name = call.attr if isinstance(call, ast.Attribute) else getattr(call, "id", None)
        if not (name and (name.startswith("Ble") or name in BLE_ERROR_FACTORIES)):
            wrong.append(f"line {node.lineno}: {ast.unparse(node.exc)}")
    assert not wrong, f"{_name(path)} raises outside BleError: {wrong}"


def test_marked_as_typed():
    assert (BLE_DIR / "py.typed").is_file()


class TestPublicApi:
    def test_every_export_resolves(self):
        missing = [name for name in ble.__all__ if not hasattr(ble, name)]
        assert not missing

    def test_exports_are_the_modules_own_objects(self):
        assert ble.Session is load_component_module("ble.client.session").Session
        assert ble.enroll is load_component_module("ble.client.enrollment").enroll
        assert ble.commands is load_component_module("ble.protocol.commands")
        assert ble.responses is load_component_module("ble.protocol.responses")

    def test_every_error_class_is_exported(self):
        enrollment = load_component_module("ble.client.enrollment")
        classes = {
            name
            for module in (errors, enrollment)
            for name, value in vars(module).items()
            if isinstance(value, type) and issubclass(value, errors.BleError)
        }
        assert classes <= set(ble.__all__)
        assert issubclass(ble.BleEnrollmentError, ble.BleError)
