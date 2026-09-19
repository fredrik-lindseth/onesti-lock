"""Tests for options flow error handling and UX.

These tests verify the error-handling logic in the options flow without
importing homeassistant. We parse the config_flow.py source and validate
the error mapping patterns, and verify strings.json has all required keys.
"""
from __future__ import annotations

import ast
import json
import os
import textwrap

import pytest


def _component_path(*parts):
    """Get path relative to the component directory."""
    return os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", *parts
    )


def _load_strings():
    """Load strings.json."""
    with open(_component_path("strings.json")) as f:
        return json.load(f)


def _load_source():
    """Load config_flow.py source as AST."""
    with open(_component_path("config_flow.py")) as f:
        return f.read()


def _load_source_ast():
    """Parse config_flow.py into AST."""
    return ast.parse(_load_source())


class TestOptionsFlowErrorStrings:
    """Verify all error codes used in config_flow.py exist in strings.json."""

    def test_all_error_codes_have_strings(self):
        """Every error code assigned in options flow must have a strings.json entry."""
        source = _load_source()
        strings = _load_strings()
        error_strings = strings["options"]["error"]

        # Extract all error code assignments like: errors["base"] = "lock_unreachable"
        # and self._set_pin_error = "lock_unreachable"
        import re
        error_codes = set()
        for match in re.finditer(r'errors\["(?:base|code|slot)"\]\s*=\s*"(\w+)"', source):
            error_codes.add(match.group(1))
        for match in re.finditer(r'self\._(?:set_pin|clear_pin)_error\s*=\s*"(\w+)"', source):
            error_codes.add(match.group(1))

        for code in error_codes:
            assert code in error_strings, (
                f"Error code '{code}' used in config_flow.py but missing from strings.json"
            )

    def test_timeout_maps_to_lock_unreachable(self):
        """TimeoutError should map to 'lock_unreachable', not 'unknown'."""
        source = _load_source()
        # Verify the pattern: TimeoutError is caught and mapped to lock_unreachable
        assert "TimeoutError" in source
        # After TimeoutError catch, the next error assignment should be lock_unreachable
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "asyncio.TimeoutError, TimeoutError" in line:
                # Look at the next few lines for the error assignment
                block = "\n".join(lines[i:i+5])
                assert "lock_unreachable" in block, (
                    f"TimeoutError handler should set 'lock_unreachable', got:\n{block}"
                )

    def test_generic_exception_maps_to_unknown(self):
        """Generic Exception should map to 'unknown'."""
        source = _load_source()
        lines = source.split("\n")
        found = False
        for i, line in enumerate(lines):
            # Look for bare "except Exception:" after the TimeoutError handler
            if "except Exception:" in line and i > 0:
                block = "\n".join(lines[i:i+5])
                if "unknown" in block:
                    found = True
                    break
        assert found, "Generic Exception handler should set 'unknown' error"

    def test_unknown_error_string_exists(self):
        """strings.json must have the 'unknown' error message."""
        strings = _load_strings()
        assert "unknown" in strings["options"]["error"]

    def test_lock_unreachable_string_exists(self):
        """strings.json must have the 'lock_unreachable' error message."""
        strings = _load_strings()
        assert "lock_unreachable" in strings["options"]["error"]


class TestOptionsFlowProgressStrings:
    """Verify progress step strings exist."""

    def test_set_pin_progress_string(self):
        strings = _load_strings()
        assert "progress" in strings["options"]
        assert "set_pin_progress" in strings["options"]["progress"]

    def test_clear_pin_progress_string(self):
        strings = _load_strings()
        assert "progress" in strings["options"]
        assert "clear_pin_progress" in strings["options"]["progress"]


class TestOptionsFlowStructure:
    """Verify the options flow has the expected async_show_progress pattern."""

    def test_has_progress_steps(self):
        """Flow must have set_pin_progress and clear_pin_progress steps."""
        source = _load_source()
        assert "async_step_set_pin_progress" in source
        assert "async_step_clear_pin_progress" in source

    def test_has_progress_done_steps(self):
        """Flow must have _done steps that HA calls when task completes."""
        source = _load_source()
        assert "async_step_set_pin_progress_done" in source
        assert "async_step_clear_pin_progress_done" in source

    def test_progress_uses_progress_task_parameter(self):
        """async_show_progress must use progress_task= (mandatory since HA 2024.5)."""
        source = _load_source()
        assert "progress_task=" in source

    def test_no_wake_reminder_in_descriptions(self):
        """'Husk å vekke låsen først!' should be removed from all strings."""
        strings = _load_strings()
        raw = json.dumps(strings)
        assert "vekke låsen" not in raw.lower()
        assert "wake the lock" not in raw.lower()
        # Check translations too
        for lang in ("en", "nb"):
            with open(_component_path("translations", f"{lang}.json")) as f:
                data = json.load(f)
            raw = json.dumps(data)
            assert "wake the lock" not in raw.lower(), f"Wake reminder still in {lang}.json"
            assert "vekke låsen" not in raw.lower(), f"Wake reminder still in {lang}.json"
            assert "vekk låsen" not in raw.lower(), f"Wake reminder still in {lang}.json"

    def test_form_data_preserved_on_error(self):
        """Flow should use add_suggested_values_to_schema for error re-display."""
        source = _load_source()
        assert "add_suggested_values_to_schema" in source

    def test_set_pin_error_routes_back_to_form(self):
        """set_pin_progress_done should route back to set_pin on error."""
        source = _load_source()
        # The done handler should call async_show_progress_done(next_step_id="set_pin")
        assert 'next_step_id="set_pin"' in source

    def test_clear_pin_error_routes_back_to_form(self):
        """clear_pin_progress_done should route back to clear_pin on error."""
        source = _load_source()
        assert 'next_step_id="clear_pin"' in source

    def test_exceptions_never_propagate(self):
        """Both done handlers must have try/except wrapping task.result()."""
        source = _load_source()
        tree = _load_source_ast()

        # Find the NimlyProOptionsFlow class
        options_cls = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "NimlyProOptionsFlow":
                options_cls = node
                break
        assert options_cls is not None

        # Find the _done methods and verify they have try/except
        done_methods = []
        for node in ast.walk(options_cls):
            if isinstance(node, ast.AsyncFunctionDef) and node.name.endswith("_done"):
                done_methods.append(node.name)
                # Check that the function body contains a Try node
                has_try = any(isinstance(n, ast.Try) for n in ast.walk(node))
                assert has_try, f"{node.name} must wrap task.result() in try/except"

        assert len(done_methods) == 2, f"Expected 2 done methods, found: {done_methods}"


class TestOptionsFlowInstanceVars:
    """Verify the options flow has required class/instance variables."""

    def test_has_task_and_error_vars(self):
        """Class must declare all progress-related variables."""
        source = _load_source()
        assert "_set_pin_task" in source
        assert "_set_pin_input" in source
        assert "_set_pin_error" in source
        assert "_clear_pin_task" in source
        assert "_clear_pin_error" in source


def _step_source(name):
    source = _load_source()
    for node in ast.walk(_load_source_ast()):
        is_func = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if is_func and node.name == name:
            return ast.get_source_segment(source, node)
    pytest.fail(f"{name} not found in config_flow.py")


class TestNameSlotValidation:
    """name_slot accepts every slot, like the set_name service (issue #6)."""

    def test_accepts_slot_0_up_to_max_slots(self):
        body = _step_source("async_step_name_slot")
        assert "0 <= slot < MAX_SLOTS" in body, (
            "name_slot must accept 0 to MAX_SLOTS - 1, master slots included"
        )
        assert "SLOT_FIRST_USER" not in body

    def test_out_of_range_maps_to_invalid_slot(self):
        body = _step_source("async_step_name_slot")
        assert 'errors["slot"] = "invalid_slot"' in body

    def test_name_is_optional_so_it_can_be_removed(self):
        """An empty name is the only way to unname a reserved slot."""
        body = _step_source("async_step_name_slot")
        assert 'vol.Optional("name", default="")' in body

    @pytest.mark.parametrize("filename", ["strings.json", "translations/en.json"])
    def test_invalid_slot_message_starts_at_0(self, filename):
        with open(_component_path(*filename.split("/"))) as f:
            message = json.load(f)["options"]["error"]["invalid_slot"]
        assert "between 0 and 999" in message


class TestReservedSlotsFloor:
    """PIN steps start at the lock's first user slot, not a constant."""

    def test_set_pin_schema_starts_at_first_user_slot(self):
        body = _step_source("_build_set_pin_schema")
        assert "first_user_slot()" in body
        assert "SLOT_FIRST_USER" not in body

    def test_clear_pin_skips_reserved_slots(self):
        body = _step_source("async_step_clear_pin")
        assert "first_user_slot()" in body
        assert "range(first, MAX_SLOTS)" in body

    def test_view_slots_marks_reserved_slots_as_master(self):
        body = _step_source("async_step_view_slots")
        assert "first_user_slot()" in body
        assert "slot_status_master" in body

    def test_view_slots_names_reserved_slots_like_the_activity_sensor(self):
        """Slot 0 always holds a master code, so it is never shown as Vacant.

        The reserved rows take their name from get_slot_name, which is what
        the activity sensor shows ("Master" for an unnamed slot 0).
        """
        body = _step_source("async_step_view_slots")
        reserved_loop = body.split("for i in range(first):", 1)[1].split(
            "for i in range(first, ", 1
        )[0]
        assert "get_slot_name(i)" in reserved_loop
        assert "vacant" not in reserved_loop


class TestSettingsStep:
    """The settings step stores reserved_slots next to the slot data."""

    def test_settings_in_menu(self):
        body = _step_source("async_step_init")
        assert '"settings"' in body
        strings = _load_strings()
        assert "settings" in strings["options"]["step"]["init"]["menu_options"]

    def test_step_exists_with_strings(self):
        _step_source("async_step_settings")
        step = _load_strings()["options"]["step"]["settings"]
        assert step["title"].strip()
        assert step["description"].strip()
        assert step["data"]["reserved_slots"].strip()

    def test_schema_bounded_by_constants(self):
        body = _step_source("async_step_settings")
        assert "CONF_RESERVED_SLOTS" in body
        assert "vol.Range(min=RESERVED_SLOTS_MIN, max=RESERVED_SLOTS_MAX)" in body
        assert "vol.Coerce(int)" in body

    def test_default_comes_from_coordinator(self):
        body = _step_source("async_step_settings")
        assert "default=self._coordinator().first_user_slot()" in body

    def test_saves_without_dropping_other_options(self):
        """Slot data lives in the same options dict and must survive."""
        body = _step_source("async_step_settings")
        assert "**self.config_entry.options" in body
        assert "async_create_entry" in body

    def test_error_codes_have_strings(self):
        """Every options error code the flow can raise has a message."""
        errors = _load_strings()["options"]["error"]
        for code in ("invalid_pin", "invalid_slot", "lock_unreachable", "unknown"):
            assert errors[code].strip()
