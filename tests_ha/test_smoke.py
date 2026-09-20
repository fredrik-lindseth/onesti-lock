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
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import (
    CONF_IEEE,
    CONF_MODEL,
    DOMAIN,
    NUM_USER_SLOTS,
    SLOT_FIRST_USER,
)
from custom_components.onesti_lock.entity import HAS_VIA_DEVICE_ID
from tests_ha.conftest import (
    DEVICE_SLUG,
    LISTENER_PATHS,
    LOCK_IEEE,
    LOCK_MODEL,
    make_lock_proxy,
)

SERVICES = {"set_pin", "clear_pin", "set_name", "clear_slot"}


SECOND_LOCK_IEEE = "00:0d:6f:00:55:66:77:88"


async def _setup_entry(hass: HomeAssistant, ieee: str = LOCK_IEEE) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=ieee,
        title=f"Onesti Lock ({ieee[-11:]})",
        minor_version=3,
        data={CONF_IEEE: ieee, CONF_MODEL: LOCK_MODEL},
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
    assert result["data"] == {CONF_IEEE: LOCK_IEEE, CONF_MODEL: LOCK_MODEL}
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

    expected = {f"{entry.entry_id}-slot-{SLOT_FIRST_USER + i}" for i in range(NUM_USER_SLOTS)}
    expected.add(f"{entry.entry_id}-activity")
    # Registered but disabled by default, see tests_ha/test_sensor.py.
    expected.update(
        {
            f"{entry.entry_id}-pin-users",
            f"{entry.entry_id}-pin-length-min",
            f"{entry.entry_id}-pin-length-max",
        }
    )
    assert unique_ids == expected


def _zha_device(hass: HomeAssistant, ieee: str = LOCK_IEEE) -> tuple[MockConfigEntry, object]:
    """ZHA's own config entry and device for a lock, in the real registry."""
    zha_entry = MockConfigEntry(domain="zha")
    zha_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        identifiers={("zha", ieee)},
        connections={(dr.CONNECTION_ZIGBEE, ieee)},
        manufacturer="Onesti Products AS",
        model=LOCK_MODEL,
        name="front_door",
    )
    return zha_entry, device


def _our_device(hass: HomeAssistant, entry: MockConfigEntry):
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    return devices[0]


async def test_the_lock_device_says_which_lock_it_is(hass: HomeAssistant, mock_zha) -> None:
    """Model, serial number and the zigbee connection, on both HA targets.

    What the registry then does with the connection differs: through HA
    2026.8 it is unique across config entries, so this device and ZHA's
    become one entry carrying both integrations. From 2026.9 it is unique
    only within one entry, the two stay apart, and the link is the
    via_device_id this integration sets.
    """
    zha_entry, zha_device = _zha_device(hass)

    entry = await _setup_entry(hass)

    device = _our_device(hass, entry)
    assert (dr.CONNECTION_ZIGBEE, LOCK_IEEE) in device.connections
    assert device.manufacturer == "Onesti Products AS"
    assert device.model == LOCK_MODEL
    assert device.serial_number == LOCK_IEEE
    assert device.name == f"{LOCK_MODEL} (3344)"
    assert (DOMAIN, entry.entry_id) in device.identifiers

    if HAS_VIA_DEVICE_ID:
        assert device.id != zha_device.id
        assert device.via_device_id == zha_device.id
    else:
        assert device.id == zha_device.id
        assert device.config_entries == {entry.entry_id, zha_entry.entry_id}


async def test_the_lock_device_stands_alone_without_zha_in_the_registry(
    hass: HomeAssistant, mock_zha
) -> None:
    """A gateway that lists the lock but no device registry entry for it.

    ZHA writes its devices as it interviews them, so ours can be built
    first. The device is still right; only the link to ZHA is missing.
    """
    entry = await _setup_entry(hass)

    device = _our_device(hass, entry)
    assert device.via_device_id is None
    assert device.serial_number == LOCK_IEEE


async def test_entity_ids_follow_the_device_name(hass: HomeAssistant, mock_zha) -> None:
    """Where DEVICE_SLUG in conftest comes from."""
    entry = await _setup_entry(hass)

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}-activity")
    assert entity_id == f"sensor.{DEVICE_SLUG}_last_activity"


async def test_reconfigure_points_the_entry_at_another_module(
    hass: HomeAssistant, mock_zha
) -> None:
    """A replaced Connect Module: new address, same entry, same options."""
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy(model="NimlyCodePRO")
    entry = await _setup_entry(hass)
    hass.config_entries.async_update_entry(
        entry, options={"slots": {"5": {"name": "Kari", "has_pin": True}}}
    )
    await hass.async_block_till_done()
    device_id = _our_device(hass, entry).id

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": SECOND_LOCK_IEEE}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_IEEE: SECOND_LOCK_IEEE, CONF_MODEL: "NimlyCodePRO"}
    assert entry.unique_id == SECOND_LOCK_IEEE
    assert entry.options["slots"] == {"5": {"name": "Kari", "has_pin": True}}
    assert entry.state is ConfigEntryState.LOADED
    # The same device, renamed: the entities did not move anywhere.
    assert _our_device(hass, entry).id == device_id
    assert _our_device(hass, entry).name == "NimlyCodePRO (7788)"


async def test_reconfigure_to_a_lock_another_entry_owns_is_refused(
    hass: HomeAssistant, mock_zha
) -> None:
    """The second entry may appear between the form and the submit."""
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    entry = await _setup_entry(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert SECOND_LOCK_IEEE in result["data_schema"]({"device": SECOND_LOCK_IEEE})["device"]
    other = await _setup_entry(hass, SECOND_LOCK_IEEE)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": SECOND_LOCK_IEEE}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_IEEE] == LOCK_IEEE
    assert other.data[CONF_IEEE] == SECOND_LOCK_IEEE


async def test_reconfigure_leaves_out_locks_other_entries_own(
    hass: HomeAssistant, mock_zha
) -> None:
    """Only this entry's own lock and the free ones are offered."""
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    entry = await _setup_entry(hass)
    await _setup_entry(hass, SECOND_LOCK_IEEE)

    result = await entry.start_reconfigure_flow(hass)

    assert result["step_id"] == "reconfigure"
    with pytest.raises(vol.Invalid):
        result["data_schema"]({"device": SECOND_LOCK_IEEE})
    assert result["data_schema"]({"device": LOCK_IEEE})["device"] == LOCK_IEEE


async def test_reconfigure_without_zha_aborts(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)
    hass.data["zha"] = SimpleNamespace(gateway_proxy=None)

    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "zha_not_found"


async def test_reconfigure_without_a_free_lock_aborts(hass: HomeAssistant, mock_zha) -> None:
    """ZHA is running but has no Onesti lock left to point at."""
    entry = await _setup_entry(hass)
    mock_zha.device_proxies = {}

    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


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
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}-activity")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["friendly_name"] == f"{LOCK_MODEL} (3344) Siste aktivitet"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow_shows_menu(hass: HomeAssistant, mock_zha) -> None:
    entry = await _setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert set(result["menu_options"]) == {"set_pin", "clear_pin", "name_slot", "view_slots", "settings"}
