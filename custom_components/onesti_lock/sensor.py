"""Sensors for Onesti Lock — slot status and activity."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUM_USER_SLOTS, SLOT_FIRST_USER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Onesti Lock sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SensorEntity] = []

    # Slot sensors (user slots start at 3)
    for i in range(NUM_USER_SLOTS):
        slot = SLOT_FIRST_USER + i
        entities.append(NimlySlotSensor(coordinator, entry, slot))

    # Activity sensor
    entities.append(NimlyActivitySensor(coordinator, entry))

    async_add_entities(entities)


class NimlySlotSensor(SensorEntity):
    """Sensor showing who occupies a lock slot."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:key-variant"

    def __init__(self, coordinator, entry: ConfigEntry, slot: int) -> None:
        self._coordinator = coordinator
        self._slot = slot
        self._attr_unique_id = f"{coordinator.ieee}-slot-{slot}"
        self._attr_translation_key = f"slot_{slot}"

    @property
    def name(self) -> str:
        return f"Slot {self._slot}"

    @property
    def native_value(self) -> str:
        slot_data = self._coordinator.get_slot(self._slot)
        return slot_data.get("name") or "Ledig"

    @property
    def extra_state_attributes(self) -> dict:
        slot_data = self._coordinator.get_slot(self._slot)
        return {
            "slot_id": self._slot,
            "has_pin": slot_data.get("has_pin", False),
            "has_rfid": slot_data.get("has_rfid", False),
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._coordinator.ieee)},
            "name": "Onesti Lock",
            "manufacturer": "Onesti Products AS",
        }

    async def async_added_to_hass(self) -> None:
        self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.remove_listener(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class NimlyActivitySensor(SensorEntity):
    """Sensor showing last lock activity with user name."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-closed-lock"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.ieee}-activity"
        self._attr_translation_key = "last_activity"
        self._activity: dict = {}

    @property
    def name(self) -> str:
        return "Siste aktivitet"

    @property
    def native_value(self) -> str | None:
        if not self._activity:
            return None
        name = self._activity.get("user_name", "Ukjent")
        action = self._activity.get("action", "unknown")
        source = self._activity.get("source", "")

        if action == "unlock":
            verb = "låste opp"
        elif action == "lock":
            verb = "låste"
        else:
            verb = action

        if source == "keypad":
            return f"{name} {verb} med kode"
        elif source == "fingerprint":
            return f"{name} {verb} med fingeravtrykk"
        elif source == "rfid":
            return f"{name} {verb} med RFID"
        elif source == "zigbee":
            return f"{verb.capitalize()} via Zigbee"
        elif source == "auto":
            return "Auto-lås"
        else:
            return f"{name} {verb}"

    @property
    def extra_state_attributes(self) -> dict:
        return dict(self._activity) if self._activity else {}

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._coordinator.ieee)},
            "name": "Onesti Lock",
            "manufacturer": "Onesti Products AS",
        }

    async def async_added_to_hass(self) -> None:
        self._coordinator.set_activity_sensor(self)

    def update_activity(
        self,
        user_slot: int | None,
        action: str,
        source: str,
    ) -> None:
        """Called by coordinator when lock activity occurs."""
        user_name = "Ukjent"
        if user_slot is not None:
            user_name = self._coordinator.get_slot_name(user_slot)

        self._activity = {
            "user_name": user_name,
            "user_slot": user_slot,
            "action": action,
            "source": source,
            "timestamp": datetime.now().isoformat(),
        }
        self.async_write_ha_state()
