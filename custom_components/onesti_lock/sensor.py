"""Sensors for Onesti Lock: slot status and activity."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from .const import NUM_USER_SLOTS
from .coordinator import OnestiConfigEntry, OnestiCoordinator
from .entity import OnestiEntity
from .localize import format_activity

_LOGGER = logging.getLogger(__name__)

# Zero means no limit. The sensors are push-based and have no actions, so
# there is nothing for HA to throttle.
PARALLEL_UPDATES = 0

# The keys update_activity writes. Restored data is filtered to these, so
# whatever an older or hand-edited restore cache holds never becomes an
# attribute.
_ACTIVITY_KEYS = ("user_name", "user_slot", "action", "source", "timestamp")

# The three numbers the lock reports about itself, as (unique_id key,
# translation key, key in coordinator.lock_capabilities). They describe
# the lock, not any one event, so each gets its own diagnostic sensor.
_CAPABILITY_SENSORS = (
    ("pin-users", "pin_users", "num_pin_users"),
    ("pin-length-min", "pin_length_min", "min_pin_length"),
    ("pin-length-max", "pin_length_max", "max_pin_length"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnestiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Onesti Lock sensors."""
    coordinator = entry.runtime_data

    # The row starts at the first user slot, which follows the per-lock
    # reserved_slots option. Changing the option reloads the entry, and
    # this runs again with the new range.
    first = coordinator.first_user_slot()
    slots = range(first, first + NUM_USER_SLOTS)

    entities: list[SensorEntity] = [OnestiSlotSensor(coordinator, entry, slot) for slot in slots]
    entities.append(OnestiActivitySensor(coordinator, entry))
    entities.extend(
        OnestiCapabilitySensor(coordinator, entry, key, translation_key, capability)
        for key, translation_key, capability in _CAPABILITY_SENSORS
    )
    async_add_entities(entities)

    _remove_orphaned_slot_sensors(hass, entry, slots)


def _remove_orphaned_slot_sensors(
    hass: HomeAssistant, entry: OnestiConfigEntry, slots: range
) -> None:
    """Drop registry entries for slot sensors that fell out of the row.

    When reserved_slots moves, the row shifts: with 3 reserved it is 3-12,
    with 1 it is 1-10. The entities for slots no longer in the row would
    otherwise stay in the registry as unavailable forever. Each slot keeps
    its own unique_id, so a slot that is in both rows keeps its entity id
    and whatever the user customised on it.
    """
    registry = er.async_get(hass)
    # The same prefix OnestiEntity builds its unique ids from.
    prefix = f"{entry.entry_id}-slot-"
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = registry_entry.unique_id
        if registry_entry.domain != "sensor" or not unique_id.startswith(prefix):
            continue
        suffix = unique_id.removeprefix(prefix)
        if suffix.isdigit() and int(suffix) in slots:
            continue
        registry.async_remove(registry_entry.entity_id)


class OnestiSlotSensor(OnestiEntity, SensorEntity):
    """Sensor showing who occupies a lock slot."""

    def __init__(self, coordinator: OnestiCoordinator, entry: OnestiConfigEntry, slot: int) -> None:
        super().__init__(coordinator, f"slot-{slot}")
        self._slot = slot
        self._attr_translation_key = "slot"
        self._attr_translation_placeholders = {"slot": str(slot)}
        # Never set _attr_name here. HA checks it before the translation
        # key, so setting it as a fallback silently disables translated
        # entity names. Verified on a running instance: the activity
        # sensor showed the English _attr_name on a Norwegian server.

    @property
    def native_value(self) -> str:
        slot_data = self._coordinator.get_slot(self._slot)
        return slot_data.get("name") or self._coordinator.strings.get("slot_vacant", "Vacant")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slot_data = self._coordinator.get_slot(self._slot)
        return {
            "slot_id": self._slot,
            "has_pin": slot_data.get("has_pin", False),
        }

    async def async_added_to_hass(self) -> None:
        self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.remove_listener(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class OnestiCapabilitySensor(OnestiEntity, SensorEntity):
    """One number the lock reports about itself.

    Off by default: these are the same for every lock of a model and do
    not change once read, so they are worth having only when a PIN is
    refused and the limits need checking. No state class, since a
    capacity is not a measurement, and no stored data, since the answer
    already lives in the config entry options.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: OnestiCoordinator,
        entry: OnestiConfigEntry,
        key: str,
        translation_key: str,
        capability: str,
    ) -> None:
        super().__init__(coordinator, key)
        self._capability = capability
        self._attr_translation_key = translation_key

    @property
    def native_value(self) -> int | None:
        """The reported number, or None until the lock has answered."""
        value = self._coordinator.lock_capabilities.get(self._capability)
        return value if isinstance(value, int) else None


@dataclass
class ActivityExtraStoredData(ExtraStoredData):
    """The last activity, kept across restarts by the restore cache.

    Only the raw fields are stored, never the rendered state. native_value
    is built from them and the current strings on every write, so the
    sensor also comes back right after the server language changes.
    """

    activity: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.activity)

    @classmethod
    def from_dict(cls, restored: Mapping[str, Any]) -> ActivityExtraStoredData | None:
        """The stored activity, or None when it cannot be one."""
        activity = {key: restored.get(key) for key in _ACTIVITY_KEYS}
        if not isinstance(activity["action"], str) or not isinstance(activity["source"], str):
            return None
        return cls(activity)


class OnestiActivitySensor(OnestiEntity, SensorEntity, RestoreEntity):
    """Sensor showing last lock activity with user name."""

    def __init__(self, coordinator: OnestiCoordinator, entry: OnestiConfigEntry) -> None:
        super().__init__(coordinator, "activity")
        self._attr_translation_key = "last_activity"
        self._activity: dict[str, Any] = {}

    @property
    def native_value(self) -> str | None:
        if not self._activity:
            return None
        strings = self._coordinator.strings
        name = self._activity.get("user_name") or strings.get("unknown_user", "Unknown")
        return format_activity(
            strings,
            self._activity.get("action", "unknown"),
            self._activity.get("source", "unknown"),
            name,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Only the event. What the lock reports about itself has its own
        # diagnostic sensors, since it never changes with an event.
        return dict(self._activity) if self._activity else {}

    @property
    def extra_restore_state_data(self) -> ActivityExtraStoredData | None:
        if not self._activity:
            return None
        return ActivityExtraStoredData(self._activity)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (extra := await self.async_get_last_extra_data()) is not None:
            restored = ActivityExtraStoredData.from_dict(extra.as_dict())
            if restored is not None:
                self._activity = restored.activity
        self._coordinator.set_activity_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        # The event listener lives until the entry unloads, which is after
        # the platform removed its entities. Without this, a lock event in
        # between would write state for an entity that is gone.
        self._coordinator.set_activity_sensor(None)
        await super().async_will_remove_from_hass()

    def update_activity(
        self,
        user_slot: int | None,
        action: str,
        source: str,
    ) -> None:
        """Called by coordinator when lock activity occurs."""
        user_name = None
        if user_slot is not None:
            user_name = self._coordinator.get_slot_name(user_slot)

        self._activity = {
            "user_name": user_name,
            "user_slot": user_slot,
            "action": action,
            "source": source,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        self.async_write_ha_state()
