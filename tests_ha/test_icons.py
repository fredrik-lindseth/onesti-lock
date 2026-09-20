"""Icons come from icons.json, the way Home Assistant reads them.

The entities set no `_attr_icon`: a translation key plus an entry in
icons.json lets a user override the icon per entity in the UI, and the
icon follows the entity even before it has a state. The services get
their icons the same way, which is what Developer tools and the
automation editor show.

The test loads the file through `homeassistant.helpers.icon` rather than
reading the JSON itself, so a key in the wrong place fails here. The set
of keys it demands is derived from the code, not listed: a new sensor
with a translation key, or a new action in services.yaml, has to bring an
icon with it.

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.icon import async_get_icons

from custom_components.onesti_lock.const import DOMAIN

_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "onesti_lock"

# The icons a user sees today. Changing one changes every install, so it
# is spelled out here rather than derived.
SENSOR_ICONS = {
    "slot": "mdi:key-variant",
    "last_activity": "mdi:door-closed-lock",
}


def _sensor_translation_keys() -> set[str]:
    """Every translation key sensor.py assigns, class-level or in __init__."""
    tree = ast.parse((_COMPONENT / "sensor.py").read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            if name == "_attr_translation_key":
                keys.add(value.value)
    return keys


def _service_names() -> set[str]:
    return set(yaml.safe_load((_COMPONENT / "services.yaml").read_text(encoding="utf-8")))


def test_the_collectors_find_something() -> None:
    """Guard against an empty set making the assertions below vacuous."""
    assert set(SENSOR_ICONS) <= _sensor_translation_keys()
    assert {"set_pin", "clear_pin", "set_name", "clear_slot"} <= _service_names()


def test_no_entity_sets_its_own_icon() -> None:
    """_attr_icon would win over icons.json and block the UI override."""
    assert "_attr_icon" not in (_COMPONENT / "sensor.py").read_text(encoding="utf-8")


async def test_every_sensor_translation_key_has_an_icon(hass: HomeAssistant) -> None:
    icons = await async_get_icons(hass, "entity", integrations=[DOMAIN])
    sensors = icons[DOMAIN]["sensor"]
    missing = sorted(key for key in _sensor_translation_keys() if key not in sensors)
    assert not missing, f"icons.json has no entity.sensor icon for: {missing}"
    for key in sensors:
        assert sensors[key]["default"].startswith("mdi:")


@pytest.mark.parametrize(("key", "icon"), sorted(SENSOR_ICONS.items()))
async def test_sensor_icons_are_unchanged(hass: HomeAssistant, key: str, icon: str) -> None:
    """The icons the entities carried before icons.json existed."""
    icons = await async_get_icons(hass, "entity", integrations=[DOMAIN])
    assert icons[DOMAIN]["sensor"][key]["default"] == icon


async def test_every_service_has_an_icon(hass: HomeAssistant) -> None:
    icons = await async_get_icons(hass, "services", integrations=[DOMAIN])
    services = icons[DOMAIN]
    missing = sorted(name for name in _service_names() if name not in services)
    assert not missing, f"icons.json has no services icon for: {missing}"
    for name in services:
        assert services[name]["service"].startswith("mdi:")
