"""Conftest for the real Home Assistant tests.

This tree runs against a real Home Assistant from
pytest-homeassistant-custom-component, unlike tests/, which stubs
homeassistant.* in sys.modules. The two cannot share an environment: the
stubs and the real package would collide in the same sys.modules. So they
live in separate trees with separate conftests, and tests_ha/ runs in its
own virtual environment per target (`just test-ha minimum|current`).

How ZHA is mocked
-----------------
The manifest lists `zha` as a dependency, so Home Assistant sets ZHA up
before this integration. The real ZHA integration cannot load here: it
imports the `zha` library (and zigpy with it), which the test plugin does
not install, and adding it would mean a new package. Two things stand in
for it instead:

1. `zha` is marked as already set up in `hass.config.components`. Home
   Assistant then treats the dependency as satisfied and never imports
   homeassistant.components.zha.
2. `hass.data["zha"]` gets a fake object with a `gateway_proxy`. That is
   the only entry point the integration uses to reach ZHA: every lookup in
   custom_components/onesti_lock/zha.py goes through `_gateway_proxy()`,
   which reads `hass.data["zha"].gateway_proxy`. Mocking at that level
   leaves zha.py's own device iteration and cluster chain walk under test,
   and it keeps working if zha.py is reshaped, as long as it still reads
   ZHA's object layout.

The fake proxy mirrors the real chain: ZHADeviceProxy -> Device (with
manufacturer and model) -> zigpy device (with endpoints and clusters).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# The repo root on sys.path, so both `import custom_components.onesti_lock`
# and the Home Assistant loader's own `import custom_components` find the
# integration.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

LOCK_IEEE = "00:0d:6f:00:11:22:33:44"
LOCK_MANUFACTURER = "Onesti Products AS"
LOCK_MODEL = "NimlyPRO"
DOORLOCK_CLUSTER_ID = 0x0101


def pytest_collection_modifyitems(session, config, items: list) -> None:
    """An empty collection is red.

    A real-HA environment that collected no tests has proven nothing. Without
    this guard `just test-ha` would pass on a misspelled path or an import
    that silently stopped being collected.
    """
    if not items:
        pytest.exit("tests_ha collected zero tests. That is red, not green.", returncode=1)


@pytest.fixture(autouse=True)
def _enable_custom(enable_custom_integrations):
    """Allow loading custom_components/ in every real-HA test."""
    yield


class FakeDoorLockCluster:
    """The parts of a zigpy DoorLock cluster the integration touches."""

    cluster_id = DOORLOCK_CLUSTER_ID

    def __init__(self) -> None:
        self._event_listeners: dict[str, list[Callable]] = {}
        self.capabilities: dict[int, int] = {0x0012: 50, 0x0017: 8, 0x0018: 4}

    def on_event(self, event: str, callback: Callable) -> Callable[[], None]:
        self._event_listeners.setdefault(event, []).append(callback)

        def unsubscribe() -> None:
            self._event_listeners[event].remove(callback)

        return unsubscribe

    async def read_attributes(self, attributes: list[int]) -> tuple[dict, dict]:
        return {a: self.capabilities[a] for a in attributes if a in self.capabilities}, {}


def make_lock_proxy(
    *,
    manufacturer: str = LOCK_MANUFACTURER,
    model: str = LOCK_MODEL,
    cluster: FakeDoorLockCluster | None = None,
) -> Any:
    """A fake ZHADeviceProxy with the Door Lock cluster on endpoint 11."""
    zigpy_device = SimpleNamespace(
        endpoints={
            0: SimpleNamespace(in_clusters={}),
            11: SimpleNamespace(in_clusters={DOORLOCK_CLUSTER_ID: cluster or FakeDoorLockCluster()}),
        }
    )
    zha_device = SimpleNamespace(manufacturer=manufacturer, model=model, device=zigpy_device)
    return SimpleNamespace(device=zha_device)


@pytest.fixture
def zha_dependency(hass) -> None:
    """Mark ZHA as set up, so the manifest dependency is satisfied."""
    hass.config.components.add("zha")


@pytest.fixture
def mock_zha(hass, zha_dependency) -> SimpleNamespace:
    """A running ZHA with one Onesti lock.

    Returns the fake gateway proxy. Tests change `device_proxies` to show
    ZHA with other devices or none.
    """
    gateway_proxy = SimpleNamespace(device_proxies={LOCK_IEEE: make_lock_proxy()})
    hass.data["zha"] = SimpleNamespace(gateway_proxy=gateway_proxy)
    return gateway_proxy


@pytest.fixture
def zha_commands(hass, mock_zha) -> list[dict]:
    """ZHA's issue_zigbee_cluster_command service, answering like a lock that got the command.

    The integration sends every ZCL command through this service, so
    registering it lets the real ZhaLockTransport and coordinator run end to
    end. Returns the list of service data the integration sent, in order.
    """
    calls: list[dict] = []

    async def _issue(call) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("zha", "issue_zigbee_cluster_command", _issue)
    return calls
