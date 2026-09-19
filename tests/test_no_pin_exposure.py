"""Guards against PIN codes leaking out of the integration.

Attrid 0x0101 on the DoorLock cluster is the actual PIN in BCD plaintext, not
an opaque identifier. Anything we put in a state attribute, a log line or the
slot storage ends up in HA's recorder, logbook and diagnostics, so these tests
fail the build if a future change reconnects that path.

Source is read as text and parsed with ast, never imported, since the
integration imports homeassistant.
"""
from __future__ import annotations

import ast
import os
import re

_PKG = os.path.join(os.path.dirname(__file__), "..", "custom_components", "onesti_lock")
# The BLE validation tool. It prints to a terminal and writes a trace file,
# so its output calls get the same check as the integration's log calls.
_BLE_CLI = os.path.join(os.path.dirname(__file__), "..", "scripts", "ble_cli.py")
# Calls in the CLI whose arguments end up on screen or in the trace: print,
# the Context's say and warn, the module's _warn, and the tracer's note.
_CLI_OUTPUT_CALLS = {"print", "say", "warn", "_warn", "note"}

# Identifier parts that must never carry a value into a log call. Matching on
# whole snake_case/camelCase parts, not substrings, keeps "decoded" and
# "command" legal. Joined spellings are listed explicitly for the same reason.
_SECRET_PARTS = {"pin", "pins", "code", "codes", "pincode", "passcode", "password"}


def _read(name: str) -> str:
    with open(os.path.join(_PKG, name)) as f:
        return f.read()


def _python_files() -> list[str]:
    """Every module in the component, subpackages such as ble/ included."""
    found = []
    for root, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        found += [os.path.relpath(os.path.join(root, f), _PKG) for f in files if f.endswith(".py")]
    return sorted(found)


def _looks_secret(identifier: str) -> bool:
    # Break camelCase before lowering, so pinCode splits into pin + code.
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    parts = [p for p in re.split(r"[^a-z0-9]+", expanded.lower()) if p]
    return any(part in _SECRET_PARTS for part in parts)


class TestPinChainRemoved:
    def test_events_has_no_pin_decoder(self):
        """events.py must not decode or listen for attrid 0x0101."""
        source = _read("events.py")
        assert "_decode_pin_code" not in source
        assert "ATTR_LAST_PIN_CODE" not in source

    def test_coordinator_has_no_pin_pipe(self):
        """No path from the attribute report to the activity sensor."""
        source = _read("coordinator.py")
        assert "update_last_pin_code" not in source
        assert "last_pin_code" not in source

    def test_sensor_has_no_pin_attribute(self):
        """The activity sensor must not hold or expose the PIN."""
        assert "last_pin_code" not in _read("sensor.py")


def _secret_names(call: ast.Call) -> list[str]:
    """The PIN-shaped identifiers among a call's arguments."""
    found = []
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        for sub in ast.walk(arg):
            name = None
            if isinstance(sub, ast.Name):
                name = sub.id
            elif isinstance(sub, ast.Attribute):
                name = sub.attr
            elif isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant):
                # Dict lookups such as slot_data["code"]. Bare string
                # constants are format strings, and naming PIN in a message
                # is fine.
                key = sub.slice.value
                name = key if isinstance(key, str) else None
            if name and _looks_secret(name):
                found.append(name)
    return found


def _is_logger_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "_LOGGER"


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class TestNoPinInLogs:
    def test_loggers_never_log_codes(self):
        """No _LOGGER call may pass a PIN-shaped value.

        Format strings mentioning PIN are fine, the values are the danger.
        """
        offenders: list[str] = []
        for filename in _python_files():
            tree = ast.parse(_read(filename))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _is_logger_call(node):
                    offenders += [f"{filename}:{node.lineno} passes {name}" for name in _secret_names(node)]
        assert not offenders, "Logging a PIN-shaped value: " + "; ".join(offenders)

    def test_ble_cli_never_prints_or_traces_codes(self):
        """scripts/ble_cli.py takes a PIN for PinCodeSet; no output call may pass it on.

        tests/test_ble_cli.py checks the same at run time, against the trace
        file and the output of a real PinCodeSet.
        """
        with open(_BLE_CLI) as f:
            tree = ast.parse(f.read())
        offenders: list[str] = []
        output_calls = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) in _CLI_OUTPUT_CALLS or _is_logger_call(node):
                output_calls += 1
                offenders += [f"ble_cli.py:{node.lineno} passes {name}" for name in _secret_names(node)]
        # Guards the guard: renamed output helpers would leave nothing to check.
        assert output_calls > 20, "the CLI's output calls were not found; were its helpers renamed?"
        assert not offenders, "Printing a PIN-shaped value: " + "; ".join(offenders)

    def test_ble_cli_check_sees_a_printed_pin(self):
        """The CLI check fires on the shapes the CLI would use to leak a PIN."""
        leak = ast.parse('ctx.say(f"PIN {pin}")\nprint(args.pin_code)\ntracer.note("x", value=new_pin)')
        calls = [node for node in ast.walk(leak) if isinstance(node, ast.Call) and _call_name(node) in _CLI_OUTPUT_CALLS]
        assert [name for call in calls for name in _secret_names(call)] == ["pin", "pin_code", "new_pin"]

    def test_secret_matcher_ignores_lookalikes(self):
        """The matcher must not fire on decoded/command and must fire on PINs."""
        assert not _looks_secret("decoded")
        assert not _looks_secret("command")
        assert not _looks_secret("encoder")
        assert _looks_secret("code")
        assert _looks_secret("pin_code")
        assert _looks_secret("_last_pin_code")
        assert _looks_secret("pinCode")
        assert _looks_secret("pincode")
        assert _looks_secret("passcode")


class TestNoPinInStorage:
    def test_storage_never_holds_codes(self):
        """Slot storage keeps the name and flags, never the code itself."""
        source = _read("coordinator.py")
        assert 'slot_data["name"]' in source
        assert 'slot_data["has_pin"]' in source
        assert 'slot_data["code"' not in source

    def test_default_slot_has_no_code_key(self):
        """DEFAULT_SLOT defines the persisted shape, so it gates what can be stored."""
        tree = ast.parse(_read("const.py"))
        keys: set[str] = set()
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(t, ast.Name) and t.id == "DEFAULT_SLOT" for t in node.targets
            ):
                continue
            assert isinstance(node.value, ast.Dict)
            keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
            found = True
        assert found, "DEFAULT_SLOT not found in const.py"
        assert keys == {"name", "has_pin"}
