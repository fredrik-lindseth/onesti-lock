"""The zigpy and Bluetooth versions installed here are the ones this Home Assistant runs.

Neither library is ours. zigpy comes with ZHA and habluetooth with the
Bluetooth integration, and both changed API between the two targets: which hook
a Door Lock cluster offers moved with zigpy, and bleak 0.22 against 3.0 is a
different client. Pinning them by hand was a paragraph of instructions about
reading manifests off the Home Assistant release. Home Assistant is installed
right here, so its own manifests can be read instead, and the day the HA pin
moves without the group in pyproject.toml following, this says so and names the
version to write.

The `zha` library itself is not installed (tests_ha/conftest.py stands in for
it), so its zigpy requirement cannot be read from metadata. The table below
carries it per zha release, and a release with no row fails with the two places
to look it up.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
from pathlib import Path

import homeassistant
import pytest

HA_ROOT = Path(homeassistant.__file__).resolve().parent

# The zigpy each pinned zha release depends on. Read off that release's own
# pyproject/metadata on PyPI, or `pip download zha==X`, when a row is missing.
ZHA_ZIGPY = {
    "0.0.59": "0.80.1",
    "2.2.2": "2.2.0",
}

# Integrations whose requirements this integration inherits at runtime.
# bluetooth.py runs on whatever the Bluetooth integration installed, and Home
# Assistant's bluetooth package imports the usb integration, so usb counts too.
INHERITED = ("bluetooth", "usb")


def _requirements(integration: str) -> list[str]:
    manifest = HA_ROOT / "components" / integration / "manifest.json"
    assert manifest.is_file(), f"Home Assistant {_ha_version()} has no components/{integration}/manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8"))["requirements"]


def _ha_version() -> str:
    return metadata.version("homeassistant")


def _pinned(requirement: str) -> tuple[str, str] | None:
    """("name", "version") for an exact pin, None for anything looser."""
    name, sep, version = requirement.partition("==")
    return (name, version) if sep and version and not any(c in version for c in ",<>! ") else None


def test_zigpy_is_the_version_this_home_assistants_zha_depends_on():
    requirements = _requirements("zha")
    pins = dict(filter(None, (_pinned(requirement) for requirement in requirements)))
    zha_version = pins.get("zha")
    assert zha_version, f"components/zha/manifest.json no longer pins zha exactly: {requirements}"

    expected = ZHA_ZIGPY.get(zha_version)
    assert expected, (
        f"Home Assistant {_ha_version()} runs zha {zha_version}, which has no row in ZHA_ZIGPY in "
        f"this file. Read the zigpy that zha {zha_version} requires off its metadata on PyPI, add "
        f"the row, and move the zigpy pin in the matching ha-* group in pyproject.toml to it."
    )
    installed = metadata.version("zigpy")
    assert installed == expected, (
        f"zigpy {installed} is installed, but Home Assistant {_ha_version()} runs zha {zha_version}, "
        f"which brings zigpy {expected}. The listener hook a Door Lock cluster offers depends on the "
        f"version, so tests_ha would be proving it against a zigpy no user has. Set "
        f"zigpy=={expected} in the matching ha-* group in pyproject.toml and run `uv lock`."
    )


@pytest.mark.parametrize("integration", INHERITED)
def test_the_inherited_stack_is_pinned_to_what_home_assistant_installs(integration):
    wrong = []
    for requirement in _requirements(integration):
        pin = _pinned(requirement)
        if pin is None:
            continue
        name, version = pin
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            wrong.append(f"{name}: not installed, Home Assistant requires {version}")
            continue
        if installed != version:
            wrong.append(f"{name}: {installed} installed, Home Assistant requires {version}")
    assert not wrong, (
        f"Home Assistant {_ha_version()} sets its {integration} integration up with other versions "
        f"than this environment has:\n  " + "\n  ".join(wrong) + "\n"
        f"custom_components/onesti_lock/bluetooth.py runs against whatever Home Assistant installed, "
        f"so the tests have to. Write these versions into the matching ha-* group in pyproject.toml "
        f"and run `uv lock`."
    )
