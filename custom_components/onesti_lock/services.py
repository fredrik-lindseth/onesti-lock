"""Services for Onesti Lock — PIN code management."""
from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, MAX_SLOTS, SLOT_FIRST_USER

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
    if ieee:
        raise HomeAssistantError(
            f"No Onesti lock found with IEEE {ieee}",
            translation_domain=DOMAIN,
            translation_key="lock_not_found_ieee",
            translation_placeholders={"ieee": ieee},
        )
    raise HomeAssistantError(
        "No Onesti lock found",
        translation_domain=DOMAIN,
        translation_key="lock_not_found",
    )


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Onesti Lock services."""

    async def handle_set_pin(call: ServiceCall) -> None:
        slot = call.data["slot"]
        name = call.data["name"]
        code = call.data["code"]
        ieee = call.data.get("ieee")

        # The coordinator is looked up before validation because the slot
        # ceiling depends on the PIN capacity this particular lock reported.
        coordinator = _get_coordinator(hass, ieee)
        max_slot = coordinator.max_user_slot()
        if not SLOT_FIRST_USER <= slot <= max_slot:
            raise HomeAssistantError(
                f"Slot must be between {SLOT_FIRST_USER} and {max_slot}",
                translation_domain=DOMAIN,
                translation_key="invalid_slot",
                # HA rejects non-string placeholder values.
                translation_placeholders={
                    "min": str(SLOT_FIRST_USER),
                    "max": str(max_slot),
                },
            )
        if not code.isdigit() or len(code) < 4 or len(code) > 8:
            raise HomeAssistantError(
                "PIN code must be 4-8 digits",
                translation_domain=DOMAIN,
                translation_key="invalid_pin",
            )

        success = await coordinator.set_pin(slot, name, code)
        if not success:
            raise HomeAssistantError(
                "Could not reach the lock. Press a button on the lock to wake it "
                "and try again.",
                translation_domain=DOMAIN,
                translation_key="lock_unreachable",
            )

    async def handle_clear_pin(call: ServiceCall) -> None:
        slot = call.data["slot"]
        ieee = call.data.get("ieee")

        if not SLOT_FIRST_USER <= slot < MAX_SLOTS:
            raise HomeAssistantError(
                f"Slot must be between {SLOT_FIRST_USER} and {MAX_SLOTS - 1}",
                translation_domain=DOMAIN,
                translation_key="invalid_slot",
                # HA rejects non-string placeholder values.
                translation_placeholders={
                    "min": str(SLOT_FIRST_USER),
                    "max": str(MAX_SLOTS - 1),
                },
            )

        coordinator = _get_coordinator(hass, ieee)
        success = await coordinator.clear_pin(slot)
        if not success:
            raise HomeAssistantError(
                "Could not reach the lock. Press a button on the lock to wake it "
                "and try again.",
                translation_domain=DOMAIN,
                translation_key="lock_unreachable",
            )

    async def handle_set_name(call: ServiceCall) -> None:
        slot = call.data["slot"]
        name = call.data["name"]
        ieee = call.data.get("ieee")

        if not SLOT_FIRST_USER <= slot < MAX_SLOTS:
            raise HomeAssistantError(
                f"Slot must be between {SLOT_FIRST_USER} and {MAX_SLOTS - 1}",
                translation_domain=DOMAIN,
                translation_key="invalid_slot",
                # HA rejects non-string placeholder values.
                translation_placeholders={
                    "min": str(SLOT_FIRST_USER),
                    "max": str(MAX_SLOTS - 1),
                },
            )

        coordinator = _get_coordinator(hass, ieee)
        await coordinator.set_slot_name(slot, name)

    async def handle_clear_slot(call: ServiceCall) -> None:
        slot = call.data["slot"]
        ieee = call.data.get("ieee")

        if not SLOT_FIRST_USER <= slot < MAX_SLOTS:
            raise HomeAssistantError(
                f"Slot must be between {SLOT_FIRST_USER} and {MAX_SLOTS - 1}",
                translation_domain=DOMAIN,
                translation_key="invalid_slot",
                # HA rejects non-string placeholder values.
                translation_placeholders={
                    "min": str(SLOT_FIRST_USER),
                    "max": str(MAX_SLOTS - 1),
                },
            )

        coordinator = _get_coordinator(hass, ieee)
        success = await coordinator.clear_slot(slot)
        if not success:
            raise HomeAssistantError(
                "Could not reach the lock. Press a button on the lock to wake it "
                "and try again.",
                translation_domain=DOMAIN,
                translation_key="lock_unreachable",
            )

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
    """Remove Onesti Lock services."""
    for service in ("set_pin", "clear_pin", "set_name", "clear_slot"):
        hass.services.async_remove(DOMAIN, service)
