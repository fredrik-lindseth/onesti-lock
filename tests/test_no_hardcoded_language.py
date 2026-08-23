"""Guard against hardcoded Norwegian sneaking back into the source.

Issue #5: Swedish and Danish users saw Norwegian sensor states, entity
names and error messages. All user-facing text now lives in
translations/*.json, so no module should contain Scandinavian letters in
a string literal, and the sensors must not override the entity name.
"""
from __future__ import annotations

import ast
import os
import re

import pytest

MODULES = [
    "sensor.py",
    "config_flow.py",
    "services.py",
    "coordinator.py",
    "localize.py",
]
SCANDINAVIAN = set("æøåäöÆØÅÄÖ")
# The strings issue #5 removed mostly contain no æøåäö ("Ledig", "Ukjent",
# "Siste aktivitet", "ingen PIN", "fingeravtrykk"), so the letter check
# alone would wave the original bug through. Match those words explicitly.
NORWEGIAN_WORDS = re.compile(
    r"\b(ledig|ukjent|siste|aktivitet|fingeravtrykk|ingen)\b", re.IGNORECASE
)


def _component_path(*parts):
    return os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", *parts
    )


def _parse(module):
    with open(_component_path(module), encoding="utf-8") as f:
        return ast.parse(f.read())


def _docstring_nodes(tree):
    """Collect the Expr nodes that are docstrings, to exempt them."""
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


class TestNoNorwegianLiterals:
    """User-facing text belongs in the translation files."""

    @pytest.mark.parametrize("module", MODULES)
    def test_no_scandinavian_letters_in_string_literals(self, module):
        tree = _parse(module)
        docstrings = _docstring_nodes(tree)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            if SCANDINAVIAN & set(node.value) or NORWEGIAN_WORDS.search(node.value):
                offenders.append((node.lineno, node.value))
        assert not offenders, f"{module} has hardcoded Scandinavian text: {offenders}"


class TestSensorNaming:
    """The sensors must let HA translate their names."""

    def _class_node(self, name):
        tree = _parse("sensor.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        raise AssertionError(f"class {name} not found in sensor.py")

    @pytest.mark.parametrize("class_name", ["NimlySlotSensor", "NimlyActivitySensor"])
    def test_no_name_property_override(self, class_name):
        """A `name` property beats the translation key and kills translation."""
        node = self._class_node(class_name)
        for child in node.body:
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                assert child.name != "name", (
                    f"{class_name} defines a name property, which overrides "
                    "_attr_translation_key"
                )

    def _assigned_attrs(self, class_name):
        node = self._class_node(class_name)
        attrs = set()
        for child in node.body:
            if not isinstance(child, ast.FunctionDef) or child.name != "__init__":
                continue
            for stmt in ast.walk(child):
                if not isinstance(stmt, ast.Assign):
                    continue
                for target in stmt.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        attrs.add(target.attr)
        return attrs

    def test_slot_sensor_sets_translation_attrs(self):
        attrs = self._assigned_attrs("NimlySlotSensor")
        assert "_attr_translation_key" in attrs
        assert "_attr_translation_placeholders" in attrs

    def test_activity_sensor_sets_translation_attrs(self):
        attrs = self._assigned_attrs("NimlyActivitySensor")
        assert "_attr_translation_key" in attrs

    def test_sensors_never_set_attr_name(self):
        """HA checks _attr_name before the translation key.

        Setting it as a fallback disables translated entity names outright.
        Confirmed on a running instance, where a Norwegian server showed
        the English _attr_name instead of "Siste aktivitet".
        """
        for cls in ("NimlySlotSensor", "NimlyActivitySensor"):
            assert "_attr_name" not in self._assigned_attrs(cls), cls

    def test_slot_translation_key_is_shared(self):
        """One key with a {slot} placeholder, not ten per-slot keys."""
        node = self._class_node("NimlySlotSensor")
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "_attr_translation_key"
                ):
                    assert isinstance(stmt.value, ast.Constant)
                    assert stmt.value.value == "slot"


class TestServiceErrorTranslation:
    """Every HomeAssistantError must carry a translation key."""

    def _raise_calls(self):
        tree = _parse("services.py")
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            exc = node.exc
            if (
                isinstance(exc, ast.Call)
                and isinstance(exc.func, ast.Name)
                and exc.func.id == "HomeAssistantError"
            ):
                calls.append(exc)
        return calls

    def test_all_errors_are_translatable(self):
        calls = self._raise_calls()
        assert calls, "no HomeAssistantError raises found in services.py"
        for call in calls:
            keywords = {kw.arg for kw in call.keywords}
            assert "translation_domain" in keywords, (
                f"line {call.lineno}: missing translation_domain"
            )
            assert "translation_key" in keywords, (
                f"line {call.lineno}: missing translation_key"
            )

    def test_all_errors_have_english_fallback_message(self):
        """str(exception) must stay readable if the lookup fails."""
        for call in self._raise_calls():
            assert call.args, f"line {call.lineno}: no positional message"

    def test_translation_keys_exist_in_strings_json(self):
        import json

        with open(_component_path("strings.json"), encoding="utf-8") as f:
            exceptions = json.load(f)["exceptions"]

        for call in self._raise_calls():
            for keyword in call.keywords:
                if keyword.arg != "translation_key":
                    continue
                assert isinstance(keyword.value, ast.Constant)
                key = keyword.value.value
                assert key in exceptions, (
                    f"services.py line {call.lineno} uses translation_key "
                    f"'{key}' which is missing from strings.json"
                )

    def test_placeholder_values_are_strings(self):
        """HA rejects non-string placeholder values, so ints must be wrapped."""
        const = {}
        with open(_component_path("const.py")) as f:
            exec(f.read(), const)

        for call in self._raise_calls():
            for keyword in call.keywords:
                if keyword.arg != "translation_placeholders":
                    continue
                assert isinstance(keyword.value, ast.Dict)
                for value in keyword.value.values:
                    where = f"services.py line {call.lineno}"
                    if isinstance(value, ast.Constant):
                        assert isinstance(value.value, str), (
                            f"{where}: placeholder literal must be a string"
                        )
                    elif isinstance(value, ast.Name):
                        # A constant pulled straight from const.py must
                        # already be a string; anything else needs str().
                        referenced = const.get(value.id)
                        assert referenced is None or isinstance(referenced, str), (
                            f"{where}: {value.id} is not a string, wrap it in str()"
                        )
                    elif isinstance(value, ast.Call):
                        assert (
                            isinstance(value.func, ast.Name) and value.func.id == "str"
                        ), f"{where}: placeholder call must be str(...)"
                    elif not isinstance(value, ast.JoinedStr):
                        raise AssertionError(
                            f"{where}: placeholder value must be a string, "
                            f"got {type(value).__name__}"
                        )
