"""Tests for config flow import compatibility.

Verifies that config_flow.py uses modern HA imports that work on HA 2025.1+
(FlowResult was removed from homeassistant.data_entry_flow in 2025.1).
"""
from __future__ import annotations

import ast
import os


def _config_flow_path():
    return os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "config_flow.py"
    )


def _parse_config_flow():
    with open(_config_flow_path()) as f:
        return ast.parse(f.read())


class TestConfigFlowImports:
    """Verify config_flow.py uses HA 2025.1+ compatible imports."""

    def test_no_import_from_data_entry_flow(self):
        """config_flow.py must NOT import from homeassistant.data_entry_flow.

        FlowResult was removed in HA 2025.1. Using it causes
        'Config flow could not be loaded: 500 Internal Server Error'.
        """
        tree = _parse_config_flow()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "data_entry_flow" not in node.module, (
                    f"Found import from {node.module} — "
                    "use ConfigFlowResult/OptionsFlowResult from "
                    "homeassistant.config_entries instead"
                )

    def test_uses_config_flow_result(self):
        """Config flow steps should return ConfigFlowResult."""
        with open(_config_flow_path()) as f:
            source = f.read()
        assert "ConfigFlowResult" in source

    def test_no_options_flow_result(self):
        """Must not use OptionsFlowResult — it doesn't exist in HA.

        Options flow methods should use ConfigFlowResult instead.
        """
        with open(_config_flow_path()) as f:
            source = f.read()
        assert "OptionsFlowResult" not in source

    def test_options_flow_no_config_entry_in_constructor(self):
        """OptionsFlow should not take config_entry in __init__.

        Modern HA auto-populates self.config_entry. Passing it to
        the constructor is the deprecated OptionsFlowWithConfigEntry pattern.
        """
        tree = _parse_config_flow()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "OptionsFlow" in node.name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        # __init__ should not have config_entry parameter
                        args = [a.arg for a in item.args.args if a.arg != "self"]
                        assert "config_entry" not in args, (
                            "OptionsFlow should not take config_entry in __init__ — "
                            "use self.config_entry (auto-populated by HA)"
                        )

    def test_options_flow_uses_self_config_entry(self):
        """OptionsFlow should use self.config_entry, not self._entry."""
        with open(_config_flow_path()) as f:
            source = f.read()
        assert "self._entry" not in source, (
            "Use self.config_entry (auto-populated) instead of self._entry"
        )
