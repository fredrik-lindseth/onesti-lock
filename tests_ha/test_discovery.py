"""Discovery of further locks, against real Home Assistant.

Home Assistant never loads a custom integration that has no config entry,
so the first lock is added by hand. From then on the integration watches
ZHA and offers every Onesti lock with a Door Lock cluster that no entry
owns, as a Discovered card the user confirms or ignores.

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN
from tests_ha.conftest import LOCK_IEEE, make_lock_proxy

SECOND_LOCK_IEEE = "00:0d:6f:00:55:66:77:88"


async def _setup_first_lock(hass: HomeAssistant) -> MockConfigEntry:
    """The entry that gets the integration loaded in the first place."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=2,
        unique_id=LOCK_IEEE,
        title="Onesti Lock (11:22:33:44)",
        data={CONF_IEEE: LOCK_IEEE},
        options={"slots": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _zha_entry(hass: HomeAssistant) -> MockConfigEntry:
    zha_entry = MockConfigEntry(domain="zha", state=ConfigEntryState.LOADED)
    zha_entry.add_to_hass(hass)
    return zha_entry


async def _pair_in_zha(
    hass: HomeAssistant,
    mock_zha,
    zha_entry: MockConfigEntry,
    ieee: str = SECOND_LOCK_IEEE,
    **proxy_kwargs,
) -> None:
    """A lock arriving in ZHA: a gateway device and a registry entry for it."""
    mock_zha.device_proxies[ieee] = make_lock_proxy(**proxy_kwargs)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        identifiers={("zha", ieee)},
        connections={(dr.CONNECTION_ZIGBEE, ieee)},
    )
    await hass.async_block_till_done()


def _discovery_flows(hass: HomeAssistant) -> list[dict]:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == "integration_discovery"
    ]


async def test_a_new_zha_device_is_offered_as_a_discovery(
    hass: HomeAssistant, mock_zha
) -> None:
    """A second lock paired in ZHA shows up as a Discovered card."""
    zha_entry = _zha_entry(hass)
    await _setup_first_lock(hass)

    await _pair_in_zha(hass, mock_zha, zha_entry, model="NimlyCodePRO")

    flows = _discovery_flows(hass)
    assert len(flows) == 1
    assert flows[0]["step_id"] == "discovery_confirm"
    assert flows[0]["context"]["unique_id"] == SECOND_LOCK_IEEE
    assert flows[0]["context"]["title_placeholders"] == {
        "model": "NimlyCodePRO",
        "ieee": SECOND_LOCK_IEEE,
    }


async def test_confirming_a_discovery_creates_the_entry(
    hass: HomeAssistant, mock_zha
) -> None:
    """Confirming the card sets the lock up, with the IEEE as its unique id."""
    zha_entry = _zha_entry(hass)
    await _setup_first_lock(hass)
    await _pair_in_zha(hass, mock_zha, zha_entry)

    flow_id = _discovery_flows(hass)[0]["flow_id"]
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_IEEE: SECOND_LOCK_IEEE}
    entry = result["result"]
    assert entry.unique_id == SECOND_LOCK_IEEE
    assert entry.state is ConfigEntryState.LOADED
    assert not _discovery_flows(hass)


async def test_a_lock_that_is_already_set_up_is_not_offered(
    hass: HomeAssistant, mock_zha
) -> None:
    """The lock we are already running is not discovered again.

    Its own device registry entry from ZHA arrives like any other, so the
    flow has to be left unstarted rather than aborted after the fact.
    """
    zha_entry = _zha_entry(hass)
    await _setup_first_lock(hass)

    await _pair_in_zha(hass, mock_zha, zha_entry, ieee=LOCK_IEEE)

    assert not _discovery_flows(hass)


async def test_an_ignored_lock_does_not_come_back(hass: HomeAssistant, mock_zha) -> None:
    """Ignore means ignore: the unique id keeps the next look quiet."""
    zha_entry = _zha_entry(hass)
    await _setup_first_lock(hass)
    await _pair_in_zha(hass, mock_zha, zha_entry)

    flow_id = _discovery_flows(hass)[0]["flow_id"]
    hass.config_entries.flow.async_abort(flow_id)
    ignored = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IGNORE},
        data={"unique_id": SECOND_LOCK_IEEE, "title": "Onesti Lock"},
    )
    await hass.async_block_till_done()
    assert ignored["type"] is FlowResultType.CREATE_ENTRY

    # ZHA restarts and lists the lock again.
    zha_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    zha_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()

    assert not _discovery_flows(hass)


async def test_zha_reaching_loaded_offers_the_locks_it_brought(
    hass: HomeAssistant, mock_zha
) -> None:
    """ZHA starting after us is a look of its own.

    The device registry entries were written before this integration was
    loaded, so no registry event is coming for them.
    """
    zha_entry = MockConfigEntry(domain="zha", state=ConfigEntryState.NOT_LOADED)
    zha_entry.add_to_hass(hass)
    await _setup_first_lock(hass)
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()

    zha_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()

    flows = _discovery_flows(hass)
    assert len(flows) == 1
    assert flows[0]["context"]["unique_id"] == SECOND_LOCK_IEEE


async def test_a_device_that_is_not_an_onesti_lock_is_ignored(
    hass: HomeAssistant, mock_zha
) -> None:
    """Any other Zigbee device paired in ZHA leaves the integration alone."""
    zha_entry = _zha_entry(hass)
    await _setup_first_lock(hass)

    await _pair_in_zha(
        hass, mock_zha, zha_entry, ieee="00:12:4b:00:99:88:77:66", manufacturer="IKEA of Sweden"
    )

    assert not _discovery_flows(hass)


async def test_a_removed_or_unknown_device_is_not_a_look(
    hass: HomeAssistant, mock_zha
) -> None:
    """Removals, and events naming a device that is already gone, are dropped.

    The second lock is put in ZHA's gateway first, so any look would find
    it. Both events are the shapes that must not start one.
    """
    zha_entry = _zha_entry(hass)
    await _setup_first_lock(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        identifiers={("zha", "00:00:00:00:00:00:00:77")},
        connections={(dr.CONNECTION_ZIGBEE, "00:00:00:00:00:00:00:77")},
    )
    await hass.async_block_till_done()
    assert not _discovery_flows(hass)
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()

    dr.async_get(hass).async_remove_device(device.id)
    hass.bus.async_fire(
        dr.EVENT_DEVICE_REGISTRY_UPDATED, {"action": "create", "device_id": device.id}
    )
    await hass.async_block_till_done()

    assert not _discovery_flows(hass)


async def test_a_device_from_another_integration_is_not_a_look(
    hass: HomeAssistant, mock_zha
) -> None:
    """A registry entry from something that is not ZHA does not start a look.

    The second lock is in ZHA's gateway all along, so a look would find it;
    that no flow appears is what says the event was filtered out.
    """
    _zha_entry(hass)
    await _setup_first_lock(hass)
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()

    other = MockConfigEntry(domain="demo")
    other.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("demo", "thing")},
        connections={(dr.CONNECTION_ZIGBEE, "00:00:00:00:00:00:00:99")},
    )
    await hass.async_block_till_done()

    assert not _discovery_flows(hass)
