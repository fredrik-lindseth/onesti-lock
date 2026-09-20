"""Services for Onesti Lock: PIN code management."""
from __future__ import annotations

import logging
from collections.abc import Awaitable

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from . import pin_rules
from .const import DOMAIN, MAX_SLOTS
from .coordinator import NimlyCoordinator
from .redact import redact_digits
from .zha import Delivery, SendOutcome

_LOGGER = logging.getLogger(__name__)

ATTR_DEVICE_ID = "device_id"
ATTR_IEEE = "ieee"


# Errors in the call itself (a slot out of range, a bad PIN, a lock that is
# not there) are ServiceValidationError, which Home Assistant shows to the
# user without logging a traceback. Errors from reaching the lock stay
# HomeAssistantError: the call was fine, the lock or the radio was not.


def _lock_not_found() -> ServiceValidationError:
    return ServiceValidationError(
        "No Onesti lock found",
        translation_domain=DOMAIN,
        translation_key="lock_not_found",
    )


def _lock_not_found_ieee(ieee: str) -> ServiceValidationError:
    return ServiceValidationError(
        f"No Onesti lock found with IEEE {ieee}",
        translation_domain=DOMAIN,
        translation_key="lock_not_found_ieee",
        translation_placeholders={"ieee": ieee},
    )


def _invalid_slot(low: int, high: int) -> ServiceValidationError:
    return ServiceValidationError(
        f"Slot must be between {low} and {high}",
        translation_domain=DOMAIN,
        translation_key="invalid_slot",
        # HA rejects non-string placeholder values.
        translation_placeholders={"min": str(low), "max": str(high)},
    )


def _not_delivered(outcome: SendOutcome) -> HomeAssistantError:
    """The error for a write the lock did not take, by what became of it."""
    if outcome.delivery is Delivery.UNREACHED:
        return HomeAssistantError(
            "Could not reach the lock. Press a button on the lock to wake it "
            "and try again.",
            translation_domain=DOMAIN,
            translation_key="lock_unreachable",
        )
    return HomeAssistantError(
        f"The lock refused the command (status {outcome.status_text})",
        translation_domain=DOMAIN,
        translation_key=outcome.error_key,
        # Every rejection text may name the status, so it is always given.
        translation_placeholders={"status": outcome.status_text},
    )


async def _write(action: str, slot: int, write: Awaitable[SendOutcome]) -> None:
    """Await a coordinator write and turn its outcome into what the caller sees.

    The transport never raises by contract. Should it anyway, the original
    exception must not reach the caller: HA puts it in the log and the
    automation trace, and a ValueError from ZHA quotes the command params,
    PIN included. It is logged redacted, without traceback, and replaced by
    an error that carries no reference to it (raised outside the except
    block, so not even as __context__).
    """
    failure: str | None = None
    try:
        outcome = await write
    except Exception as err:
        failure = f"{type(err).__name__}: {redact_digits(err)}"
    if failure is not None:
        _LOGGER.error("Unexpected error %s on slot %s: %s", action, slot, failure)
        raise HomeAssistantError(
            f"Unexpected error {action} on slot {slot}, see the log",
            translation_domain=DOMAIN,
            translation_key="write_failed",
            translation_placeholders={"slot": str(slot)},
        )
    if not outcome.delivered:
        raise _not_delivered(outcome)


def _find_by_ieee(coordinators: list[NimlyCoordinator], ieee: str) -> NimlyCoordinator | None:
    # ZHA shows IEEE addresses in lower case, but people paste them from
    # anywhere, so the match ignores case.
    wanted = ieee.lower()
    return next((c for c in coordinators if c.ieee.lower() == wanted), None)


def _entry_id_for_device(hass: HomeAssistant, device_id: str) -> str:
    """The config entry behind one of this integration's own devices.

    entity.py registers each lock's device with the identifier
    (DOMAIN, entry_id). A device id that is unknown, or that belongs to
    some other integration alone (the ZHA device of a lock that is not set
    up here included), is not an Onesti lock as far as the services are
    concerned.
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for domain, identifier in device.identifiers:
            if domain == DOMAIN:
                return identifier
    raise _lock_not_found()


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> NimlyCoordinator:
    """The lock a service call targets.

    device_id wins over ieee when both are given. Without either, the call
    only goes through when exactly one lock is loaded: with two or more,
    guessing would program a code into the wrong door.

    Only loaded entries count. A lock whose entry is still setting up or
    retrying has no working transport yet, so it is reported as not found
    rather than handed a command that cannot reach it.
    """
    coordinators: list[NimlyCoordinator] = [
        entry.runtime_data for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    ]

    device_id = call.data.get(ATTR_DEVICE_ID)
    ieee = call.data.get(ATTR_IEEE)
    if device_id:
        entry_id = _entry_id_for_device(hass, device_id)
        coordinator = next((c for c in coordinators if c.entry.entry_id == entry_id), None)
        if coordinator is None:
            # The device is ours, but its entry is not loaded.
            raise _lock_not_found()
        return coordinator
    if ieee:
        coordinator = _find_by_ieee(coordinators, ieee)
        if coordinator is None:
            raise _lock_not_found_ieee(ieee)
        return coordinator

    if not coordinators:
        raise _lock_not_found()
    if len(coordinators) > 1:
        ieees = ", ".join(sorted(c.ieee for c in coordinators))
        raise ServiceValidationError(
            f"More than one Onesti lock is set up ({ieees}). Pick the lock "
            "with device_id or ieee.",
            translation_domain=DOMAIN,
            translation_key="multiple_locks",
            translation_placeholders={"ieees": ieees},
        )
    return coordinators[0]


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Onesti Lock services, once, when the integration is set up.

    They stay registered for the life of Home Assistant, as Home Assistant
    recommends, and look the lock up per call. Registering them per entry
    and removing them with the last one raced: while one lock was unloaded
    and another was still setting up, neither counted as loaded, so the
    services went away under the lock that was about to arrive.
    """

    async def handle_set_pin(call: ServiceCall) -> None:
        slot = call.data["slot"]
        name = call.data["name"]
        code = call.data["code"]

        # The coordinator is looked up before validation because both bounds
        # are per lock: the floor is its reserved-slots setting, the ceiling
        # the PIN capacity it reported.
        coordinator = _get_coordinator(hass, call)
        first = coordinator.first_user_slot()
        max_slot = coordinator.max_user_slot()
        if not first <= slot <= max_slot:
            raise _invalid_slot(first, max_slot)
        if not pin_rules.is_valid_pin(code, coordinator.lock_capabilities):
            low, high = pin_rules.pin_length_range(coordinator.lock_capabilities)
            # The message leaves the code out: exceptions reach the log and
            # automation traces.
            raise ServiceValidationError(
                f"PIN code must be {low}-{high} digits",
                translation_domain=DOMAIN,
                translation_key="invalid_pin",
                translation_placeholders={"min": str(low), "max": str(high)},
            )

        await _write("setting PIN", slot, coordinator.set_pin(slot, name, code))

    async def handle_clear_pin(call: ServiceCall) -> None:
        slot = call.data["slot"]

        # Looked up first: the reserved master slots are a per-lock setting.
        coordinator = _get_coordinator(hass, call)
        first = coordinator.first_user_slot()
        if not first <= slot < MAX_SLOTS:
            raise _invalid_slot(first, MAX_SLOTS - 1)

        await _write("clearing PIN", slot, coordinator.clear_pin(slot))

    async def handle_set_name(call: ServiceCall) -> None:
        slot = call.data["slot"]
        name = call.data["name"]

        # Names are the integration's own data and never reach the lock, so
        # every slot can be named, master slots included (issue #6).
        if not 0 <= slot < MAX_SLOTS:
            raise _invalid_slot(0, MAX_SLOTS - 1)

        coordinator = _get_coordinator(hass, call)
        await coordinator.set_slot_name(slot, name)

    async def handle_clear_slot(call: ServiceCall) -> None:
        slot = call.data["slot"]

        # Looked up first: the reserved master slots are a per-lock setting.
        coordinator = _get_coordinator(hass, call)
        first = coordinator.first_user_slot()
        if not first <= slot < MAX_SLOTS:
            raise _invalid_slot(first, MAX_SLOTS - 1)

        await _write("clearing slot", slot, coordinator.clear_slot(slot))

    hass.services.async_register(
        DOMAIN,
        "set_pin",
        handle_set_pin,
        schema=vol.Schema(
            {
                vol.Required("slot"): vol.Coerce(int),
                vol.Required("name"): cv.string,
                vol.Required("code"): cv.string,
                vol.Optional(ATTR_DEVICE_ID): cv.string,
                vol.Optional(ATTR_IEEE): cv.string,
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
                vol.Optional(ATTR_DEVICE_ID): cv.string,
                vol.Optional(ATTR_IEEE): cv.string,
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
                vol.Optional(ATTR_DEVICE_ID): cv.string,
                vol.Optional(ATTR_IEEE): cv.string,
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
                vol.Optional(ATTR_DEVICE_ID): cv.string,
                vol.Optional(ATTR_IEEE): cv.string,
            }
        ),
    )

