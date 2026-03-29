"""Tests for slot data constants and validation."""
from __future__ import annotations

import json
import os

import pytest


def _load_const():
    """Load const.py values without importing the full package (avoids homeassistant dep)."""
    const_path = os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "const.py"
    )
    namespace = {}
    with open(const_path) as f:
        exec(f.read(), namespace)
    return namespace


class TestConstants:
    """Test integration constants."""

    def test_domain(self):
        c = _load_const()
        assert c["DOMAIN"] == "onesti_lock"

    def test_slot_first_user(self):
        """User slots start at 3 (0-2 reserved for master codes)."""
        c = _load_const()
        assert c["SLOT_FIRST_USER"] == 3

    def test_max_slots(self):
        c = _load_const()
        assert c["MAX_SLOTS"] == 200

    def test_num_user_slots(self):
        """UI shows 10 slots (3-12)."""
        c = _load_const()
        assert c["NUM_USER_SLOTS"] == 10
        assert c["SLOT_FIRST_USER"] + c["NUM_USER_SLOTS"] == 13

    def test_supported_models(self):
        """All known Onesti whitelabel models."""
        c = _load_const()
        models = c["SUPPORTED_MODELS"]
        assert "NimlyPRO" in models
        assert "NimlyPRO24" in models
        assert "easyCodeTouch_v1" in models
        assert "EasyCodeTouch" in models
        assert "EasyFingerTouch" in models

    def test_manufacturer(self):
        c = _load_const()
        assert c["MANUFACTURER"] == "Onesti Products AS"

    def test_default_slot(self):
        c = _load_const()
        slot = c["DEFAULT_SLOT"]
        assert slot["name"] == ""
        assert slot["has_pin"] is False
        assert slot["has_rfid"] is False

    def test_doorlock_cluster_id(self):
        c = _load_const()
        assert c["DOORLOCK_CLUSTER_ID"] == 0x0101


class TestManifest:
    """Test manifest.json consistency."""

    def test_manifest_domain_matches_const(self):
        manifest_path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)
        c = _load_const()
        assert manifest["domain"] == c["DOMAIN"]

    def test_manifest_has_zha_dependency(self):
        manifest_path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert "zha" in manifest["dependencies"]

    def test_manifest_version_format(self):
        manifest_path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)
        parts = manifest["version"].split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


class TestTranslations:
    """Test translation files are complete and consistent."""

    def _load_json(self, filename):
        path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "onesti_lock", filename
        )
        with open(path) as f:
            return json.load(f)

    def _get_keys(self, d, prefix=""):
        """Recursively get all keys from nested dict."""
        keys = set()
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.update(self._get_keys(v, full))
            else:
                keys.add(full)
        return keys

    def test_en_translation_exists(self):
        data = self._load_json("translations/en.json")
        assert "config" in data
        assert "options" in data

    def test_nb_translation_exists(self):
        data = self._load_json("translations/nb.json")
        assert "config" in data
        assert "options" in data

    def test_translations_have_same_keys(self):
        """English and Norwegian translations should have identical structure."""
        en = self._load_json("translations/en.json")
        nb = self._load_json("translations/nb.json")
        en_keys = self._get_keys(en)
        nb_keys = self._get_keys(nb)
        assert en_keys == nb_keys, f"Missing in nb: {en_keys - nb_keys}, extra in nb: {nb_keys - en_keys}"

    def test_strings_json_has_same_keys_as_en(self):
        """strings.json should match en.json structure."""
        strings = self._load_json("strings.json")
        en = self._load_json("translations/en.json")
        strings_keys = self._get_keys(strings)
        en_keys = self._get_keys(en)
        assert strings_keys == en_keys
