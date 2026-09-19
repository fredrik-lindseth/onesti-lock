"""Base class for the entities Onesti Lock creates."""
from __future__ import annotations

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
