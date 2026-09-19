"""A canary PIN through every path a code travels, and nowhere it must not land.

tests/test_no_pin_exposure.py guards by name: it looks for pin_code and
code in the source. That misses a renamed attribute or a whole params dict
handed to a log call. This file guards by value instead. A known PIN goes
in through the service and the options flow, the real coordinator and the
real ZhaLockTransport carry it to the lock's zigpy Door Lock cluster, and
the cluster answers with success, a failure status, a duplicate-code
status, the Nimly IndexError, a timeout, a failed delivery, or a ValueError
that quotes the params.
Afterwards the canary must not be found in:

- any log record, from any logger, at DEBUG and up, tracebacks included,
- the config entry, options included, which is what .storage persists,
- the state or attributes of any entity,
- any event fired on the bus,
- any repair issue,
- the exception that reaches whoever called.

One thing carries the code by design and is left out of the event check:
the call_service event for onesti_lock.set_pin is the caller's own input,
which Home Assistant fires for every service call. The same event reaches
the log too, because homeassistant.core logs every bus event at DEBUG, and
pytest-homeassistant-custom-component turns DEBUG on whenever pytest runs
verbose (the -v in addopts). That one record is left out of the log check. The transport sends to
the cluster directly and calls no service, so no call_service event of
ours carries it; test_no_call_service_event_carries_the_pin states that on
its own, without the exception for onesti_lock.set_pin.

The cluster errors above all come back through the real transport, which
catches them. test_a_transport_that_raises_does_not_leak covers what
happens when a write raises past it anyway.

The options flow re-renders a failed set_pin form with the code as a
suggested value, so the user does not type it again. That goes back to the
browser that sent it and is not checked here.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.const import EVENT_CALL_SERVICE, MATCH_ALL
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zigpy.exceptions import DeliveryError

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN
from tests_ha.conftest import DOORLOCK_CLUSTER_ID, LOCK_IEEE, ZclStatus, lock_cluster

CANARY = "83729164"
# One digit too many for every lock, so it is refused with invalid_pin.
TOO_LONG = CANARY + "0"
SLOT = 5
SET_PIN_COMMAND = 0x0005
ATTR_OPERATION_EVENT = 0x0100
# The attribute that carries typed PIN digits; the listener must ignore it.
ATTR_PIN_DIGITS = 0x0101
KEYPAD_UNLOCK_SLOT_5 = 0x02020000 | SLOT


def _raising(kind: type[BaseException], text: str) -> Callable[[dict], BaseException]:
    """An error whose message quotes the params, pin_code included."""
    return lambda params: kind(text.format(params=params))


# What the lock's cluster does with each command, in order, and the error
# key the caller gets (None when the PIN was delivered). Each message
# quotes the params, the worst case for anything that logs it.
SCENARIOS: dict[str, tuple[list[Callable[[dict], Any]], str | None]] = {
    "success": ([], None),
    "failure_status": ([lambda params: SimpleNamespace(status=ZclStatus.FAILURE)], "lock_rejected"),
    "duplicate_status": ([lambda params: SimpleNamespace(status=3)], "lock_rejected_duplicate"),
    "index_error": ([_raising(IndexError, "tuple index out of range parsing {params}")], None),
    "timeout": ([_raising(TimeoutError, "no answer to {params}")] * 2, "lock_unreachable"),
    "delivery_error": ([_raising(DeliveryError, "failed to deliver {params}")] * 2, "lock_unreachable"),
    "value_error": ([_raising(ValueError, "Invalid params {params}")], "lock_unreachable"),
}


@pytest.fixture(autouse=True)
def _debug_everywhere(caplog) -> None:
    """Every logger at DEBUG, so nothing is filtered out before the check."""
    caplog.set_level(logging.DEBUG)


@pytest.fixture
def bus_events(hass: HomeAssistant) -> list[Event]:
    events: list[Event] = []

    @callback
    def _record(event: Event) -> None:
        events.append(event)

    hass.bus.async_listen(MATCH_ALL, _record)
    return events


@pytest.fixture
def zha_service(mock_zha) -> SimpleNamespace:
    """The lock's Door Lock cluster, following a scripted list of effects.

    `effects` is what the cluster does with each command, `calls` what it
    was sent, as {"command": id, "params": {...}}.
    """
    cluster = lock_cluster(mock_zha)
    return SimpleNamespace(effects=cluster.command_effects, calls=cluster.commands)


@pytest.fixture
async def entry(hass: HomeAssistant, zha_service) -> MockConfigEntry:
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
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


# -- Where the canary must not be --


def _is_known_carrier_record(record: logging.LogRecord) -> bool:
    """homeassistant.core's DEBUG line for the known carrier event."""
    return (
        record.name == "homeassistant.core"
        and record.levelno == logging.DEBUG
        and record.getMessage().startswith(f"Bus:Handling <Event {EVENT_CALL_SERVICE}[")
        and f"domain={DOMAIN}," in record.getMessage()
    )


def _log_texts(caplog) -> list[str]:
    """Every log record, formatted and raw, except the known carrier.

    Built from the records rather than caplog.text, which holds the same
    records but cannot drop the carrier line on its own.
    """
    formatter = logging.Formatter()
    texts = []
    for record in caplog.records:
        if _is_known_carrier_record(record):
            continue
        texts.append(formatter.format(record))
        texts.append(record.getMessage())
        if record.exc_info:
            texts.append(formatter.formatException(record.exc_info))
        if record.stack_info:
            texts.append(record.stack_info)
    return texts


def _exception_texts(error: BaseException | None) -> list[str]:
    """What a caller can read off the exception and everything chained to it."""
    texts = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        texts += [str(error), repr(error), repr(error.args)]
        texts.append(repr(getattr(error, "translation_placeholders", None)))
        error = error.__cause__ or error.__context__
    return texts


def _is_known_carrier(event: Event) -> bool:
    """The call_service event for our own service, see the module docstring."""
    return event.event_type == EVENT_CALL_SERVICE and event.data.get("domain") == DOMAIN


def _places(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    caplog,
    events: list[Event],
    raised: BaseException | None,
) -> dict[str, list[str]]:
    return {
        "log": _log_texts(caplog),
        "config entry": [json.dumps(entry.as_dict(), default=str)],
        "states": [f"{s.entity_id} {s.state} {dict(s.attributes)!r}" for s in hass.states.async_all()],
        "events": [f"{e.event_type} {dict(e.data)!r}" for e in events if not _is_known_carrier(e)],
        "repair issues": [repr(dataclasses.asdict(i)) for i in ir.async_get(hass).issues.values()],
        "exception": _exception_texts(raised),
    }


def assert_no_canary(hass, entry, caplog, events, raised=None, canary: str = CANARY) -> None:
    leaks = {
        place: [text for text in texts if canary in text]
        for place, texts in _places(hass, entry, caplog, events, raised).items()
    }
    leaks = {place: texts for place, texts in leaks.items() if texts}
    assert not leaks, f"the PIN {canary} leaked into {sorted(leaks)}: {leaks}"


# -- Driving the paths --


async def _report(hass: HomeAssistant, mock_zha, attribute_id: int, raw_value: Any) -> None:
    cluster = mock_zha.device_proxies[LOCK_IEEE].device.device.endpoints[11].in_clusters[DOORLOCK_CLUSTER_ID]
    event = SimpleNamespace(attribute_id=attribute_id, raw_value=raw_value)
    for listener in list(cluster._event_listeners["attribute_report"]):
        listener(event)
    await hass.async_block_till_done()


async def _after_the_write(hass: HomeAssistant, mock_zha) -> None:
    """The lock reports someone using slot 5, and once the typed digits.

    Runs the activity sensor, the onesti_lock_activity event and the
    listener's handling of the attribute that carries PIN digits, all after
    the write, so the slot sensors show whatever the write left behind.
    """
    await _report(hass, mock_zha, ATTR_OPERATION_EVENT, KEYPAD_UNLOCK_SLOT_5)
    await _report(hass, mock_zha, ATTR_PIN_DIGITS, CANARY)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _service_set_pin(hass: HomeAssistant, code: str) -> HomeAssistantError | None:
    try:
        await hass.services.async_call(
            DOMAIN, "set_pin", {"slot": SLOT, "name": "Kari", "code": code}, blocking=True
        )
    except HomeAssistantError as err:
        return err
    return None


async def _flow_set_pin(hass: HomeAssistant, entry: MockConfigEntry, code: str) -> dict[str, Any]:
    """Run set_pin through the options flow; returns where the flow ended."""
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "set_pin"})
    result = await flow.async_configure(result["flow_id"], {"slot": str(SLOT), "name": "Kari", "code": code})
    if result["type"] is FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done(wait_background_tasks=True)
        result = await flow.async_configure(result["flow_id"])
    return result


def _pin_sent(zha_service) -> bool:
    """The canary really went out, so its absence elsewhere means something."""
    return any(
        call["command"] == SET_PIN_COMMAND and call["params"].get("pin_code") == CANARY
        for call in zha_service.calls
    )


# -- Tests --


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_service_set_pin(hass, entry, mock_zha, zha_service, bus_events, caplog, scenario) -> None:
    effects, error = SCENARIOS[scenario]
    zha_service.effects[:] = effects

    raised = await _service_set_pin(hass, CANARY)
    await _after_the_write(hass, mock_zha)

    assert _pin_sent(zha_service)
    assert (raised.translation_key if raised else None) == error
    assert entry.options["slots"].get(str(SLOT), {}).get("has_pin", False) is (error is None)
    assert_no_canary(hass, entry, caplog, bus_events, raised)


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_options_flow_set_pin(hass, entry, mock_zha, zha_service, bus_events, caplog, scenario) -> None:
    effects, error = SCENARIOS[scenario]
    zha_service.effects[:] = effects

    result = await _flow_set_pin(hass, entry, CANARY)
    await _after_the_write(hass, mock_zha)

    assert _pin_sent(zha_service)
    if error is None:
        assert result["type"] is FlowResultType.CREATE_ENTRY
    else:
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}
    assert_no_canary(hass, entry, caplog, bus_events)


async def test_service_refuses_a_code_too_long_without_quoting_it(
    hass, entry, zha_service, bus_events, caplog
) -> None:
    raised = await _service_set_pin(hass, TOO_LONG)

    assert raised is not None
    assert raised.translation_key == "invalid_pin"
    assert zha_service.calls == []
    assert_no_canary(hass, entry, caplog, bus_events, raised, canary=TOO_LONG)


async def test_options_flow_refuses_a_code_too_long_without_logging_it(
    hass, entry, zha_service, bus_events, caplog
) -> None:
    result = await _flow_set_pin(hass, entry, TOO_LONG)

    assert result["errors"] == {"code": "invalid_pin"}
    assert zha_service.calls == []
    assert_no_canary(hass, entry, caplog, bus_events, canary=TOO_LONG)


async def test_no_call_service_event_carries_the_pin(hass, entry, zha_service, bus_events) -> None:
    # The recorder stores every call_service event with its full service
    # data. The transport once sent through ZHA's issue_zigbee_cluster_command
    # service, so a PIN set from the options flow, which passes the code
    # through no service of ours, still landed in the database.
    result = await _flow_set_pin(hass, entry, CANARY)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _pin_sent(zha_service)
    call_service_events = [e for e in bus_events if e.event_type == EVENT_CALL_SERVICE]
    assert not [e for e in call_service_events if CANARY in repr(dict(e.data))]


@pytest.mark.parametrize("path", ["options_flow", "service"])
async def test_a_transport_that_raises_does_not_leak(hass, entry, zha_service, bus_events, caplog, path) -> None:
    async def send(command: int, params: dict) -> bool:
        raise ValueError(f"Invalid params {params}")

    entry.runtime_data.transport.send = send
    raised: BaseException | None = None
    if path == "options_flow":
        result = await _flow_set_pin(hass, entry, CANARY)
        assert result["errors"] == {"base": "unknown"}
    else:
        raised = await _service_set_pin(hass, CANARY)
        assert raised is not None
        assert raised.translation_key == "write_failed"
        assert raised.__cause__ is None and raised.__context__ is None
    # The failure is still reported, just without the code or a traceback.
    assert any(r.levelname == "ERROR" and "ValueError" in r.getMessage() for r in caplog.records)
    assert not any(r.exc_info for r in caplog.records)

    assert_no_canary(hass, entry, caplog, bus_events, raised)
