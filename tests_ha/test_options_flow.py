"""The options flow, driven through a real Home Assistant.

Each test runs NimlyProOptionsFlow through hass.config_entries.options, so
HA's own flow manager handles menus, forms, schema validation, progress
tasks and entry updates. The coordinator is the real one created by
async_setup_entry. Only its transport is swapped for a fake, which stands
in for the Zigbee radio and records every command the flow sends.

The PIN steps never leave their progress step under Home Assistant's flow
manager: when the task finishes, HA calls async_step_set_pin_progress again,
which shows the same finished task, and the *_progress_done steps are never
reached. The end-to-end tests for that are xfail. The rest drive the flow
through HA up to the finished task and then call the done step on the flow
object, which is how the error mapping and the preserved input get tested
until the glue is fixed.
"""

from __future__ import annotations

from typing import Any

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, CONF_RESERVED_SLOTS, DOMAIN
from tests_ha.conftest import LOCK_IEEE

SET_PIN_COMMAND = 0x0005
CLEAR_PIN_COMMAND = 0x0007


class FakeTransport:
    """Stands in for ZhaLockTransport.

    `result` is what send() returns, or an exception instance to raise.
    """

    def __init__(self) -> None:
        self.result: bool | BaseException = True
        self.sent: list[tuple[int, dict]] = []

    def cluster(self) -> None:
        return None

    async def wake(self) -> None:
        return None

    async def send(self, command: int, params: dict) -> bool:
        self.sent.append((command, params))
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
    hass.data[DOMAIN][entry.entry_id]["coordinator"].transport = transport
    return entry


async def _open_step(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> dict[str, Any]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})


async def _finish_progress(hass: HomeAssistant, result: dict[str, Any]) -> dict[str, Any]:
    """Let the background task finish and return where HA took the flow."""
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    await hass.async_block_till_done()
    return await hass.config_entries.options.async_configure(result["flow_id"])


def _flow(hass: HomeAssistant, result: dict[str, Any]) -> Any:
    """The live options flow object behind a result.

    The flow manager has no public accessor for the handler, and _progress
    has held it under this name from the minimum target to current.
    """
    return hass.config_entries.options._progress[result["flow_id"]]


async def _finish_progress_by_hand(hass: HomeAssistant, result: dict[str, Any]) -> dict[str, Any]:
    """Let the task finish, then run the done step as HA should have.

    A done step that routes back to the form is followed to that form, the
    way HA follows a SHOW_PROGRESS_DONE result.
    """
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    await hass.async_block_till_done()
    flow = _flow(hass, result)
    done = await getattr(flow, f"async_step_{result['step_id']}_done")()
    if done["type"] is FlowResultType.SHOW_PROGRESS_DONE:
        return await getattr(flow, f"async_step_{done['step_id']}")()
    return done


PROGRESS_STUCK = pytest.mark.xfail(
    reason=(
        "config_flow.py: async_step_set_pin_progress and "
        "async_step_clear_pin_progress never check task.done(), so HA re-shows "
        "the progress step when the task finishes and the *_progress_done "
        "steps are never called"
    ),
    strict=True,
)


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
    assert _suggested(result) == user_input
    assert transport.sent == []


@PROGRESS_STUCK
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
    result = await _finish_progress_by_hand(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert transport.sent == [
        (SET_PIN_COMMAND, {"user_id": 4, "user_status": 1, "user_type": 0, "pin_code": "1234"})
    ]
    assert entry.options["slots"]["4"] == {"name": "Kari", "has_pin": True, "has_rfid": False}


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
    result = await _finish_progress_by_hand(hass, result)

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
    flow = _flow(hass, result)
    result = await _finish_progress_by_hand(hass, result)
    assert result["errors"] == {"base": "lock_unreachable"}

    # The form's submit, as HA would route it once the flow is back on it.
    transport.result = True
    result = await flow.async_step_set_pin(user_input)
    result = await _finish_progress_by_hand(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(transport.sent) == 2
    assert entry.options["slots"]["5"] == {"name": "Ola", "has_pin": True, "has_rfid": False}


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


@PROGRESS_STUCK
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
    result = await _finish_progress_by_hand(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert transport.sent == [(CLEAR_PIN_COMMAND, {"user_id": 4})]
    assert entry.options["slots"]["4"] == {"name": "", "has_pin": False, "has_rfid": False}


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
    result = await _finish_progress_by_hand(hass, result)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "clear_pin"
    assert result["errors"] == {"base": error}
    assert _suggested(result) == {"slot": "4"}
    assert entry.options["slots"]["4"] == {"name": "Kari", "has_pin": True}


# -- name_slot --


@pytest.mark.parametrize("slot", [0, 999])
async def test_name_slot_accepts_every_slot(hass: HomeAssistant, entry: MockConfigEntry, slot: int) -> None:
    result = await _open_step(hass, entry, "name_slot")

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slot": slot, "name": " Kari "})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["slots"][str(slot)] == {"name": "Kari", "has_pin": False, "has_rfid": False}


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
    assert entry.options["slots"] == {"4": {"name": "", "has_pin": True, "has_rfid": False}}


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
