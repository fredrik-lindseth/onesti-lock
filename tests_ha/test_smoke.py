"""Smoke tests against a real Home Assistant.

tests/ stubs homeassistant.*, so config flow rendering, entry setup, entity
registration and translation loading never run against real Home Assistant
there. These tests load the integration into a real instance, with ZHA
mocked at the gateway proxy level (see conftest.py).

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN, NUM_USER_SLOTS, SLOT_FIRST_USER
from tests_ha.conftest import LISTENER_PATHS, LOCK_IEEE, make_lock_proxy

SERVICES = {"set_pin", "clear_pin", "set_name", "clear_slot"}


SECOND_LOCK_IEEE = "00:0d:6f:00:55:66:77:88"


async def _setup_entry(hass: HomeAssistant, ieee: str = LOCK_IEEE) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=ieee,
        title=f"Onesti Lock ({ieee[-11:]})",
        data={CONF_IEEE: ieee},
        options={"slots": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow_finds_lock_and_creates_entry(hass: HomeAssistant, mock_zha) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": LOCK_IEEE})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_IEEE: LOCK_IEEE}
    entry = result["result"]
    assert entry.unique_id == LOCK_IEEE
    assert entry.state is ConfigEntryState.LOADED


async def test_config_flow_ignores_non_onesti_device(hass: HomeAssistant, mock_zha) -> None:
    mock_zha.device_proxies = {"00:11:22:33:44:55:66:77": make_lock_proxy(manufacturer="IKEA of Sweden")}

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_config_flow_without_lock_aborts(hass: HomeAssistant, mock_zha) -> None:
    mock_zha.device_proxies = {}

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_config_flow_without_zha_gateway_aborts(hass: HomeAssistant, zha_dependency) -> None:
    hass.data["zha"] = SimpleNamespace(gateway_proxy=None)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "zha_not_found"


@pytest.mark.parametrize("cluster_class", LISTENER_PATHS, indirect=True)
async def test_setup_and_unload_entry(hass: HomeAssistant, mock_zha) -> None:
    """Both zigpy listener hooks: one listener on setup, none after unload."""
    cluster = mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11].in_clusters[0x0101]

    entry = await _setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert cluster.listener_count == 1
    coordinator = entry.runtime_data
    assert coordinator.lock_capabilities.get("num_pin_users") == 50

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert cluster.listener_count == 0


async def test_unload_then_setup_again(hass: HomeAssistant, mock_zha) -> None:
    cluster = mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11].in_clusters[0x0101]
    entry = await _setup_entry(hass)
    first_coordinator = entry.runtime_data

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hasattr(entry, "runtime_data")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not first_coordinator
    assert cluster.listener_count == 1
    assert set(hass.services.async_services().get(DOMAIN, {})) == SERVICES


async def test_services_outlive_every_entry(hass: HomeAssistant, mock_zha) -> None:
    """The services belong to the integration, not to one lock.

    They used to go with the last loaded entry, which raced: a lock still
    setting up does not count as loaded, so unloading another lock at that
    moment removed the services under it.
    """
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    first = await _setup_entry(hass)
    second = await _setup_entry(hass, SECOND_LOCK_IEEE)

    assert await hass.config_entries.async_unload(first.entry_id)
    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()

    assert set(hass.services.async_services().get(DOMAIN, {})) == SERVICES
    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(DOMAIN, "set_name", {"slot": 5, "name": "Kari"}, blocking=True)
    assert excinfo.value.translation_key == "lock_not_found"


async def test_services_find_only_loaded_locks(hass: HomeAssistant, mock_zha) -> None:
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    first = await _setup_entry(hass)
    second = await _setup_entry(hass, SECOND_LOCK_IEEE)

    await hass.services.async_call(
        DOMAIN, "set_name", {"slot": 5, "name": "Kari", "ieee": SECOND_LOCK_IEEE.upper()}, blocking=True
    )
    assert second.options["slots"]["5"]["name"] == "Kari"
    assert "5" not in first.options["slots"]

    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN, "set_name", {"slot": 5, "name": "Ola", "ieee": SECOND_LOCK_IEEE}, blocking=True
        )
    assert excinfo.value.translation_key == "lock_not_found_ieee"


async def test_entities_registered_with_expected_unique_ids(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)

    registry = er.async_get(hass)
    unique_ids = {e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}

    expected = {f"{LOCK_IEEE}-slot-{SLOT_FIRST_USER + i}" for i in range(NUM_USER_SLOTS)}
    expected.add(f"{LOCK_IEEE}-activity")
    # Registered but disabled by default, see tests_ha/test_sensor.py.
    expected.update({f"{LOCK_IEEE}-pin-users", f"{LOCK_IEEE}-pin-length-min", f"{LOCK_IEEE}-pin-length-max"})
    assert unique_ids == expected


async def test_services_registered(hass: HomeAssistant, mock_zha) -> None:
    await _setup_entry(hass)

    assert set(hass.services.async_services().get(DOMAIN, {})) == SERVICES


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "Last activity"), ("nb", "Siste aktivitet")],
)
async def test_entity_translations_load(hass: HomeAssistant, language: str, expected: str) -> None:
    translations = await async_get_translations(hass, language, "entity", {DOMAIN})

    assert translations[f"component.{DOMAIN}.entity.sensor.last_activity.name"] == expected


async def test_entity_name_is_translated_on_norwegian_instance(hass: HomeAssistant, mock_zha) -> None:
    hass.config.language = "nb"
    entry = await _setup_entry(hass)

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{LOCK_IEEE}-activity")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["friendly_name"] == "Onesti Lock Siste aktivitet"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow_shows_menu(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert set(result["menu_options"]) == {"set_pin", "clear_pin", "name_slot", "view_slots", "settings"}
