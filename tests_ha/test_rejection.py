"""A lock that answers and refuses, told apart from one that never answered.

The whole path runs in a real Home Assistant: the service or the options
flow, the real coordinator and the real ZhaLockTransport, down to the fake
zigpy Door Lock cluster from conftest. The cluster answers Set PIN Code with
status 3 (duplicate code), status 1 (general failure), success, or not at
all. A refusal must reach the user as its own text, leave the slot as it
was, and not wake the lock, since an answer means it is already awake.

Status 2 and 3 are read by the ZCL spec. Whether a Nimly lock sends them
has not been checked on hardware, so these tests pin down what the
integration does with them, not what the lock does.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN
from tests_ha.conftest import LOCK_IEEE, ZclStatus, lock_cluster

SLOT = 5
CODE = "56789"
SET_PIN_COMMAND = 0x0005
CLEAR_PIN_COMMAND = 0x0007


def _answer(status: int) -> Any:
    """Set PIN Code Response with this status, as zigpy hands it back."""
    return SimpleNamespace(status=status)


# effects on the cluster, error key (None when delivered), status placeholder,
# and whether the lock gets woken.
SCENARIOS: dict[str, tuple[list[Any], str | None, str | None, bool]] = {
    "duplicate": ([_answer(3)], "lock_rejected_duplicate", "3", False),
    "failure": ([_answer(ZclStatus.FAILURE)], "lock_rejected", "1", False),
    "timeout": ([TimeoutError(), TimeoutError()], "lock_unreachable", None, True),
    "success": ([_answer(ZclStatus.SUCCESS)], None, None, False),
}


@pytest.fixture
def wake_calls(hass: HomeAssistant, mock_zha) -> list[str]:
    """ZHA's lock entity for our lock, and lock.lock recording the wakes."""
    zha_entry = MockConfigEntry(domain="zha")
    zha_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        connections={(dr.CONNECTION_ZIGBEE, LOCK_IEEE)},
        identifiers={("zha", LOCK_IEEE)},
    )
    er.async_get(hass).async_get_or_create(
        "lock", "zha", f"{LOCK_IEEE}-11-257", device_id=device.id, config_entry=zha_entry,
        suggested_object_id="front_door",
    )
    calls: list[str] = []

    async def _lock(call: ServiceCall) -> None:
        calls.append(call.data["entity_id"])

    hass.services.async_register("lock", "lock", _lock)
    return calls


@pytest.fixture
async def entry(hass: HomeAssistant, mock_zha, wake_calls) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=2,
        unique_id=LOCK_IEEE,
        data={CONF_IEEE: LOCK_IEEE},
        options={"slots": {str(SLOT): {"name": "Kari", "has_pin": False}}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


def _script(mock_zha, effects: list[Any]) -> list[dict]:
    cluster = lock_cluster(mock_zha)
    cluster.command_effects[:] = effects
    return cluster.commands


def _slot(entry: MockConfigEntry) -> dict[str, Any]:
    return entry.options["slots"][str(SLOT)]


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_service_set_pin(hass: HomeAssistant, entry, mock_zha, wake_calls, scenario) -> None:
    effects, key, status, woken = SCENARIOS[scenario]
    commands = _script(mock_zha, effects)

    raised: HomeAssistantError | None = None
    try:
        await hass.services.async_call(
            DOMAIN, "set_pin", {"slot": SLOT, "name": "Ola", "code": CODE}, blocking=True
        )
    except HomeAssistantError as err:
        raised = err

    assert (raised.translation_key if raised else None) == key
    assert bool(wake_calls) is woken
    assert commands[0]["command"] == SET_PIN_COMMAND
    if key is None:
        assert _slot(entry) == {"name": "Ola", "has_pin": True}
        return
    # Nothing changes locally when the lock did not take the code.
    assert _slot(entry) == {"name": "Kari", "has_pin": False}
    if status is not None:
        assert raised.translation_placeholders == {"status": status}
    else:
        assert "Could not reach the lock" in str(raised)


async def test_service_messages_are_translated(hass: HomeAssistant, entry, mock_zha) -> None:
    """The user reads why, not a translation key.

    The frontend renders a service error from its translation key and
    placeholders, so the message is built the same way here.
    """
    translations = await async_get_translations(hass, "en", "exceptions", [DOMAIN])
    messages = {}
    for status in (1, 2, 3):
        _script(mock_zha, [_answer(status)])
        with pytest.raises(HomeAssistantError) as excinfo:
            await hass.services.async_call(
                DOMAIN, "set_pin", {"slot": SLOT, "name": "Ola", "code": CODE}, blocking=True
            )
        err = excinfo.value
        template = translations[f"component.{DOMAIN}.exceptions.{err.translation_key}.message"]
        messages[status] = template.format(**err.translation_placeholders)

    assert "(status 1)" in messages[1]
    assert "memory is full" in messages[2]
    assert "already uses it" in messages[3]


async def test_service_clear_pin_refused_keeps_the_pin(hass: HomeAssistant, entry, mock_zha, wake_calls) -> None:
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "slots": {str(SLOT): {"name": "Kari", "has_pin": True}}}
    )
    # Status 3 means nothing special for Clear PIN Code.
    commands = _script(mock_zha, [_answer(3)])

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(DOMAIN, "clear_pin", {"slot": SLOT}, blocking=True)

    assert excinfo.value.translation_key == "lock_rejected"
    assert commands[0]["command"] == CLEAR_PIN_COMMAND
    assert _slot(entry) == {"name": "Kari", "has_pin": True}
    assert wake_calls == []


async def _flow_set_pin(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "set_pin"})
    result = await flow.async_configure(result["flow_id"], {"slot": str(SLOT), "name": "Ola", "code": CODE})
    if result["type"] is FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done(wait_background_tasks=True)
        result = await flow.async_configure(result["flow_id"])
    return result


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_options_flow_set_pin(hass: HomeAssistant, entry, mock_zha, wake_calls, scenario) -> None:
    effects, key, status, woken = SCENARIOS[scenario]
    _script(mock_zha, effects)

    result = await _flow_set_pin(hass, entry)

    assert bool(wake_calls) is woken
    if key is None:
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert _slot(entry) == {"name": "Ola", "has_pin": True}
        return
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "set_pin"
    assert result["errors"] == {"base": key}
    assert _slot(entry) == {"name": "Kari", "has_pin": False}
    placeholders = result["description_placeholders"]
    # {min}-{max} for the form, and {status} for the rejection texts.
    assert placeholders["min"] == "4"
    assert placeholders.get("status") == status


@pytest.mark.parametrize("language", ["en", "nb", "sv", "da"])
async def test_every_error_key_has_a_translation(hass: HomeAssistant, entry, language: str) -> None:
    """The frontend looks the flow's error up by key; it must be there."""
    options = await async_get_translations(hass, language, "options", [DOMAIN])
    exceptions = await async_get_translations(hass, language, "exceptions", [DOMAIN])
    for key in ("lock_rejected", "lock_rejected_duplicate", "lock_rejected_memory_full"):
        assert options[f"component.{DOMAIN}.options.error.{key}"]
        assert exceptions[f"component.{DOMAIN}.exceptions.{key}.message"]
    assert "{status}" in options[f"component.{DOMAIN}.options.error.lock_rejected"]
