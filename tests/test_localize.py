"""Tests for the runtime string localization module.

localize.py imports homeassistant.core for a type hint only, so a minimal
stub is enough to import the module without HA installed.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types

import pytest

if "homeassistant" not in sys.modules:
    _ha = types.ModuleType("homeassistant")
    _core = types.ModuleType("homeassistant.core")
    _core.HomeAssistant = object
    _ha.core = _core
    sys.modules["homeassistant"] = _ha
    sys.modules["homeassistant.core"] = _core


_COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "onesti_lock"
)
_PACKAGE = "onesti_lock_under_test"


def _load_localize():
    """Import localize.py under a stub package.

    The module uses a relative import for DOMAIN, so it needs a parent
    package. The stub package is never executed, which keeps the real
    __init__.py (and its homeassistant imports) out of the way.
    """
    if _PACKAGE not in sys.modules:
        package = types.ModuleType(_PACKAGE)
        package.__path__ = [_COMPONENT_DIR]
        sys.modules[_PACKAGE] = package
    name = f"{_PACKAGE}.localize"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_COMPONENT_DIR, "localize.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_const():
    """Load const.py values without importing the package."""
    const_path = os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "const.py"
    )
    namespace = {}
    with open(const_path) as f:
        exec(f.read(), namespace)
    return namespace


localize = _load_localize()

LANGUAGES = ["en", "nb", "sv", "da"]


class TestNormalizeLanguage:
    """Language codes from hass.config.language are messy; normalize them."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("sv", "sv"),
            ("sv-SE", "sv"),
            ("SV_se", "sv"),
            ("no", "nb"),
            ("nn", "nb"),
            ("nb", "nb"),
            ("da", "da"),
            ("en-GB", "en"),
            ("de", "de"),
            (None, "en"),
            ("", "en"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert localize.normalize_language(raw) == expected


class TestLoadStrings:
    """load_strings reads the runtime section from translations/<lang>.json."""

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_language_loads(self, language):
        strings = localize.load_strings(language)
        assert strings
        assert strings["activity_unknown"]

    def test_unknown_language_falls_back_to_english(self):
        assert localize.load_strings("de") == localize.load_strings("en")

    def test_none_falls_back_to_english(self):
        assert localize.load_strings(None) == localize.load_strings("en")

    def test_regional_variant_resolves(self):
        assert localize.load_strings("sv-SE") == localize.load_strings("sv")

    def test_norwegian_aliases_resolve(self):
        nb = localize.load_strings("nb")
        assert localize.load_strings("no") == nb
        assert localize.load_strings("nn") == nb

    def test_missing_file_does_not_raise(self):
        # Every language merges over English, so a bogus code degrades
        # silently rather than taking the integration down.
        assert localize.load_strings("zz") == localize.load_strings("en")


class TestFormatActivity:
    """format_activity renders one full sentence per (action, source)."""

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_every_action_source_combination_renders(self, language):
        c = _load_const()
        strings = localize.load_strings(language)
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
                result = localize.format_activity(strings, action, source, "Kari")
                assert result, f"{language} {action}_{source} rendered empty"
                assert "{" not in result, f"{language} {action}_{source}: {result}"

    @pytest.mark.parametrize(
        ("language", "action", "source", "expected"),
        [
            ("nb", "unlock", "keypad", "Kari låste opp med kode"),
            ("sv", "unlock", "keypad", "Kari låste upp med kod"),
            ("da", "unlock", "keypad", "Kari låste op med kode"),
            ("en", "unlock", "keypad", "Kari unlocked with code"),
            ("en", "lock", "auto", "Auto-lock"),
            ("nb", "lock", "auto", "Auto-lås"),
            ("nb", "lock", "zigbee", "Låst via Zigbee"),
            ("nb", "unlock", "zigbee", "Låst opp via Zigbee"),
            ("sv", "unlock", "zigbee", "Upplåst via Zigbee"),
            ("da", "lock", "unattributed", "Låst"),
        ],
    )
    def test_exact_sentences(self, language, action, source, expected):
        strings = localize.load_strings(language)
        assert localize.format_activity(strings, action, source, "Kari") == expected

    @pytest.mark.parametrize("action", ["unknown", "garbage"])
    @pytest.mark.parametrize("language", LANGUAGES)
    def test_unknown_action_falls_back(self, language, action):
        strings = localize.load_strings(language)
        result = localize.format_activity(strings, action, "keypad", "Kari")
        assert result == strings["activity_unknown"]

    def test_empty_strings_do_not_raise(self):
        """Both translation files unreadable is survivable, not fatal."""
        assert localize.format_activity({}, "unlock", "keypad", "Kari")


class FakeHass:
    """Just enough hass for async_get_strings: data dict + executor."""

    def __init__(self):
        self.data = {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class TestAsyncGetStringsCache:
    """The shared cache must be reusable but never writable."""

    def test_cache_returns_same_object_per_language(self):
        hass = FakeHass()
        first = asyncio.run(localize.async_get_strings(hass, "nb"))
        second = asyncio.run(localize.async_get_strings(hass, "nb"))
        assert first is second
        assert first.get("slot_vacant")

    def test_cached_strings_are_read_only(self):
        hass = FakeHass()
        strings = asyncio.run(localize.async_get_strings(hass, "en"))
        with pytest.raises(TypeError):
            strings["slot_vacant"] = "poisoned"

    def test_languages_get_separate_entries(self):
        hass = FakeHass()
        en = asyncio.run(localize.async_get_strings(hass, "en"))
        nb = asyncio.run(localize.async_get_strings(hass, "no"))
        assert en is not nb
        assert nb.get("slot_vacant") != en.get("slot_vacant")
