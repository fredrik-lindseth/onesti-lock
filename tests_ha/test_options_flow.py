"""The options flow, driven through a real Home Assistant.

Each test runs NimlyProOptionsFlow through hass.config_entries.options, so
HA's own flow manager handles menus, forms, schema validation, progress
tasks and entry updates. The coordinator is the real one created by
async_setup_entry. Only its transport is swapped for a fake, which stands
in for the Zigbee radio and records every command the flow sends.

The PIN steps run their command as a progress task. When it finishes, HA
calls the progress step again on its own, and the step answers with
progress_done pointing at the result or back at the form. The PIN tests
follow that whole path through HA's flow manager, success and failure alike.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, CONF_RESERVED_SLOTS, DOMAIN
from tests_ha.conftest import LOCK_IEEE

SET_PIN_COMMAND = 0x0005
CLEAR_PIN_COMMAND = 0x0007


class FakeTransport:
    """Stands in for ZhaLockTransport.

    `result` is what send() returns, or an exception instance to raise.
    send() yields to the loop first, the way a radio round trip does, so the
    progress task is still running when the flow shows its spinner. With
    `instant` it finishes inside the eagerly started task instead. With a
    `gate`, send() holds until the test sets it, the way a sleeping lock
    keeps a command waiting.
    """

    def __init__(self) -> None:
        self.result: bool | BaseException = True
        self.instant = False
        self.gate: asyncio.Event | None = None
        self.sent: list[tuple[int, dict]] = []

    def cluster(self) -> None:
        return None

    async def wake(self) -> None:
        return None

    async def send(self, command: int, params: dict) -> bool:
        self.sent.append((command, params))
        if self.gate is not None:
            await self.gate.wait()
        elif not self.instant:
            await asyncio.sleep(0)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    async def read_capabilities(self) -> dict[str, Any]:
        return {}


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def entry_options() -> dict[str, Any]:
    """Options the entry starts with. Tests override this fixture."""
    return {"slots": {}}


@pytest.fixture
async def entry(
    hass: HomeAssistant, mock_zha, transport: FakeTransport, entry_options: dict[str, Any]
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=LOCK_IEEE,
        title="Onesti Lock (11:22:33:44)",
        data={CONF_IEEE: LOCK_IEEE},
        options=entry_options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.transport = transport
    return entry


async def _open_step(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> dict[str, Any]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})


async def _finish_progress(hass: HomeAssistant, result: dict[str, Any]) -> dict[str, Any]:
    """Let the background task finish and return where HA took the flow.

    HA moves the flow off the progress step by itself when the task is done,
    and the frontend then calls configure to follow it. The assert checks the
    first half, the configure call is the second.
    """
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    flow = _flow(hass, result)
    await hass.async_block_till_done()
    assert flow.cur_step["type"] is FlowResultType.SHOW_PROGRESS_DONE
    return await hass.config_entries.options.async_configure(result["flow_id"])


def _flow(hass: HomeAssistant, result: dict[str, Any]) -> Any:
    """The live options flow object behind a result.

    The flow manager has no public accessor for the handler, and _progress
    has held it under this name from the minimum target to current.
    """
    return hass.config_entries.options._progress[result["flow_id"]]


def _slot_choices(result: dict[str, Any]) -> dict[str, str]:
    """The options of the `slot` selector in a form result."""
    for key, validator in result["data_schema"].schema.items():
        if key == "slot":
            assert isinstance(validator, vol.In)
            return dict(validator.container)
    raise AssertionError("form has no slot field")


def _suggested(result: dict[str, Any]) -> dict[str, Any]:
    """Suggested values the form was re-rendered with."""
    return {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }


# -- Menu --


async def test_menu(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == ["set_pin", "clear_pin", "name_slot", "view_slots", "settings"]


# -- set_pin --


@pytest.mark.parametrize("code", ["123", "123456789", "12a4", ""])
async def test_set_pin_invalid_code_shows_error(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport, code: str
) -> None:
    result = await _open_step(hass, entry, "set_pin")
    user_input = {"slot": "4", "name": "Kari", "code": code}

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "set_pin"
    assert result["errors"] == {"code": "invalid_pin"}
    assert result["description_placeholders"] == {"min": "4", "max": "8"}
    assert _suggested(result) == user_input
    assert transport.sent == []


async def test_set_pin_form_carries_the_length_range(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "set_pin")

    # Sent with the first render too, so the form never shows a bare {min}.
    assert result["description_placeholders"] == {"min": "4", "max": "8"}


REPORTED_6_TO_10 = {"slots": {}, "capabilities": {"min_pin_length": 6, "max_pin_length": 10}}


@pytest.mark.parametrize("entry_options", [REPORTED_6_TO_10])
@pytest.mark.parametrize("code", ["12345", "12345678901"])
async def test_set_pin_outside_reported_range_is_invalid_pin_with_placeholders(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport, code: str
) -> None:
    result = await _open_step(hass, entry, "set_pin")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"slot": "4", "name": "Kari", "code": code}
    )

    assert result["errors"] == {"code": "invalid_pin"}
    assert result["description_placeholders"] == {"min": "6", "max": "10"}
    assert transport.sent == []
    # The frontend fills the error text from the form's placeholders. Doing
    # the same with the translations HA loaded shows no brace survives.
    translations = await async_get_translations(hass, "en", "options", {DOMAIN})
    message = translations[f"component.{DOMAIN}.options.error.invalid_pin"]
    assert message.format(**result["description_placeholders"]) == "PIN code must be 6-10 digits"


@pytest.mark.parametrize("entry_options", [REPORTED_6_TO_10])
async def test_set_pin_inside_reported_range_is_sent(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    result = await _open_step(hass, entry, "set_pin")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"slot": "4", "name": "Kari", "code": "1234567890"}
    )
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(transport.sent) == 1


async def test_set_pin_completes_through_ha(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    result = await _open_step(hass, entry, "set_pin")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"slot": "4", "name": "Kari", "code": "1234"}
    )
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_set_pin_valid_code_runs_progress_and_saves(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    result = await _open_step(hass, entry, "set_pin")
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"slot": "4", "name": "Kari", "code": "1234"}
    )
    assert result["step_id"] == "set_pin_progress"
    assert result["progress_action"] == "set_pin_progress"
    # Passed as progress_task, which HA has required since 2024.5.
    assert _flow(hass, result).async_get_progress_task() is not None
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert transport.sent == [
        (SET_PIN_COMMAND, {"user_id": 4, "user_status": 1, "user_type": 0, "pin_code": "1234"})
    ]
    assert entry.options["slots"]["4"] == {"name": "Kari", "has_pin": True}


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (False, "lock_unreachable"),
        (TimeoutError(), "lock_unreachable"),
        (RuntimeError("radio on fire"), "unknown"),
    ],
    ids=["send_failed", "timeout", "unexpected"],
)
async def test_set_pin_failure_returns_to_form_with_input(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    transport: FakeTransport,
    outcome: bool | BaseException,
    error: str,
) -> None:
    transport.result = outcome
    user_input = {"slot": "5", "name": "Ola", "code": "56789"}
    result = await _open_step(hass, entry, "set_pin")

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "set_pin"
    assert result["errors"] == {"base": error}
    assert _suggested(result) == user_input
    assert "5" not in entry.options["slots"]


async def test_set_pin_can_retry_after_failure(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    transport.result = False
    user_input = {"slot": "5", "name": "Ola", "code": "56789"}
    result = await _open_step(hass, entry, "set_pin")
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    result = await _finish_progress(hass, result)
    assert result["errors"] == {"base": "lock_unreachable"}

    transport.result = True
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(transport.sent) == 2
    assert entry.options["slots"]["5"] == {"name": "Ola", "has_pin": True}


async def test_set_pin_labels_slots_from_storage(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    hass.config_entries.async_update_entry(entry, options={"slots": {"4": {"name": "Kari", "has_pin": True}}})

    result = await _open_step(hass, entry, "set_pin")

    choices = _slot_choices(result)
    assert choices["3"] == "Slot 3: Vacant"
    assert choices["4"] == "Slot 4: Kari"


# -- Reserved slots --


@pytest.mark.parametrize(
    ("entry_options", "first"),
    [
        ({"slots": {}}, 3),
        ({"slots": {}, CONF_RESERVED_SLOTS: 1}, 1),
        ({"slots": {}, CONF_RESERVED_SLOTS: 2}, 2),
    ],
)
async def test_set_pin_never_offers_reserved_slots(
    hass: HomeAssistant, entry: MockConfigEntry, first: int
) -> None:
    result = await _open_step(hass, entry, "set_pin")

    choices = [int(slot) for slot in _slot_choices(result)]
    assert choices == list(range(first, first + 10))


@pytest.mark.parametrize(
    "entry_options",
    [
        {
            "slots": {
                "0": {"name": "Master", "has_pin": True},
                "1": {"name": "Admin", "has_pin": True},
                "2": {"name": "Spare", "has_pin": False},
                "3": {"name": "Kari", "has_pin": True},
                "500": {"name": "", "has_pin": True},
            }
        }
    ],
)
async def test_clear_pin_never_offers_reserved_slots(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "clear_pin")

    assert result["type"] is FlowResultType.FORM
    assert _slot_choices(result) == {"3": "Slot 3: Kari", "500": "Slot 500"}


# -- clear_pin --


async def test_clear_pin_without_active_slots_aborts(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "clear_pin")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_active_slots"


@pytest.mark.parametrize("entry_options", [{"slots": {"4": {"name": "Kari", "has_pin": True}}}])
async def test_clear_pin_completes_through_ha(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "clear_pin")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": "4"})
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("entry_options", [{"slots": {"4": {"name": "Kari", "has_pin": True}}}])
async def test_clear_pin_clears_the_slot(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    result = await _open_step(hass, entry, "clear_pin")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": "4"})
    assert result["step_id"] == "clear_pin_progress"
    assert result["progress_action"] == "clear_pin_progress"
    assert _flow(hass, result).async_get_progress_task() is not None
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert transport.sent == [(CLEAR_PIN_COMMAND, {"user_id": 4})]
    # clear_pin, not clear_slot: the name stays.
    assert entry.options["slots"]["4"] == {"name": "Kari", "has_pin": False}


@pytest.mark.parametrize(
    "entry_options",
    [
        {
            "slots": {
                "4": {"name": "Kari", "has_pin": True},
                "5": {"name": "Tag", "has_pin": False},
                "6": {"name": "", "has_pin": True},
            }
        }
    ],
)
async def test_clear_pin_lists_only_slots_with_a_pin(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "clear_pin")

    # Slot 5 is named but has no PIN, like an RFID tag. It is not offered.
    assert _slot_choices(result) == {"4": "Slot 4: Kari", "6": "Slot 6"}


@pytest.mark.parametrize("entry_options", [{"slots": {"5": {"name": "Tag", "has_pin": False}}}])
async def test_clear_pin_with_only_named_slots_aborts(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "clear_pin")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_active_slots"


@pytest.mark.parametrize("entry_options", [{"slots": {"4": {"name": "Kari", "has_pin": True}}}])
@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (False, "lock_unreachable"),
        (TimeoutError(), "lock_unreachable"),
        (RuntimeError("radio on fire"), "unknown"),
    ],
    ids=["send_failed", "timeout", "unexpected"],
)
async def test_clear_pin_failure_returns_to_form_with_input(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    transport: FakeTransport,
    outcome: bool | BaseException,
    error: str,
) -> None:
    transport.result = outcome
    result = await _open_step(hass, entry, "clear_pin")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": "4"})
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "clear_pin"
    assert result["errors"] == {"base": error}
    assert _suggested(result) == {"slot": "4"}
    assert entry.options["slots"]["4"] == {"name": "Kari", "has_pin": True}


@pytest.mark.parametrize("entry_options", [{"slots": {"4": {"name": "Kari", "has_pin": True}}}])
async def test_clear_pin_can_retry_after_failure(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    transport.result = TimeoutError()
    result = await _open_step(hass, entry, "clear_pin")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": "4"})
    result = await _finish_progress(hass, result)
    assert result["errors"] == {"base": "lock_unreachable"}

    transport.result = True
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": "4"})
    result = await _finish_progress(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(transport.sent) == 2
    assert entry.options["slots"]["4"]["has_pin"] is False


# -- A task that is done before the spinner shows --
#
# HA starts tasks eagerly, so a command that never waits finishes inside the
# submit. The progress step then answers progress_done at once, and HA follows
# it within the same configure call, passing the submitted input along.


@pytest.mark.parametrize(("outcome", "error"), [(True, None), (False, "lock_unreachable")])
async def test_set_pin_instant_task(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport, outcome: bool, error: str | None
) -> None:
    transport.instant = True
    transport.result = outcome
    user_input = {"slot": "5", "name": "Ola", "code": "56789"}
    result = await _open_step(hass, entry, "set_pin")

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    if error is None:
        assert result["type"] is FlowResultType.CREATE_ENTRY
    else:
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}
        assert _suggested(result) == user_input
    assert len(transport.sent) == 1


@pytest.mark.parametrize("entry_options", [{"slots": {"4": {"name": "Kari", "has_pin": True}}}])
@pytest.mark.parametrize(("outcome", "error"), [(True, None), (False, "lock_unreachable")])
async def test_clear_pin_instant_task(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport, outcome: bool, error: str | None
) -> None:
    transport.instant = True
    transport.result = outcome
    result = await _open_step(hass, entry, "clear_pin")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": "4"})

    if error is None:
        assert result["type"] is FlowResultType.CREATE_ENTRY
    else:
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}
        assert _suggested(result) == {"slot": "4"}
    # One send only: the form must not restart the task on the routed input.
    assert len(transport.sent) == 1


# -- name_slot --


@pytest.mark.parametrize("slot", [0, 999])
async def test_name_slot_accepts_every_slot(hass: HomeAssistant, entry: MockConfigEntry, slot: int) -> None:
    result = await _open_step(hass, entry, "name_slot")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": slot, "name": " Kari "})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["slots"][str(slot)] == {"name": "Kari", "has_pin": False}


@pytest.mark.parametrize("slot", [1000, -1])
async def test_name_slot_rejects_out_of_range(hass: HomeAssistant, entry: MockConfigEntry, slot: int) -> None:
    result = await _open_step(hass, entry, "name_slot")
    user_input = {"slot": slot, "name": "Kari"}

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "name_slot"
    assert result["errors"] == {"slot": "invalid_slot"}
    assert _suggested(result) == user_input
    assert str(slot) not in entry.options["slots"]


@pytest.mark.parametrize(
    "entry_options",
    [{"slots": {"0": {"name": "Master Kari", "has_pin": False}, "4": {"name": "Ola", "has_pin": True}}}],
)
async def test_name_slot_empty_name_removes_it(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    for slot in (0, 4):
        result = await _open_step(hass, entry, "name_slot")
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": slot, "name": ""})
        assert result["type"] is FlowResultType.CREATE_ENTRY

    # A slot left with neither name nor PIN is dropped, one with a PIN stays.
    assert entry.options["slots"] == {"4": {"name": "", "has_pin": True}}


async def test_name_slot_name_defaults_to_empty(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "name_slot")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": 7})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "7" not in entry.options["slots"]


# -- view_slots --

VIEW_SLOTS_OPTIONS = {
    "slots": {
        "0": {"name": "Kari", "has_pin": True},
        "3": {"name": "Ola", "has_pin": True},
        "4": {"name": "Tag", "has_pin": False},
    }
}


@pytest.mark.parametrize("entry_options", [VIEW_SLOTS_OPTIONS])
@pytest.mark.parametrize(
    ("language", "expected_head"),
    [
        (
            "en",
            [
                "Slot 0: Kari (master)",
                "Slot 1: Master",
                "Slot 2: Master",
                "Slot 3: **Ola** (PIN active)",
                "Slot 4: Tag (no PIN)",
                "Slot 5: Vacant",
            ],
        ),
        (
            "nb",
            [
                "Slot 0: Kari (master)",
                "Slot 1: Master",
                "Slot 2: Master",
                "Slot 3: **Ola** (PIN aktiv)",
                "Slot 4: Tag (ingen PIN)",
                "Slot 5: Ledig",
            ],
        ),
        (
            "sv",
            [
                "Plats 0: Kari (master)",
                "Plats 1: Master",
                "Plats 2: Master",
                "Plats 3: **Ola** (PIN aktiv)",
                "Plats 4: Tag (ingen PIN)",
                "Plats 5: Ledig",
            ],
        ),
        (
            "da",
            [
                "Plads 0: Kari (master)",
                "Plads 1: Master",
                "Plads 2: Master",
                "Plads 3: **Ola** (PIN aktiv)",
                "Plads 4: Tag (ingen PIN)",
                "Plads 5: Ledig",
            ],
        ),
    ],
)
async def test_view_slots_text_per_language(
    hass: HomeAssistant, entry: MockConfigEntry, language: str, expected_head: list[str]
) -> None:
    hass.config.language = language

    result = await _open_step(hass, entry, "view_slots")

    assert result["type"] is FlowResultType.FORM
    lines = result["description_placeholders"]["slot_status"].split("\n")
    # Reserved slots 0-2, then ten user slots from 3.
    assert len(lines) == 13
    assert lines[:6] == expected_head
    assert lines[-1].split(":")[0].endswith(" 12")


@pytest.mark.parametrize("entry_options", [{"slots": {}, CONF_RESERVED_SLOTS: 1}])
async def test_view_slots_follows_reserved_slots(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "view_slots")

    lines = result["description_placeholders"]["slot_status"].split("\n")
    assert lines[:3] == ["Slot 0: Master", "Slot 1: Vacant", "Slot 2: Vacant"]
    assert len(lines) == 11


async def test_view_slots_submit_returns_to_menu(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await _open_step(hass, entry, "view_slots")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"


# -- settings --


@pytest.mark.parametrize(
    ("entry_options", "default"),
    [({"slots": {}}, 3), ({"slots": {}, CONF_RESERVED_SLOTS: 2}, 2)],
)
async def test_settings_default_is_current_value(
    hass: HomeAssistant, entry: MockConfigEntry, default: int
) -> None:
    result = await _open_step(hass, entry, "settings")

    assert result["type"] is FlowResultType.FORM
    assert next(iter(result["data_schema"].schema)).default() == default


@pytest.mark.parametrize(
    "entry_options",
    [{"slots": {"0": {"name": "Kari", "has_pin": True}, "4": {"name": "Ola", "has_pin": True}}}],
)
@pytest.mark.parametrize("submitted", [1, "1"])
async def test_settings_stores_reserved_slots_and_keeps_slots(
    hass: HomeAssistant, entry: MockConfigEntry, entry_options: dict[str, Any], submitted: int | str
) -> None:
    result = await _open_step(hass, entry, "settings")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_RESERVED_SLOTS: submitted})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_RESERVED_SLOTS] == 1
    assert entry.options["slots"] == entry_options["slots"]


@pytest.mark.parametrize("value", [0, 4])
async def test_settings_rejects_out_of_bounds(hass: HomeAssistant, entry: MockConfigEntry, value: int) -> None:
    result = await _open_step(hass, entry, "settings")

    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(result["flow_id"], {CONF_RESERVED_SLOTS: value})

    assert CONF_RESERVED_SLOTS not in entry.options


# -- Closing the dialog while a write runs --
#
# Closing the dialog aborts the flow, and HA cancels its progress task. The
# command may already have reached the lock by then, so the write itself must
# run to the end and save, and only the waiting is cancelled.


@pytest.mark.parametrize("entry_options", [{"slots": {"4": {"name": "Kari", "has_pin": True}}}])
@pytest.mark.parametrize(
    ("step", "user_input", "action", "saved"),
    [
        ("set_pin", {"slot": "5", "name": "Ola", "code": "56789"}, "setting PIN", {"name": "Ola", "has_pin": True}),
        ("clear_pin", {"slot": "4"}, "clearing PIN", {"name": "Kari", "has_pin": False}),
    ],
    ids=["set_pin", "clear_pin"],
)
async def test_closing_the_dialog_lets_the_write_finish(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    transport: FakeTransport,
    caplog: pytest.LogCaptureFixture,
    step: str,
    user_input: dict[str, Any],
    action: str,
    saved: dict[str, Any],
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.onesti_lock")
    transport.gate = asyncio.Event()
    result = await _open_step(hass, entry, step)
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    progress_task = _flow(hass, result).async_get_progress_task()

    hass.config_entries.options.async_abort(result["flow_id"])
    with contextlib.suppress(asyncio.CancelledError):
        await progress_task
    assert progress_task.cancelled()
    assert "keeps running" in caplog.text

    transport.gate.set()
    await hass.async_block_till_done()

    assert entry.options["slots"][user_input["slot"]] == saved
    assert f"Finished {action} on slot {user_input['slot']}" in caplog.text


# -- Two paths, one flow object --


@pytest.mark.parametrize("entry_options", [{"slots": {"4": {"name": "Kari", "has_pin": True}}}])
async def test_set_pin_failure_does_not_reach_clear_pin(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    """set_pin and clear_pin keep separate input and errors.

    The dialog cannot move from one to the other, so the handler's steps are
    called directly here. That is the object both paths once shared state on.
    """
    transport.result = False
    set_input = {"slot": "5", "name": "Ola", "code": "56789"}
    result = await _open_step(hass, entry, "set_pin")
    flow = _flow(hass, result)
    result = await hass.config_entries.options.async_configure(result["flow_id"], set_input)
    result = await _finish_progress(hass, result)
    assert result["errors"] == {"base": "lock_unreachable"}

    form = await flow.async_step_clear_pin()
    assert form["errors"] == {}
    assert _suggested(form) == {}

    await flow.async_step_clear_pin({"slot": "4"})
    await hass.async_block_till_done()
    await flow.async_step_clear_pin_progress()
    form = await flow.async_step_clear_pin()
    assert form["errors"] == {"base": "lock_unreachable"}
    assert _suggested(form) == {"slot": "4"}
    assert transport.sent[-1] == (CLEAR_PIN_COMMAND, {"user_id": 4})

    # And the set_pin input survived the clear attempt untouched.
    transport.result = True
    await flow.async_step_set_pin_progress()
    await hass.async_block_till_done()
    await flow.async_step_set_pin_progress()
    assert transport.sent[-1][1]["user_id"] == 5
    assert entry.options["slots"]["5"] == {"name": "Ola", "has_pin": True}


# -- Two dialogs at once --


@pytest.mark.parametrize("entry_options", [{"slots": {"4": {"name": "Kari", "has_pin": True}}}])
async def test_concurrent_flows_keep_both_writes(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    transport.gate = asyncio.Event()
    set_result = await _open_step(hass, entry, "set_pin")
    clear_result = await _open_step(hass, entry, "clear_pin")
    set_result = await hass.config_entries.options.async_configure(
        set_result["flow_id"], {"slot": "5", "name": "Ola", "code": "56789"}
    )
    clear_result = await hass.config_entries.options.async_configure(clear_result["flow_id"], {"slot": "4"})
    assert set_result["type"] is FlowResultType.SHOW_PROGRESS
    assert clear_result["type"] is FlowResultType.SHOW_PROGRESS

    transport.gate.set()
    set_result = await _finish_progress(hass, set_result)
    clear_result = await _finish_progress(hass, clear_result)

    assert set_result["type"] is FlowResultType.CREATE_ENTRY
    assert clear_result["type"] is FlowResultType.CREATE_ENTRY
    assert sorted(command for command, _ in transport.sent) == [SET_PIN_COMMAND, CLEAR_PIN_COMMAND]
    # Each result dialog saved the options as they stood when it finished,
    # so neither wrote the other's change back out.
    assert entry.options["slots"] == {
        "4": {"name": "Kari", "has_pin": False},
        "5": {"name": "Ola", "has_pin": True},
    }


async def test_concurrent_set_pin_flows_keep_their_own_input(
    hass: HomeAssistant, entry: MockConfigEntry, transport: FakeTransport
) -> None:
    transport.gate = asyncio.Event()
    first = await _open_step(hass, entry, "set_pin")
    second = await _open_step(hass, entry, "set_pin")
    first = await hass.config_entries.options.async_configure(
        first["flow_id"], {"slot": "4", "name": "Kari", "code": "1234"}
    )
    second = await hass.config_entries.options.async_configure(
        second["flow_id"], {"slot": "5", "name": "Ola", "code": "56789"}
    )

    transport.gate.set()
    await _finish_progress(hass, first)
    await _finish_progress(hass, second)

    assert sorted(params["user_id"] for _, params in transport.sent) == [4, 5]
    assert entry.options["slots"] == {
        "4": {"name": "Kari", "has_pin": True},
        "5": {"name": "Ola", "has_pin": True},
    }
