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
        if not group.startswith("ha-"):
            continue  # unit runs tests/ against stubs and has no Home Assistant
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


# --- the Python floor --------------------------------------------------------
#
# The integration runs in the user's Home Assistant, so the lowest Python it
# has to work on is the lowest the minimum HA runs on, not the dev Python in
# .python-version. That floor is written out four times: the uv group that
# builds the minimum environment, requires-python, ruff's target-version and
# the interpreter CI compiles the integration with. mypy's python_version is
# deliberately not one of them (it parses the newest HA, see pyproject.toml).

PY_FLOOR_GROUP = "ha-minimum"
LOWER_BOUND = re.compile(r">=\s*(\d+)\.(\d+)(?:\.\d+)?")


def _python_floor() -> tuple[int, int]:
    """The floor as (major, minor), read from the ha-minimum group in pyproject.toml.

    That group's requires-python is the one place the number is derived rather
    than repeated: it is the range the minimum Home Assistant resolves in.
    """
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    spec = pyproject["tool"]["uv"]["dependency-groups"][PY_FLOOR_GROUP]["requires-python"]
    match = LOWER_BOUND.search(spec)
    assert match, f"[tool.uv.dependency-groups].{PY_FLOOR_GROUP}.requires-python is {spec!r} and has no >= bound"
    return int(match.group(1)), int(match.group(2))


def test_requires_python_is_the_floor():
    major, minor = _python_floor()
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    spec = pyproject["project"]["requires-python"]
    match = LOWER_BOUND.search(spec)
    assert match, f"project.requires-python is {spec!r} and has no >= bound"
    assert (int(match.group(1)), int(match.group(2))) == (major, minor), (
        f"project.requires-python is {spec!r}, but the {PY_FLOOR_GROUP} group runs Python "
        f"{major}.{minor}. The floor is the runtime, not the dev toolchain: raise or lower both."
    )


def test_ruff_targets_the_floor():
    major, minor = _python_floor()
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    target = pyproject["tool"]["ruff"]["target-version"]
    assert target == f"py{major}{minor}", (
        f"[tool.ruff] target-version is {target!r}, but the lowest Python the integration runs on "
        f"is {major}.{minor}. Ruff would suggest syntax the minimum Home Assistant cannot parse."
    )


def test_ci_compiles_the_integration_on_the_floor():
    major, minor = _python_floor()
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    found = re.findall(r"python(\d+)\.(\d+) -m compileall", ci)
    assert found, "ci.yml no longer runs compileall with a versioned interpreter, so nothing proves the floor compiles"
    for version in found:
        assert (int(version[0]), int(version[1])) == (major, minor), (
            f"ci.yml compiles the integration with python{version[0]}.{version[1]}, but the floor is "
            f"{major}.{minor}. Move the interpreter and the setup-python list with it."
        )


def test_the_minimum_test_target_runs_on_the_floor():
    major, minor = _python_floor()
    justfile = (REPO / "justfile").read_text(encoding="utf-8")
    match = re.search(r"minimum\)\s*python=(\d+)\.(\d+)", justfile)
    assert match, "the justfile no longer picks a Python for `just test-ha minimum`, so this rule checks nothing"
    assert (int(match.group(1)), int(match.group(2))) == (major, minor), (
        f"`just test-ha minimum` runs Python {match.group(1)}.{match.group(2)}, but the "
        f"{PY_FLOOR_GROUP} group resolves for {major}.{minor}."
    )


def test_the_dev_python_is_not_below_the_floor():
    major, minor = _python_floor()
    dev = (REPO / ".python-version").read_text(encoding="utf-8").strip()
    parts = tuple(int(part) for part in dev.split(".")[:2])
    assert parts >= (major, minor), (
        f".python-version is {dev}, below the {major}.{minor} floor the integration has to run on. "
        f"Development and CI may run ahead of the floor, never behind it."
    )
