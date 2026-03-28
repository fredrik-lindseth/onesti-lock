"""Services for Nimly PRO — PIN code management."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, NUM_SLOTS

_LOGGER = logging.getLogger(__name__)


def _get_coordinator(hass: HomeAssistant, ieee: str | None = None):
    """Get coordinator, optionally filtered by IEEE."""
    entries = hass.data.get(DOMAIN, {})
    for entry_data in entries.values():
        coordinator = entry_data.get("coordinator")
        if coordinator is None:
            continue
        if ieee is None or coordinator.ieee.lower() == ieee.lower():
            return coordinator
    raise HomeAssistantError(f"Nimly lock not found{f' for {ieee}' if ieee else ''}")


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Nimly PRO services."""

    async def handle_set_pin(call: ServiceCall) -> None:
        slot = call.data["slot"]
        name = call.data["name"]
        code = call.data["code"]
        ieee = call.data.get("ieee")

        if not 0 <= slot < NUM_SLOTS:
            raise HomeAssistantError(f"Slot must be 0-{NUM_SLOTS - 1}")
        if not code.isdigit() or len(code) < 4 or len(code) > 8:
            raise HomeAssistantError("PIN must be 4-8 digits")

        coordinator = _get_coordinator(hass, ieee)
        success = await coordinator.set_pin(slot, name, code)
        if not success:
            raise HomeAssistantError(
                "Kunne ikke nå låsen — trykk en knapp på låsen og prøv igjen"
            )

    async def handle_clear_pin(call: ServiceCall) -> None:
        slot = call.data["slot"]
        ieee = call.data.get("ieee")

        if not 0 <= slot < NUM_SLOTS:
            raise HomeAssistantError(f"Slot must be 0-{NUM_SLOTS - 1}")

        coordinator = _get_coordinator(hass, ieee)
        success = await coordinator.clear_pin(slot)
        if not success:
            raise HomeAssistantError(
                "Kunne ikke nå låsen — trykk en knapp på låsen og prøv igjen"
            )

    async def handle_set_name(call: ServiceCall) -> None:
        slot = call.data["slot"]
        name = call.data["name"]
        ieee = call.data.get("ieee")

        if not 0 <= slot < NUM_SLOTS:
            raise HomeAssistantError(f"Slot must be 0-{NUM_SLOTS - 1}")

        coordinator = _get_coordinator(hass, ieee)
        await coordinator.set_slot_name(slot, name)

    async def handle_clear_slot(call: ServiceCall) -> None:
        slot = call.data["slot"]
        ieee = call.data.get("ieee")

        if not 0 <= slot < NUM_SLOTS:
            raise HomeAssistantError(f"Slot must be 0-{NUM_SLOTS - 1}")

        coordinator = _get_coordinator(hass, ieee)
        await coordinator.clear_slot(slot)

    hass.services.async_register(
        DOMAIN,
        "set_pin",
        handle_set_pin,
        schema=vol.Schema(
            {
                vol.Required("slot"): vol.Coerce(int),
                vol.Required("name"): cv.string,
                vol.Required("code"): cv.string,
                vol.Optional("ieee"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "clear_pin",
        handle_clear_pin,
        schema=vol.Schema(
            {
                vol.Required("slot"): vol.Coerce(int),
                vol.Optional("ieee"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_name",
        handle_set_name,
        schema=vol.Schema(
            {
                vol.Required("slot"): vol.Coerce(int),
                vol.Required("name"): cv.string,
                vol.Optional("ieee"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "clear_slot",
        handle_clear_slot,
        schema=vol.Schema(
            {
                vol.Required("slot"): vol.Coerce(int),
                vol.Optional("ieee"): cv.string,
            }
        ),
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Remove Nimly PRO services."""
    for service in ("set_pin", "clear_pin", "set_name", "clear_slot"):
        hass.services.async_remove(DOMAIN, service)
