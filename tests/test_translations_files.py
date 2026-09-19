"""Tests for translation file completeness across en/nb/sv/da.

strings.json is the English source and must stay in sync with
translations/en.json. Every file must carry the same keys, the same
placeholders, and every runtime key the Python code looks up.
"""
from __future__ import annotations

import ast
import json
import os
import re

import pytest

FILES = [
    "strings.json",
    "translations/en.json",
    "translations/nb.json",
    "translations/sv.json",
    "translations/da.json",
]
LANGUAGE_FILES = FILES[1:]
EXCEPTION_KEYS = [
    "lock_unreachable",
    "lock_rejected",
    "lock_rejected_duplicate",
    "lock_rejected_memory_full",
    "invalid_slot",
    "invalid_pin",
    "lock_not_found",
    "lock_not_found_ieee",
    "multiple_locks",
]
# localize.py reads its strings from this section. It is "common" because
# hassfest only accepts the top-level keys in HA's strings schema, and
# nothing in HA looks up an integration's "common" keys on its own.
RUNTIME_SECTION = "common"
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
EM_DASH = "—"


def _component_path(*parts):
    return os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", *parts
    )


def _load(filename):
    with open(_component_path(*filename.split("/")), encoding="utf-8") as f:
        return json.load(f)


def _key_paths(data, prefix=""):
    """Recursively collect all leaf key paths."""
    paths = set()
    for key, value in data.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths.update(_key_paths(value, full))
        else:
            paths.add(full)
    return paths


def _placeholders(text):
    return set(PLACEHOLDER_RE.findall(text))


def _load_const():
    namespace = {}
    with open(_component_path("const.py")) as f:
        exec(f.read(), namespace)
    return namespace


class TestFileStructure:
    """All five files must describe the same set of strings."""

    def test_strings_json_equals_en(self):
        """strings.json is the English source, byte-for-byte in content."""
        assert _load("strings.json") == _load("translations/en.json")

    @pytest.mark.parametrize("filename", LANGUAGE_FILES)
    def test_same_key_paths_as_strings_json(self, filename):
        base = _key_paths(_load("strings.json"))
        other = _key_paths(_load(filename))
        assert base == other, (
            f"Missing in {filename}: {base - other}, extra: {other - base}"
        )

    @pytest.mark.parametrize("filename", FILES)
    def test_has_all_sections(self, filename):
        data = _load(filename)
        for section in ("config", "options", "entity", "exceptions", RUNTIME_SECTION):
            assert section in data, f"{filename} is missing '{section}'"


class TestEntityNames:
    """Entity names go through HA's own translation layer."""

    @pytest.mark.parametrize("filename", FILES)
    def test_slot_name_has_placeholder(self, filename):
        name = _load(filename)["entity"]["sensor"]["slot"]["name"]
        assert "{slot}" in name, f"{filename}: slot name must interpolate {{slot}}"

    @pytest.mark.parametrize("filename", FILES)
    def test_last_activity_name_is_set(self, filename):
        name = _load(filename)["entity"]["sensor"]["last_activity"]["name"]
        assert name.strip()


class TestExceptions:
    """Service errors are translated by HA from the exceptions section."""

    @pytest.mark.parametrize("filename", FILES)
    @pytest.mark.parametrize("key", EXCEPTION_KEYS)
    def test_key_present_with_message(self, filename, key):
        exceptions = _load(filename)["exceptions"]
        assert key in exceptions, f"{filename} is missing exceptions.{key}"
        assert exceptions[key]["message"].strip()

    @pytest.mark.parametrize("key", EXCEPTION_KEYS)
    def test_placeholders_match_across_files(self, key):
        expected = _placeholders(_load("strings.json")["exceptions"][key]["message"])
        for filename in LANGUAGE_FILES:
            actual = _placeholders(_load(filename)["exceptions"][key]["message"])
            assert actual == expected, f"{filename} exceptions.{key}: {actual} != {expected}"

    def test_invalid_slot_has_min_max(self):
        message = _load("strings.json")["exceptions"]["invalid_slot"]["message"]
        assert _placeholders(message) == {"min", "max"}

    def test_lock_not_found_ieee_has_ieee(self):
        message = _load("strings.json")["exceptions"]["lock_not_found_ieee"]["message"]
        assert _placeholders(message) == {"ieee"}

    def test_multiple_locks_lists_the_ieees(self):
        message = _load("strings.json")["exceptions"]["multiple_locks"]["message"]
        assert _placeholders(message) == {"ieees"}

    def test_invalid_pin_names_the_lock_s_range(self):
        """The range comes from the lock, so the text cannot hardcode 4-8."""
        message = _load("strings.json")["exceptions"]["invalid_pin"]["message"]
        assert _placeholders(message) == {"min", "max"}


class TestOptionsErrors:
    """Form errors in the options flow, filled from description_placeholders."""

    def test_same_error_keys_everywhere(self):
        base = set(_load("strings.json")["options"]["error"])
        for filename in LANGUAGE_FILES:
            keys = set(_load(filename)["options"]["error"])
            assert keys == base, f"{filename}: missing {base - keys}, extra {keys - base}"

    @pytest.mark.parametrize("filename", LANGUAGE_FILES)
    def test_placeholders_match_across_files(self, filename):
        base = _load("strings.json")["options"]["error"]
        errors = _load(filename)["options"]["error"]
        for key, value in base.items():
            assert _placeholders(errors[key]) == _placeholders(value), (
                f"{filename} options.error.{key}: placeholders differ"
            )

    def test_invalid_pin_names_the_lock_s_range(self):
        message = _load("strings.json")["options"]["error"]["invalid_pin"]
        assert _placeholders(message) == {"min", "max"}


class TestRuntimeSection:
    """Runtime strings are read by localize.py, not by HA."""

    def test_all_languages_have_same_runtime_keys(self):
        base = set(_load("strings.json")[RUNTIME_SECTION])
        for filename in LANGUAGE_FILES:
            keys = set(_load(filename)[RUNTIME_SECTION])
            assert keys == base, f"{filename}: missing {base - keys}, extra {keys - base}"

    def test_placeholders_match_across_languages(self):
        base = _load("strings.json")[RUNTIME_SECTION]
        for filename in LANGUAGE_FILES:
            runtime = _load(filename)[RUNTIME_SECTION]
            for key, value in base.items():
                assert _placeholders(runtime[key]) == _placeholders(value), (
                    f"{filename} {RUNTIME_SECTION}.{key}: placeholders differ"
                )

    @pytest.mark.parametrize("filename", FILES)
    def test_no_em_dash(self, filename):
        """User-facing strings use a colon or parentheses, not an em-dash.

        Covers every section (config, options, entity, services, common),
        not only the runtime strings, since all of it reaches the user.
        """

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield from walk(value, f"{path}.{key}" if path else key)
            elif isinstance(node, str):
                yield path, node

        for path, value in walk(_load(filename), ""):
            assert EM_DASH not in value, f"{filename} {path} contains an em-dash"

    @pytest.mark.parametrize("filename", FILES)
    def test_no_empty_values(self, filename):
        for key, value in _load(filename)[RUNTIME_SECTION].items():
            assert value.strip(), f"{filename} {RUNTIME_SECTION}.{key} is empty"


def _keys_used_in_code():
    """Collect runtime keys the Python code looks up.

    Two sources: literal `.get("key")` calls on a `strings`/`s` object, and
    the `{action}_{source}` keys format_activity builds at runtime.
    """
    keys = set()
    for module in ("sensor.py", "config_flow.py", "coordinator.py", "services.py", "localize.py"):
        with open(_component_path(module)) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get" or not node.args:
                continue
            receiver = node.func.value
            is_strings = (
                isinstance(receiver, ast.Name) and receiver.id in ("strings", "s")
            ) or (isinstance(receiver, ast.Attribute) and receiver.attr == "strings")
            if not is_strings:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                keys.add(first.value)

    c = _load_const()
    sources = [
        c["SOURCE_ZIGBEE"],
        c["SOURCE_KEYPAD"],
        c["SOURCE_FINGERPRINT"],
        c["SOURCE_RFID"],
        c["SOURCE_AUTO"],
        c["SOURCE_UNATTRIBUTED"],
        c["SOURCE_UNKNOWN"],
    ]
    for action in (c["ACTION_LOCK"], c["ACTION_UNLOCK"]):
        for source in sources:
            keys.add(f"{action}_{source}")
    keys.add("activity_unknown")
    return keys


class TestRuntimeKeysUsedInCode:
    """Every key the code asks for must exist in every language file."""

    def test_collector_finds_something(self):
        """Guard against the ast collector silently matching nothing."""
        keys = _keys_used_in_code()
        assert "slot_vacant" in keys
        assert "slot_label" in keys
        assert "slot_fallback_name" in keys

    @pytest.mark.parametrize("filename", FILES)
    def test_all_used_keys_exist(self, filename):
        runtime = _load(filename)[RUNTIME_SECTION]
        missing = sorted(k for k in _keys_used_in_code() if k not in runtime)
        assert not missing, f"{filename} {RUNTIME_SECTION} is missing: {missing}"
