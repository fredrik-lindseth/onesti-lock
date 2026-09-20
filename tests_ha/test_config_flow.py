"""The config flow paths the smoke tests leave out.

test_smoke.py drives the happy path: ZHA lists the lock, the form offers it,
the entry is created. What is left is a lock reporting a model string we do
not know, a lock that already has an entry, and the options flow write Home
Assistant cancels under the dialog.

Run with `just test-ha minimum` and `just test-ha current`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_IGNORE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, CONF_MODEL, DOMAIN
from custom_components.onesti_lock.entity import HAS_VIA_DEVICE_ID
from custom_components.onesti_lock.zha import SEND_DELIVERED, SendOutcome
from tests_ha.conftest import LOCK_IEEE, LOCK_MODEL, make_lock_proxy

SECOND_LOCK_IEEE = "00:0d:6f:00:55:66:77:88"
THIRD_LOCK_IEEE = "00:0d:6f:00:99:aa:bb:cc"


def _device_choices(result: dict[str, Any]) -> dict[str, str]:
    """The options of the `device` selector in the user form."""
    for key, validator in result["data_schema"].schema.items():
        if key == "device":
            assert isinstance(validator, vol.In)
            return dict(validator.container)
    raise AssertionError("form has no device field")


def _our_device(hass: HomeAssistant, entry: MockConfigEntry):
    """The one device the entry owns, looked up the way HA 2026.9 allows."""
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    return devices[0]


def _add_entry(hass: HomeAssistant, ieee: str = LOCK_IEEE) -> MockConfigEntry:
    """An entry for a lock, added but not set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=ieee,
        title=f"Onesti Lock ({ieee[-11:]})",
        data={CONF_IEEE: ieee},
        options={"slots": {}},
    )
    entry.add_to_hass(hass)
    return entry


# -- The device list --


async def test_unknown_model_is_offered_with_a_warning(
    hass: HomeAssistant, mock_zha, caplog: pytest.LogCaptureFixture
) -> None:
    """A model string nobody has seen is a warning, not a refusal.

    All Onesti locks share hardware and the ZMNC010 module, and a module can
    report a sibling model name (issue #5), so the list is informational.
    """
    caplog.set_level(logging.WARNING, logger="custom_components.onesti_lock")
    mock_zha.device_proxies = {LOCK_IEEE: make_lock_proxy(model="NimlyNotYetKnown")}

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.FORM
    assert _device_choices(result) == {LOCK_IEEE: f"NimlyNotYetKnown ({LOCK_IEEE})"}
    assert "Unrecognized Onesti model 'NimlyNotYetKnown'" in caplog.text


async def test_lock_with_an_entry_is_left_out_of_the_list(hass: HomeAssistant, mock_zha) -> None:
    """A lock already set up is not offered again, the second one still is."""
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    _add_entry(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.FORM
    assert set(_device_choices(result)) == {SECOND_LOCK_IEEE}


async def test_second_setup_of_the_same_lock_aborts_already_configured(
    hass: HomeAssistant, mock_zha
) -> None:
    """The same lock cannot be set up twice.

    The device list drops locks that already have an entry, so the way to
    reach the unique-id check is a lock that gains an entry while the form is
    open: two dialogs at once, or an entry created from a second HA client.
    The other lock keeps the list non-empty, so the flow gets as far as the
    submitted device.
    """
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert LOCK_IEEE in _device_choices(result)

    _add_entry(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": LOCK_IEEE})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_an_ignored_lock_is_not_offered_under_add_integration(
    hass: HomeAssistant, mock_zha
) -> None:
    """Ignore takes the lock off the list, rather than off the end of it.

    An ignore entry holds the unique id, so picking the lock here would
    abort already_configured with nothing said about unignoring it.
    """
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    mock_zha.device_proxies[THIRD_LOCK_IEEE] = make_lock_proxy()
    _add_entry(hass)
    ignored = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IGNORE},
        data={"unique_id": SECOND_LOCK_IEEE, "title": "Onesti Lock"},
    )
    await hass.async_block_till_done()
    assert ignored["type"] is FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.FORM
    assert set(_device_choices(result)) == {THIRD_LOCK_IEEE}


# -- The lock leaving ZHA with the form open --


async def test_a_lock_that_left_zha_is_asked_for_again(hass: HomeAssistant, mock_zha) -> None:
    """ZHA drops the lock between the form and the submit.

    Home Assistant validates the submitted value against the schema of the
    form it showed, so the lock still passes vol.In. Reading it out of the
    freshly built list was a KeyError and "Unknown error occurred".
    """
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM

    del mock_zha.device_proxies[LOCK_IEEE]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": LOCK_IEEE})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"device": "device_gone"}
    assert set(_device_choices(result)) == {SECOND_LOCK_IEEE}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_reconfigure_to_a_lock_that_left_zha_is_asked_for_again(
    hass: HomeAssistant, mock_zha
) -> None:
    """The same race on the reconfigure step, which is where it is likeliest.

    The new module has just been paired, and a ZHA reload with the dialog
    open is what puts it out of the gateway again.
    """
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    mock_zha.device_proxies[THIRD_LOCK_IEEE] = make_lock_proxy()
    entry = _add_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    del mock_zha.device_proxies[SECOND_LOCK_IEEE]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": SECOND_LOCK_IEEE}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"device": "device_gone"}
    assert entry.data[CONF_IEEE] == LOCK_IEEE


# -- Reconfigure and the device registry --


@pytest.mark.skipif(
    not HAS_VIA_DEVICE_ID, reason="below HA 2026.9 the device carries no connection"
)
async def test_reconfigure_drops_the_replaced_modules_address(
    hass: HomeAssistant, mock_zha
) -> None:
    """The old module's zigbee connection goes when the entry moves.

    async_get_or_create only merges connections and never removes one, so
    without this the device would carry both addresses for good.
    """
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy(model="NimlyCodePRO")
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=3,
        unique_id=LOCK_IEEE,
        title=f"Onesti Lock ({LOCK_IEEE[-11:]})",
        data={CONF_IEEE: LOCK_IEEE, CONF_MODEL: LOCK_MODEL},
        options={"slots": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = _our_device(hass, entry)
    assert (dr.CONNECTION_ZIGBEE, LOCK_IEEE) in device.connections

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": SECOND_LOCK_IEEE}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"

    device = _our_device(hass, entry)
    assert (dr.CONNECTION_ZIGBEE, LOCK_IEEE) not in device.connections
    assert device.connections == {(dr.CONNECTION_ZIGBEE, SECOND_LOCK_IEEE)}


@pytest.mark.skipif(
    HAS_VIA_DEVICE_ID, reason="from HA 2026.9 a device belongs to one config entry"
)
async def test_reconfigure_leaves_a_shared_registry_row_alone(
    hass: HomeAssistant, mock_zha
) -> None:
    """Below HA 2026.9 a zigbee connection could merge our device with ZHA's.

    entity.py no longer sends one there, so a merged row can only be left
    over from an install that did. The connection on it is ZHA's own
    identity, and taking it off would leave ZHA unable to find its lock.
    Built here as the merge left it: two config entries and a connection.
    """
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    entry = _add_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    zha_entry = MockConfigEntry(domain="zha")
    zha_entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    registry.async_update_device(
        _our_device(hass, entry).id,
        add_config_entry_id=zha_entry.entry_id,
        merge_connections={(dr.CONNECTION_ZIGBEE, LOCK_IEEE)},
    )

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": SECOND_LOCK_IEEE}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"

    device = _our_device(hass, entry)
    assert (dr.CONNECTION_ZIGBEE, LOCK_IEEE) in device.connections


# -- The options flow, cut off mid-write --


class _GatedTransport:
    """A transport whose send() holds until the test lets it through."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.sent: list[tuple[int, dict]] = []

    def cluster(self) -> None:
        return None

    async def wake(self) -> None:
        return None

    async def send(self, command: int, params: dict) -> SendOutcome:
        self.sent.append((command, params))
        await self.gate.wait()
        return SEND_DELIVERED

    async def read_capabilities(self) -> dict[str, Any]:
        return {}


async def test_cancelled_write_shows_the_unknown_error(hass: HomeAssistant, mock_zha) -> None:
    """Home Assistant shutting down under a PIN write leaves an error, not a result.

    The write runs as its own task behind asyncio.shield, and the progress
    task only waits for it. Cancelling that waiter is what a shutdown does,
    and the step has to read the cancellation rather than ask a cancelled
    task for its result.
    """
    transport = _GatedTransport()
    entry = _add_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.transport = transport

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "set_pin"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"slot": "4", "name": "Kari", "code": "1234"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS

    flow = hass.config_entries.options._progress[result["flow_id"]]
    waiter = flow._set_pin_task
    waiter.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await waiter
    assert waiter.cancelled()

    # HA runs the progress step again once the task it was given is done,
    # cancellation included, and the step takes the flow back to the form.
    # Only the loop is let run here: async_block_till_done would wait for
    # the write itself, which is still held at the gate on purpose.
    await asyncio.sleep(0)
    assert flow.cur_step["type"] is FlowResultType.SHOW_PROGRESS_DONE
    form = await hass.config_entries.options.async_configure(result["flow_id"])
    assert form["step_id"] == "set_pin"
    assert form["errors"] == {"base": "unknown"}

    # The command itself was never cancelled: it reached the lock and saved.
    transport.gate.set()
    await hass.async_block_till_done()
    assert transport.sent
    assert entry.options["slots"]["4"]["has_pin"] is True
