"""The installed ZHA still has the gateway lookup that conftest.py stands in for.

tests_ha cannot import homeassistant.components.zha.helpers, since it needs
the zha library, so conftest.py puts a stand-in for get_zha_gateway_proxy in
sys.modules. Every other test here then runs against that stand-in, and a
rename or a new contract in Home Assistant would pass them all and break
only in production.

This test reads helpers.py from the installed Home Assistant, compiles the
real get_zha_gateway_proxy and get_zha_data together with the HAZHAData
dataclass they build, and runs them next to the stand-in on the same fake
hass. Nothing else from helpers.py is executed, so the zha library is not
needed. It runs on both pinned targets.
"""

from __future__ import annotations
import __future__

import ast
import collections
import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import homeassistant.components
import pytest

HELPERS_PATH = Path(homeassistant.components.__path__[0]) / "zha" / "helpers.py"
# What zha.py imports, and what the stand-in in conftest.py mimics.
CONTRACT = "get_zha_gateway_proxy"
# What the real function leans on, compiled alongside it.
SUPPORT = ("get_zha_data", "HAZHAData")


def _real_helpers() -> dict[str, Any]:
    """The contract function and its support, compiled from the installed source."""
    tree = ast.parse(HELPERS_PATH.read_text(), filename=str(HELPERS_PATH))
    wanted = {CONTRACT, *SUPPORT}
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef) and node.name in wanted
    ]
    found = {node.name for node in nodes}
    assert found == wanted, f"missing from {HELPERS_PATH}: {sorted(wanted - found)}"

    from homeassistant.components.zha.const import DATA_ZHA

    namespace: dict[str, Any] = {
        "DATA_ZHA": DATA_ZHA,
        "collections": collections,
        "dataclasses": dataclasses,
    }
    module = ast.Module(body=nodes, type_ignores=[])
    # Annotations name ZHA and zigpy types that are not importable here.
    code = compile(module, str(HELPERS_PATH), "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True)
    exec(code, namespace)
    return namespace


@pytest.fixture(scope="module")
def real() -> dict[str, Any]:
    return _real_helpers()


@pytest.fixture
def stand_in():
    """The function tests_ha actually runs against."""
    return sys.modules["homeassistant.components.zha.helpers"].get_zha_gateway_proxy


def test_zha_keeps_its_data_under_the_key_the_fixtures_use() -> None:
    """mock_zha in conftest.py writes hass.data["zha"]."""
    from homeassistant.components.zha.const import DATA_ZHA

    assert DATA_ZHA == "zha"


def test_a_running_gateway_is_returned(real, stand_in) -> None:
    gateway_proxy = object()
    hass_real = SimpleNamespace(data={"zha": real["HAZHAData"](gateway_proxy=gateway_proxy)})
    hass_stand_in = SimpleNamespace(data={"zha": SimpleNamespace(gateway_proxy=gateway_proxy)})

    assert real[CONTRACT](hass_real) is gateway_proxy
    assert stand_in(hass_stand_in) is gateway_proxy


def test_no_gateway_raises_value_error(real, stand_in) -> None:
    """zha.py catches exactly ValueError and reads it as ZHA not running."""
    with pytest.raises(ValueError):
        real[CONTRACT](SimpleNamespace(data={"zha": real["HAZHAData"]()}))
    with pytest.raises(ValueError):
        stand_in(SimpleNamespace(data={"zha": SimpleNamespace(gateway_proxy=None)}))


def test_zha_never_set_up_raises_value_error(real, stand_in) -> None:
    """With nothing under hass.data["zha"] both still raise, not KeyError."""
    with pytest.raises(ValueError):
        real[CONTRACT](SimpleNamespace(data={}))
    with pytest.raises(ValueError):
        stand_in(SimpleNamespace(data={}))
