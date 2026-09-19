"""Tests for the runtime string localization module.

localize.py imports homeassistant.core for a type hint only, so a minimal
stub is enough to import the module without HA installed.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from .conftest import load_component_module


def _load_const():
    """Load const.py values without importing the package."""
    const_path = os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "onesti_lock", "const.py"
    )
    namespace = {}
    with open(const_path) as f:
        exec(f.read(), namespace)
    return namespace


localize = load_component_module("localize")

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
    """load_strings reads the common section from translations/<lang>.json."""

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


class TestFormatSlotLabel:
    """format_slot_label renders every slot label in the options flow."""

    @pytest.mark.parametrize(
        ("language", "expected"),
        [
            ("en", "Slot 3: Kari"),
            ("nb", "Slot 3: Kari"),
            ("sv", "Plats 3: Kari"),
            ("da", "Plads 3: Kari"),
        ],
    )
    def test_each_language(self, language, expected):
        strings = localize.load_strings(language)
        assert localize.format_slot_label(strings, 3, "Kari") == expected

    def test_name_is_inserted_verbatim(self):
        strings = localize.load_strings("en")
        assert localize.format_slot_label(strings, 12, "**Kari**") == "Slot 12: **Kari**"

    def test_falls_back_without_strings(self):
        assert localize.format_slot_label({}, 0, "Master") == "Slot 0: Master"


class TestFormatReservedSlotRow:
    """Reserved master rows in view slots never repeat the slot number."""

    @pytest.mark.parametrize("lang", ["en", "nb", "sv", "da"])
    @pytest.mark.parametrize("slot", [0, 1, 2])
    def test_unnamed_reads_master_once(self, lang, slot):
        localize = load_component_module("localize")
        strings = localize.load_strings(lang)
        row = localize.format_reserved_slot_row(strings, slot, "")
        label = strings["slot_label"].format(
            slot=slot, name=strings["slot_fallback_master"]
        )
        assert row == label
        prefix = strings["slot_label"].split("{slot}")[0]
        assert row.count(prefix.strip()) == 1
        assert strings["slot_status_master"] not in row

    @pytest.mark.parametrize("slot", [0, 1, 2])
    def test_named_gets_master_suffix(self, slot):
        localize = load_component_module("localize")
        strings = localize.load_strings("en")
        row = localize.format_reserved_slot_row(strings, slot, "Christian")
        assert row == f"Slot {slot}: Christian (master)"

    def test_english_rows(self):
        localize = load_component_module("localize")
        strings = localize.load_strings("en")
        assert localize.format_reserved_slot_row(strings, 0, "") == "Slot 0: Master"
        assert localize.format_reserved_slot_row(strings, 1, "") == "Slot 1: Master"

    def test_falls_back_without_strings(self):
        localize = load_component_module("localize")
        assert localize.format_reserved_slot_row({}, 2, "") == "Slot 2: Master"
        assert (
            localize.format_reserved_slot_row({}, 2, "Kari") == "Slot 2: Kari (master)"
        )


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
