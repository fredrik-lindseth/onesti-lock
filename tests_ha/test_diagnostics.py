"""Download diagnostics on a real Home Assistant, through the diagnostics API.

What a user attaches to a public issue must carry what a bug needs and not
the household: no IEEE address and no slot names. The PIN side of the same
output is in test_pin_canary.py.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN
from tests_ha.conftest import DOORLOCK_CLUSTER_ID, LOCK_IEEE, LOCK_MODEL, lock_cluster

TITLE = "Onesti Lock (11:22:33:44)"
ATTR_OPERATION_EVENT = 0x0100
# Keypad unlock (source 0x02, action 0x02) by slot 3.
KEYPAD_UNLOCK_SLOT_3 = 0x02020003
SLOTS = {
    "3": {"name": "Kari", "has_pin": True},
    "4": {"name": "", "has_pin": True},
    "7": {"name": "Ola", "has_pin": False},
}


async def _setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=2,
        unique_id=LOCK_IEEE,
        title=TITLE,
        data={CONF_IEEE: LOCK_IEEE},
        options=options if options is not None else {"slots": dict(SLOTS)},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _report(hass: HomeAssistant, mock_zha, value: int) -> None:
    cluster = lock_cluster(mock_zha)
    event = SimpleNamespace(attribute_id=ATTR_OPERATION_EVENT, raw_value=value)
    for listener in list(cluster._event_listeners["attribute_report"]):
        listener(event)
    await hass.async_block_till_done(wait_background_tasks=True)


def _assert_nothing_personal(diagnostics: dict) -> None:
    dump = json.dumps(diagnostics)
    for personal in (LOCK_IEEE, LOCK_IEEE.upper(), "11:22:33:44", "Kari", "Ola"):
        assert personal not in dump, f"{personal} is in the diagnostics"


async def test_diagnostics_of_a_running_lock(hass: HomeAssistant, hass_client, mock_zha) -> None:
    entry = await _setup(hass)
    await _report(hass, mock_zha, KEYPAD_UNLOCK_SLOT_3)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    _assert_nothing_personal(diagnostics)
    assert diagnostics["integration_version"]
    assert diagnostics["home_assistant_version"]
    assert diagnostics["entry"]["title"] == "**REDACTED**"
    assert diagnostics["entry"]["unique_id"] == "**REDACTED**"
    assert diagnostics["entry"]["data"] == {CONF_IEEE: "**REDACTED**"}
    assert (diagnostics["entry"]["version"], diagnostics["entry"]["minor_version"]) == (2, 2)
    # Names become named/unnamed, the PIN flag stays as stored.
    assert diagnostics["entry"]["options"]["slots"] == {
        "3": {"name": "named", "has_pin": True},
        "4": {"name": "unnamed", "has_pin": True},
        "7": {"name": "named", "has_pin": False},
    }
    capabilities = {"num_pin_users": 50, "max_pin_length": 8, "min_pin_length": 4}
    assert diagnostics["entry"]["options"]["capabilities"] == capabilities
    assert diagnostics["lock_capabilities"] == capabilities
    assert diagnostics["capabilities_final"] is True
    assert diagnostics["first_user_slot"] == diagnostics["setup_first_user_slot"] == 3
    assert diagnostics["zha"] == {
        "loaded": True,
        "entry_states": [],
        "device_found": True,
        "manufacturer": "Onesti Products AS",
        "model": LOCK_MODEL,
        "door_lock_cluster_found": True,
        "cluster_type": "FakeDoorLockCluster",
        "cluster_endpoint": 11,
        "lock_entity_found": False,
    }
    assert diagnostics["listener"] == {
        "registered": True,
        "cluster_type": "FakeDoorLockCluster",
        "on_current_cluster": True,
        "repair_issue": False,
    }
    assert diagnostics["wake_echo_pending"] is False
    activity = diagnostics["last_activity"]
    assert activity["timestamp"]
    assert {k: v for k, v in activity.items() if k != "timestamp"} == {
        "user_slot": 3,
        "user_name": "named",
        "action": "unlock",
        "source": "keypad",
    }


async def test_diagnostics_of_an_unnamed_slot_activity(hass: HomeAssistant, hass_client, mock_zha) -> None:
    # The sensor shows "Slot 4" for an unnamed slot; the diagnostics say so
    # without quoting the fallback as if it were a name.
    entry = await _setup(hass)
    await _report(hass, mock_zha, (KEYPAD_UNLOCK_SLOT_3 & ~0xFFFF) | 4)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["last_activity"]["user_name"] == "unnamed"


async def test_diagnostics_before_the_lock_answered(hass: HomeAssistant, hass_client, mock_zha) -> None:
    lock_cluster(mock_zha).capabilities = {}
    lock_cluster(mock_zha).read_attributes = _unanswered
    entry = await _setup(hass, options={"slots": {}})

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["capabilities_final"] is False
    assert diagnostics["lock_capabilities"] == {}
    assert "capabilities" not in diagnostics["entry"]["options"]
    assert diagnostics["last_activity"] is None


async def _unanswered(attributes: list[int]) -> tuple[dict, dict]:
    raise TimeoutError


async def test_diagnostics_with_no_door_lock_cluster(hass: HomeAssistant, hass_client, mock_zha) -> None:
    # ZHA lists the lock but its object layout hides the cluster: the case
    # the repair issue is for.
    mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11].in_clusters.clear()
    entry = await _setup(hass)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    _assert_nothing_personal(diagnostics)
    assert diagnostics["zha"]["device_found"] is True
    assert diagnostics["zha"]["door_lock_cluster_found"] is False
    assert diagnostics["zha"]["cluster_type"] is None
    assert diagnostics["listener"]["registered"] is False
    assert diagnostics["listener"]["repair_issue"] is True


async def test_diagnostics_after_the_lock_left_zha(hass: HomeAssistant, hass_client, mock_zha) -> None:
    entry = await _setup(hass)
    mock_zha.device_proxies.clear()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    _assert_nothing_personal(diagnostics)
    assert diagnostics["zha"]["loaded"] is True
    assert diagnostics["zha"]["device_found"] is False
    assert diagnostics["listener"]["registered"] is True
    assert diagnostics["listener"]["on_current_cluster"] is False


async def test_diagnostics_while_zha_is_not_loaded(hass: HomeAssistant, hass_client, zha_dependency) -> None:
    entry = await _setup(hass)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    _assert_nothing_personal(diagnostics)
    assert diagnostics["zha"]["loaded"] is False
    assert diagnostics["zha"]["device_found"] is False
    assert diagnostics["listener"] == {
        "registered": False,
        "cluster_type": None,
        "on_current_cluster": False,
        "repair_issue": False,
    }


async def test_diagnostics_see_a_cluster_zha_replaced(hass: HomeAssistant, hass_client, mock_zha) -> None:
    entry = await _setup(hass)
    endpoint = mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11]
    endpoint.in_clusters[DOORLOCK_CLUSTER_ID] = type(lock_cluster(mock_zha))()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["listener"]["registered"] is True
    assert diagnostics["listener"]["on_current_cluster"] is False
