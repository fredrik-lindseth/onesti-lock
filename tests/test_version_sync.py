"""Keep the minimum Home Assistant version in one place.

hacs.json is what users are promised. The ha-minimum dependency group is what
`just test-ha minimum` actually tests, and README, AGENTS.md, justfile and
pyproject.toml repeat the number in prose. Nothing kept those copies in sync,
so hacs.json could be raised while the minimum environment kept testing the
old release. This reads them together and fails when they disagree.
"""

import json
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = "pytest-homeassistant-custom-component"

# Files allowed to name a full HA version. Every one they name must be a
# version uv.lock actually tests. docs/ holds history and is left out.
FILES_WITH_HA_VERSIONS = ("README.md", "AGENTS.md", "justfile", "pyproject.toml", "hacs.json")
HA_VERSION = re.compile(r"\b20\d\d\.\d{1,2}\.\d+\b")


def _lock() -> dict:
    return tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))


def _ha_version_per_group() -> dict[str, str]:
    """The homeassistant release each ha-* group resolves to, read from uv.lock.

    The groups pin the plugin, and each plugin release pins homeassistant
    exactly, so the chain is project group -> plugin version -> homeassistant.
    """
    packages = _lock()["package"]
    (project,) = [p for p in packages if p["name"] == "onesti-lock"]
    result = {}
    for group, deps in project["dev-dependencies"].items():
        (plugin_version,) = [d["version"] for d in deps if d["name"] == PLUGIN]
        (plugin,) = [p for p in packages if p["name"] == PLUGIN and p["version"] == plugin_version]
        (ha,) = [d["version"] for d in plugin["dependencies"] if d["name"] == "homeassistant"]
        result[group] = ha
    return result


def _hacs_minimum() -> str:
    return json.loads((REPO / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]


def test_ha_minimum_group_tests_the_version_hacs_json_promises():
    locked = _ha_version_per_group()
    assert set(locked) == {"ha-minimum", "ha-current"}
    assert locked["ha-minimum"] == _hacs_minimum(), (
        f"hacs.json promises HA {_hacs_minimum()}, but the ha-minimum group in uv.lock "
        f"tests {locked['ha-minimum']}. Move the plugin pin in pyproject.toml and run `uv lock`."
    )


def test_every_ha_version_in_prose_is_a_locked_one():
    locked = set(_ha_version_per_group().values())
    for name in FILES_WITH_HA_VERSIONS:
        text = (REPO / name).read_text(encoding="utf-8")
        for version in HA_VERSION.findall(text):
            assert version in locked, f"{name} names HA {version}, but uv.lock tests only {sorted(locked)}"


def test_readme_states_the_hacs_json_minimum():
    major_minor = ".".join(_hacs_minimum().split(".")[:2])
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert f"Home Assistant {major_minor} or newer" in readme, (
        f"README.md does not say 'Home Assistant {major_minor} or newer', which is what hacs.json promises"
    )
