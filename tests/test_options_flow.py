"""Options flow strings.

The flow's behaviour is tested against a real Home Assistant in
tests_ha/test_options_flow.py. What stays here is the part that needs no
Home Assistant: every error code, progress step and settings field the flow
uses has a message in strings.json and the translations.
"""
from __future__ import annotations

import json
import os

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


class TestOptionsFlowErrorStrings:
    """Every error code the options flow can raise has a message."""

    def test_error_codes_have_strings(self):
        errors = _load_strings()["options"]["error"]
        for code in (
            "invalid_pin",
            "invalid_slot",
            "lock_unreachable",
            "lock_rejected",
            "lock_rejected_duplicate",
            "lock_rejected_memory_full",
            "unknown",
        ):
            assert errors[code].strip()

    def test_unknown_error_string_exists(self):
        assert "unknown" in _load_strings()["options"]["error"]

    def test_lock_unreachable_string_exists(self):
        assert "lock_unreachable" in _load_strings()["options"]["error"]

    @pytest.mark.parametrize("filename", ["strings.json", "translations/en.json"])
    def test_invalid_slot_message_starts_at_0(self, filename):
        with open(_component_path(*filename.split("/"))) as f:
            message = json.load(f)["options"]["error"]["invalid_slot"]
        assert "between 0 and 999" in message

    def test_no_active_slots_abort_string(self):
        assert _load_strings()["options"]["abort"]["no_active_slots"].strip()


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


class TestSettingsStrings:
    """The settings step has a menu entry, a title and a field label."""

    def test_settings_in_menu_strings(self):
        strings = _load_strings()
        assert "settings" in strings["options"]["step"]["init"]["menu_options"]

    def test_step_has_strings(self):
        step = _load_strings()["options"]["step"]["settings"]
        assert step["title"].strip()
        assert step["description"].strip()
        assert step["data"]["reserved_slots"].strip()
