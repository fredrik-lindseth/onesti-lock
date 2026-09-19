"""Which lock a service call reaches, against a real Home Assistant.

tests/test_service_lookup.py covers the same rules under stubs. Here the
device ids come from Home Assistant's own device registry, filled by the
sensor platform, and the calls go through the real service layer with its
schema validation and translated errors. Each lock gets a recording
transport, so a test can see which lock a command went to without leaning
on how zha.py reaches ZHA.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onesti_lock.const import CONF_IEEE, DOMAIN
from custom_components.onesti_lock.zha import SEND_DELIVERED, SendOutcome
from tests_ha.conftest import LOCK_IEEE, make_lock_proxy

SECOND_LOCK_IEEE = "00:0d:6f:00:55:66:77:88"
SET_PIN_COMMAND = 0x0005


class RecordingTransport:
    """Stands in for ZhaLockTransport: every command reaches the lock."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, dict]] = []

    async def send(self, command_id: int, params: dict) -> SendOutcome:
        self.sent.append((command_id, params))
        return SEND_DELIVERED


async def _setup_lock(
    hass: HomeAssistant, ieee: str, options: dict | None = None
) -> tuple[MockConfigEntry, RecordingTransport]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=ieee,
        title=f"Onesti Lock ({ieee[-11:]})",
        data={CONF_IEEE: ieee},
        options={"slots": {}, **(options or {})},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    transport = RecordingTransport()
    entry.runtime_data.transport = transport
    return entry, transport


@pytest.fixture
async def two_locks(hass: HomeAssistant, mock_zha):
    mock_zha.device_proxies[SECOND_LOCK_IEEE] = make_lock_proxy()
    front = await _setup_lock(hass, LOCK_IEEE)
    back = await _setup_lock(hass, SECOND_LOCK_IEEE)
    return front, back


def _device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """The lock's device, as the device selector in services.yaml offers it.

    Looked up by config entry: async_get_device(identifiers=...) raises a
    deprecation error in the current target, and this works in both.
    """
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [device.identifiers for device in devices] == [{(DOMAIN, entry.data[CONF_IEEE])}]
    return devices[0].id


async def _set_name(hass: HomeAssistant, **target: str) -> None:
    await hass.services.async_call(
        DOMAIN, "set_name", {"slot": 5, "name": "Kari", **target}, blocking=True
    )


def _named(entry: MockConfigEntry) -> bool:
    return entry.options["slots"].get("5", {}).get("name") == "Kari"


async def test_two_locks_without_a_target_are_refused(hass: HomeAssistant, two_locks) -> None:
    (front, front_transport), (back, back_transport) = two_locks

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN, "set_pin", {"slot": 5, "name": "Kari", "code": "1234"}, blocking=True
        )

    assert excinfo.value.translation_key == "multiple_locks"
    assert excinfo.value.translation_placeholders == {"ieees": f"{LOCK_IEEE}, {SECOND_LOCK_IEEE}"}
    assert front_transport.sent == back_transport.sent == []
    assert not _named(front) and not _named(back)


async def test_the_refusal_names_both_locks(hass: HomeAssistant, two_locks) -> None:
    """The ieees placeholder is filled in the message a user sees."""
    with pytest.raises(ServiceValidationError) as excinfo:
        await _set_name(hass)

    assert LOCK_IEEE in str(excinfo.value)
    assert SECOND_LOCK_IEEE in str(excinfo.value)


async def test_device_id_picks_the_lock(hass: HomeAssistant, two_locks) -> None:
    (front, front_transport), (back, back_transport) = two_locks

    await hass.services.async_call(
        DOMAIN,
        "set_pin",
        {"slot": 5, "name": "Kari", "code": "1234", "device_id": _device_id(hass, back)},
        blocking=True,
    )

    assert front_transport.sent == []
    assert [command for command, _ in back_transport.sent] == [SET_PIN_COMMAND]
    assert _named(back) and not _named(front)


async def test_device_id_wins_over_ieee(hass: HomeAssistant, two_locks) -> None:
    (front, _), (back, _) = two_locks

    await _set_name(hass, device_id=_device_id(hass, back), ieee=LOCK_IEEE)

    assert _named(back) and not _named(front)


async def test_ieee_in_another_case_picks_the_lock(hass: HomeAssistant, two_locks) -> None:
    (front, _), (back, _) = two_locks

    await _set_name(hass, ieee=SECOND_LOCK_IEEE.upper())

    assert _named(back) and not _named(front)


async def test_a_device_from_another_integration_is_refused(hass: HomeAssistant, two_locks) -> None:
    """A ZHA device with the same IEEE is still not one of ours."""
    (front, _), (back, _) = two_locks
    zha_entry = MockConfigEntry(domain="zha")
    zha_entry.add_to_hass(hass)
    zha_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        identifiers={("zha", LOCK_IEEE)},
        connections={(dr.CONNECTION_ZIGBEE, LOCK_IEEE)},
    )

    with pytest.raises(ServiceValidationError) as excinfo:
        await _set_name(hass, device_id=zha_device.id)

    assert excinfo.value.translation_key == "lock_not_found"
    assert not _named(front) and not _named(back)


async def test_unknown_ieee_is_refused(hass: HomeAssistant, two_locks) -> None:
    with pytest.raises(ServiceValidationError) as excinfo:
        await _set_name(hass, ieee="00:00:00:00:00:00:00:01")

    assert excinfo.value.translation_key == "lock_not_found_ieee"


async def test_one_lock_needs_no_target(hass: HomeAssistant, mock_zha) -> None:
    entry, _ = await _setup_lock(hass, LOCK_IEEE)

    await _set_name(hass)

    assert _named(entry)


async def test_invalid_pin_names_the_lock_s_range(hass: HomeAssistant, mock_zha) -> None:
    """The translated message is filled in from the min and max placeholders.

    The fake lock reports 4-8 (conftest), which is also the fallback, so
    this holds whether or not the capabilities were read in time.
    """
    entry, transport = await _setup_lock(hass, LOCK_IEEE)

    with pytest.raises(ServiceValidationError) as excinfo:
        await hass.services.async_call(
            DOMAIN, "set_pin", {"slot": 5, "name": "Kari", "code": "123"}, blocking=True
        )

    assert excinfo.value.translation_key == "invalid_pin"
    assert excinfo.value.translation_placeholders == {"min": "4", "max": "8"}
    assert "4-8" in str(excinfo.value)
    assert transport.sent == []


@pytest.mark.parametrize(
    ("language", "set_pin_name"), [("en", "Set PIN code"), ("nb", "Sett PIN-kode")]
)
async def test_action_names_and_fields_come_from_the_translations(
    hass: HomeAssistant, mock_zha, language: str, set_pin_name: str
) -> None:
    """services.yaml holds no text, so the action dialog reads the translations.

    Every name and description was English in services.yaml before. They now
    live in strings.json and translations/*.json, and this is what proves
    Home Assistant finds them there for a custom integration.
    """
    await _setup_lock(hass, LOCK_IEEE)

    translations = await async_get_translations(hass, language, "services", {DOMAIN})

    prefix = f"component.{DOMAIN}.services"
    assert translations[f"{prefix}.set_pin.name"] == set_pin_name
    for action in ("set_pin", "clear_pin", "set_name", "clear_slot"):
        assert translations[f"{prefix}.{action}.description"].strip()
    for field in ("slot", "name", "code", "device_id", "ieee"):
        assert translations[f"{prefix}.set_pin.fields.{field}.name"].strip()
        assert translations[f"{prefix}.set_pin.fields.{field}.description"].strip()
