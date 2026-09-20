"""Base class for the entities Onesti Lock creates."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import NimlyCoordinator


class NimlyEntity(Entity):
    """An entity on the Onesti Lock device of one lock.

    Every unique_id is the lock's IEEE followed by a per-entity key, and
    the entity registry holds users' entities by it, so the format must
    not change. Never set _attr_name here or in a subclass: HA checks it
    before the translation key, which silently disables translated names.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: NimlyCoordinator, key: str) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.ieee}-{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.ieee)},
            name="Onesti Lock",
            manufacturer="Onesti Products AS",
        )

    @property
    def available(self) -> bool:
        """Follows the coordinator, which follows the event listener.

        Unavailable means lock events cannot reach Home Assistant, so
        nothing shown here is being kept up to date. A lock that is merely
        asleep is available: see NimlyCoordinator.available.
        """
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        """Follow the coordinator, for availability at least.

        A subclass that registers its own listener (the slot sensors do,
        for slot data) may skip this; one that calls super() gets the
        availability updates through it.
        """
        await super().async_added_to_hass()
        self._coordinator.add_listener(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.remove_listener(self._handle_coordinator_update)
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
