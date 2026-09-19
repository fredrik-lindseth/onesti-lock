"""Which error class a service call raises, and that its message translates.

Home Assistant tells a mistake in the call from a failure behind it by
class: ServiceValidationError for input the user can fix (slot, PIN, which
lock), HomeAssistantError for the lock not taking the command. The frontend
shows the first without a traceback in the log. Both carry a translation
key, and every key must render in all four languages.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.translation import async_get_translations

from custom_components.onesti_lock import zha
from custom_components.onesti_lock.const import CONF_RESERVED_SLOTS, DOMAIN
from tests_ha.conftest import LOCK_IEEE, make_lock_proxy
from tests_ha.test_services import SECOND_LOCK_IEEE, _setup_lock

LANGUAGES = ("en", "nb", "sv", "da")
SET_PIN = {"slot": 5, "name": "Kari", "code": "1234"}

# service, data, translation key. One lock is loaded, with the default three
# reserved slots unless the case says otherwise.
INPUT_ERRORS: dict[str, tuple[str, dict[str, Any], str]] = {
    "set_pin_master_slot": ("set_pin", {**SET_PIN, "slot": 2}, "invalid_slot"),
    "clear_pin_master_slot": ("clear_pin", {"slot": 0}, "invalid_slot"),
    "clear_slot_master_slot": ("clear_slot", {"slot": 2}, "invalid_slot"),
    "set_name_above_ceiling": ("set_name", {"slot": 1000, "name": "Kari"}, "invalid_slot"),
    "short_pin": ("set_pin", {**SET_PIN, "code": "123"}, "invalid_pin"),
    "unknown_device": ("set_name", {"slot": 5, "name": "Kari", "device_id": "nope"}, "lock_not_found"),
    "unknown_ieee": (
        "set_name",
        {"slot": 5, "name": "Kari", "ieee": "00:00:00:00:00:00:00:01"},
        "lock_not_found_ieee",
    ),
}


class OutcomeTransport:
    """Every command ends the way the test says, or raises what it says."""

    def __init__(self, result: zha.SendOutcome | Exception) -> None:
        self.result = result
        self.sent: list[int] = []

    async def send(self, command_id: int, params: dict) -> zha.SendOutcome:
        self.sent.append(command_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


# outcome of the write, translation key.
TRANSPORT_ERRORS: dict[str, tuple[zha.SendOutcome | Exception, str]] = {
    "unreachable": (zha.SEND_UNREACHED, "lock_unreachable"),
    "rejected": (zha.rejected(0x0005, object(), 1), "lock_rejected"),
    "memory_full": (zha.rejected(0x0005, object(), 2), "lock_rejected_memory_full"),
    "duplicate": (zha.rejected(0x0005, object(), 3), "lock_rejected_duplicate"),
    "unexpected": (RuntimeError("boom"), "write_failed"),
}


async def _raised(hass: HomeAssistant, service: str, data: dict[str, Any]) -> HomeAssistantError:
    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
    return excinfo.value


async def _render(hass: HomeAssistant, err: HomeAssistantError) -> dict[str, str]:
    """The message per language, built the way the frontend builds it."""
    rendered = {}
    for language in LANGUAGES:
        translations = await async_get_translations(hass, language, "exceptions", [DOMAIN])
        template = translations[f"component.{DOMAIN}.exceptions.{err.translation_key}.message"]
        rendered[language] = template.format(**(err.translation_placeholders or {}))
    return rendered


async def _assert_translated(hass: HomeAssistant, err: HomeAssistantError) -> None:
    assert err.translation_domain == DOMAIN
    messages = await _render(hass, err)
    for language in ("nb", "sv", "da"):
        assert messages[language] != messages["en"], language
    for message in messages.values():
        assert "{" not in message


@pytest.mark.parametrize("case", INPUT_ERRORS)
async def test_input_errors_are_validation_errors(hass: HomeAssistant, mock_zha, case: str) -> None:
    service, data, key = INPUT_ERRORS[case]
    _, transport = await _setup_lock(hass, LOCK_IEEE)

    err = await _raised(hass, service, data)

    assert isinstance(err, ServiceValidationError)
    assert err.translation_key == key
    assert transport.sent == []
    await _assert_translated(hass, err)


async def test_multiple_locks_is_a_validation_error(hass: HomeAssistant, mock_zha) -> None:
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    await _setup_lock(hass, LOCK_IEEE)
    await _setup_lock(hass, SECOND_LOCK_IEEE)

    err = await _raised(hass, "set_pin", SET_PIN)

    assert isinstance(err, ServiceValidationError)
    assert err.translation_key == "multiple_locks"
    await _assert_translated(hass, err)


async def test_no_loaded_lock_is_a_validation_error(hass: HomeAssistant, mock_zha) -> None:
    entry, _ = await _setup_lock(hass, LOCK_IEEE)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    err = await _raised(hass, "set_name", {"slot": 5, "name": "Kari"})

    assert isinstance(err, ServiceValidationError)
    assert err.translation_key == "lock_not_found"


@pytest.mark.parametrize("service", ["set_pin", "clear_pin", "clear_slot"])
async def test_slot_zero_never_reaches_the_coordinator_guard(hass: HomeAssistant, mock_zha, service: str) -> None:
    """With one reserved slot, slot 0 is still refused by the service itself.

    The coordinator refuses it too, with a bare ValueError that carries no
    translation. The service's own check has to come first, so a user never
    sees that one.
    """
    _, transport = await _setup_lock(hass, LOCK_IEEE, {CONF_RESERVED_SLOTS: 1})
    data = SET_PIN if service == "set_pin" else {}

    err = await _raised(hass, service, {**data, "slot": 0})

    assert isinstance(err, ServiceValidationError)
    assert err.translation_key == "invalid_slot"
    assert err.translation_placeholders["min"] == "1"
    assert transport.sent == []


WRITES: dict[str, Callable[[HomeAssistant], Awaitable[None]]] = {
    "set_pin": lambda hass: hass.services.async_call(DOMAIN, "set_pin", SET_PIN, blocking=True),
    "clear_pin": lambda hass: hass.services.async_call(DOMAIN, "clear_pin", {"slot": 5}, blocking=True),
    "clear_slot": lambda hass: hass.services.async_call(DOMAIN, "clear_slot", {"slot": 5}, blocking=True),
}


@pytest.mark.parametrize("service", WRITES)
@pytest.mark.parametrize("case", TRANSPORT_ERRORS)
async def test_transport_errors_are_not_validation_errors(
    hass: HomeAssistant, mock_zha, case: str, service: str
) -> None:
    result, key = TRANSPORT_ERRORS[case]
    entry, _ = await _setup_lock(hass, LOCK_IEEE)
    transport = OutcomeTransport(result)
    entry.runtime_data.transport = transport

    with pytest.raises(HomeAssistantError) as excinfo:
        await WRITES[service](hass)

    err = excinfo.value
    assert not isinstance(err, ServiceValidationError)
    assert transport.sent, "the call should have reached the transport"
    # The fake transport hands back the same outcome whatever the command.
    assert err.translation_key == key
    await _assert_translated(hass, err)


async def test_every_exception_renders_in_every_language(hass: HomeAssistant, mock_zha) -> None:
    """Every key renders in every language, placeholders filled, none left over."""
    placeholders = {
        "min": "3",
        "max": "49",
        "ieee": LOCK_IEEE,
        "ieees": f"{LOCK_IEEE}, {SECOND_LOCK_IEEE}",
        "status": "1",
        "slot": "5",
    }
    await _setup_lock(hass, LOCK_IEEE)
    for language in LANGUAGES:
        translations = await async_get_translations(hass, language, "exceptions", [DOMAIN])
        prefix = f"component.{DOMAIN}.exceptions."
        keys = {k for k in translations if k.startswith(prefix)}
        assert keys, language
        for key in keys:
            assert "{" not in translations[key].format(**placeholders), (language, key)
