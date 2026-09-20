"""The event listener against the real zigpy each pinned Home Assistant ships.

Every other test in this tree hands the listener a fake cluster. That
proves the decoding, but not the one thing that actually broke: which
hook a real zigpy Door Lock cluster offers, and whether a real
Report_Attributes frame reaches our handler through it.

zigpy is pinned per dependency group to exactly the version that group's
Home Assistant gets through zha (see pyproject.toml):

| target  | Home Assistant | zha    | zigpy  | Cluster.on_event |
| ------- | -------------- | ------ | ------ | ---------------- |
| minimum | 2025.6.0       | 0.0.59 | 0.80.1 | no               |
| current | 2026.9.3       | 2.2.2  | 2.2.0  | yes              |

So `just test-ha minimum` runs this file through the add_listener
fallback and `just test-ha current` through on_event, and both must end
with the activity sensor showing who unlocked the door.

The cluster here is a real `zigpy.zcl.clusters.closures.DoorLock`. Only
the two outbound calls are replaced, since there is no radio: everything
that receives a report (handle_message, _update_attribute, the listener
machinery) is zigpy's own code.

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

from importlib.metadata import version
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import zigpy.types as t
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zigpy.zcl import Cluster, foundation
from zigpy.zcl.clusters.closures import DoorLock

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN
from tests_ha.conftest import DEVICE_SLUG, LOCK_IEEE, lock_cluster

ACTIVITY_ENTITY_ID = f"sensor.{DEVICE_SLUG}_last_activity"

# attrid 0x0100: source byte, action byte, user slot (uint16).
KARI_UNLOCKS_WITH_CODE = 0x02020005  # keypad, unlock, slot 5
AUTO_LOCK = 0x0A010000  # auto, lock, no user

_CAPABILITIES = {0x0012: 50, 0x0017: 8, 0x0018: 4}

# EventBase came into Cluster in zigpy 0.91.0, and with it on_event.
_ON_EVENT_FROM = (0, 91)
_ZIGPY_VERSION = version("zigpy")
_ZIGPY = tuple(int(part) for part in _ZIGPY_VERSION.split(".")[:2])


def make_real_cluster() -> DoorLock:
    """A real zigpy Door Lock cluster with its radio calls replaced.

    The stubs are set on the instance, not in a subclass: subclassing a
    zigpy cluster runs __init_subclass__, which recompiles the command and
    attribute definitions on class-level dicts shared with DoorLock.
    """
    endpoint = MagicMock()
    endpoint.endpoint_id = 11
    # zigpy resolves the device through the application for some paths.
    endpoint.device.application.get_device.return_value = endpoint.device
    cluster = DoorLock(endpoint)
    # Not `commands`: zigpy's Cluster already has a property by that name.
    cluster.sent_commands = []

    async def command(command_id: int, *args: Any, **params: Any) -> Any:
        cluster.sent_commands.append({"command": command_id, "params": dict(params)})
        return SimpleNamespace(status=foundation.Status.SUCCESS)

    async def read_attributes(attributes: list[int], **kwargs: Any) -> tuple[dict, dict]:
        return {a: _CAPABILITIES[a] for a in attributes if a in _CAPABILITIES}, {}

    cluster.command = command
    cluster.read_attributes = read_attributes
    return cluster


def report_frame(attrid: int, value: int) -> tuple[foundation.ZCLHeader, Any]:
    """A Report_Attributes frame, built from the bytes the lock sends.

    Payload layout per ZCL: attribute id uint16 LE, data type, then the
    value. 0x1B is bitmap32, which is what the captures show for 0x0100
    (docs/zigbee-protocol/zigbee-captures.md). Deserializing it rather
    than handing zigpy ready-made objects keeps the byte order under test.
    """
    payload = (
        t.uint16_t(attrid).serialize()
        + t.uint8_t(0x1B).serialize()
        + t.bitmap32(value).serialize()
    )
    schema = foundation.GENERAL_COMMANDS[foundation.GeneralCommand.Report_Attributes].schema
    args, rest = schema.deserialize(payload)
    assert rest == b"", f"{len(rest)} bytes left over: {rest!r}"
    header = foundation.ZCLHeader.general(
        tsn=1,
        command_id=foundation.GeneralCommand.Report_Attributes,
        direction=foundation.Direction.Server_to_Client,
    )
    return header, args


async def _report(hass: HomeAssistant, cluster: DoorLock, attrid: int, value: int) -> None:
    cluster.handle_message(*report_frame(attrid, value))
    await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, slots: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=2,
        unique_id=LOCK_IEEE,
        title="Onesti Lock (11:22:33:44)",
        data={CONF_IEEE: LOCK_IEEE},
        options={"slots": slots or {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _zha_issue(hass: HomeAssistant, entry: MockConfigEntry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"zha_internals_{entry.entry_id}")


# Every test in this file runs against the real cluster.
pytestmark = pytest.mark.parametrize("cluster_class", [make_real_cluster], indirect=True)


async def test_on_event_exists_exactly_from_zigpy_0_91(hass: HomeAssistant, mock_zha) -> None:
    """The premise of the fallback, checked against the installed library.

    If this fails, the version table in the module docstring is stale and
    the rest of the file is testing something else than it claims to.
    """
    assert hasattr(Cluster, "on_event") is (_ZIGPY >= _ON_EVENT_FROM), _ZIGPY_VERSION
    assert hasattr(lock_cluster(mock_zha), "on_event") is (_ZIGPY >= _ON_EVENT_FROM)
    # The fallback needs both halves wherever on_event is missing.
    assert callable(lock_cluster(mock_zha).add_listener)
    assert callable(lock_cluster(mock_zha).remove_listener)


async def test_activity_arrives_from_a_real_report(hass: HomeAssistant, mock_zha) -> None:
    """End to end: real cluster, real frame, named user on the sensor."""
    entry = await _setup(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    assert entry.state is ConfigEntryState.LOADED
    # Whichever hook this zigpy has, it was enough: no repair issue.
    assert _zha_issue(hass, entry) is None
    assert not ir.async_get(hass).issues

    await _report(hass, lock_cluster(mock_zha), 0x0100, KARI_UNLOCKS_WITH_CODE)

    state = hass.states.get(ACTIVITY_ENTITY_ID)
    assert state.state == "Kari unlocked with code"
    assert state.attributes["user_slot"] == 5
    assert state.attributes["action"] == "unlock"
    assert state.attributes["source"] == "keypad"


async def test_the_ha_event_fires_from_a_real_report(hass: HomeAssistant, mock_zha) -> None:
    await _setup(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    fired = []
    hass.bus.async_listen("onesti_lock_activity", fired.append)

    await _report(hass, lock_cluster(mock_zha), 0x0100, KARI_UNLOCKS_WITH_CODE)
    await _report(hass, lock_cluster(mock_zha), 0x0100, AUTO_LOCK)

    assert [e.data["source"] for e in fired] == ["keypad", "auto"]
    # Auto-lock fires the event but must not take the sensor from Kari.
    assert hass.states.get(ACTIVITY_ENTITY_ID).state == "Kari unlocked with code"


async def test_other_attributes_leave_the_sensor_alone(hass: HomeAssistant, mock_zha) -> None:
    """A real frame for another attribute goes through the same machinery.

    On the add_listener path zigpy calls attribute_updated for every
    attribute it sees, our own capability reads included, so the attrid
    filter is what keeps them out.
    """
    await _setup(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    await _report(hass, lock_cluster(mock_zha), 0x0100, KARI_UNLOCKS_WITH_CODE)
    before = hass.states.get(ACTIVITY_ENTITY_ID)

    await _report(hass, lock_cluster(mock_zha), 0x0012, 50)

    after = hass.states.get(ACTIVITY_ENTITY_ID)
    assert after.state == before.state
    assert dict(after.attributes) == dict(before.attributes)


async def test_unload_stops_the_real_listener(hass: HomeAssistant, mock_zha) -> None:
    """Unsubscribing has to work on both hooks, not just on_event.

    The HA event is the public sign that the listener ran: it fires for
    every decoded report, suppressed ones included. After unload no
    report may produce one.
    """
    entry = await _setup(hass, slots={"5": {"name": "Kari", "has_pin": True}})
    cluster = lock_cluster(mock_zha)
    fired = []
    hass.bus.async_listen("onesti_lock_activity", fired.append)

    await _report(hass, cluster, 0x0100, KARI_UNLOCKS_WITH_CODE)
    assert len(fired) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    await _report(hass, cluster, 0x0100, KARI_UNLOCKS_WITH_CODE)
    assert len(fired) == 1
