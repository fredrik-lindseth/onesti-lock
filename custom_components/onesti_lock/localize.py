"""Runtime string localization for Onesti Lock.

Sensor states and options-flow labels are built in Python and never pass
through HA's translation layer, so we resolve them ourselves against the
server language (hass.config.language). The strings live in the "runtime"
section of translations/<lang>.json so translators only have one place to
look, and we read those files directly rather than going through
async_get_translations, whose handling of non-standard categories is not
documented for custom integrations.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from homeassistant.core import HomeAssistant

from .const import DOMAIN

DEFAULT_LANGUAGE = "en"
RUNTIME_SECTION = "runtime"

# Cache lives under its own hass.data key, not inside hass.data[DOMAIN]:
# async_unload_entry treats an empty hass.data[DOMAIN] as "last entry gone"
# and a cache entry there would keep the services registered forever.
DATA_RUNTIME_STRINGS = f"{DOMAIN}_runtime_strings"

# HA uses "nb" for bokmål; map the other Norwegian codes onto it so
# nynorsk and legacy "no" users do not silently fall back to English.
_LANGUAGE_ALIASES = {"no": "nb", "nn": "nb"}

_TRANSLATIONS_DIR = Path(__file__).parent / "translations"


def normalize_language(language: str | None) -> str:
    """Reduce an HA language code to a file we might have on disk."""
    if not language:
        return DEFAULT_LANGUAGE
    lang = language.lower().replace("_", "-").split("-")[0]
    return _LANGUAGE_ALIASES.get(lang, lang)


def load_strings(language: str | None) -> dict[str, str]:
    """Read runtime strings for a language, merged over English defaults.

    Blocking file IO: call via async_get_strings, never from the event loop.
    Merging over English means a key missing from one language degrades to
    English instead of raising at state-write time.
    """
    merged = _read_section(DEFAULT_LANGUAGE)
    lang = normalize_language(language)
    if lang != DEFAULT_LANGUAGE:
        merged.update(_read_section(lang))
    return merged


def _read_section(language: str) -> dict[str, str]:
    path = _TRANSLATIONS_DIR / f"{language}.json"
    try:
        with path.open(encoding="utf-8") as file:
            return dict(json.load(file).get(RUNTIME_SECTION, {}))
    except (OSError, ValueError):
        # A missing or malformed file must not take the integration down;
        # English is read first, so the worst case is an empty overlay.
        return {}


async def async_get_strings(hass: HomeAssistant, language: str | None) -> Mapping[str, str]:
    """Load runtime strings off the event loop, cached per language.

    The cached mapping is shared by every config entry, the coordinator
    and the options flow, so it is wrapped read-only: one in-place write
    would poison every consumer in the HA instance at once. A writer gets
    an immediate TypeError at the write site instead.
    """
    cache = hass.data.setdefault(DATA_RUNTIME_STRINGS, {})
    lang = normalize_language(language)
    if lang not in cache:
        cache[lang] = MappingProxyType(
            await hass.async_add_executor_job(load_strings, lang)
        )
    return cache[lang]


def format_activity(
    strings: Mapping[str, str], action: str, source: str, user_name: str
) -> str:
    """Render the activity sensor state as a full sentence.

    Full sentences per (action, source) instead of verb + suffix
    composition, because composition does not survive translation
    (word order differs between languages).
    """
    template = strings.get(f"{action}_{source}")
    if template is None:
        # Unknown action byte from firmware we have not seen yet
        return strings.get("activity_unknown", "Unknown activity")
    return template.format(name=user_name)
