"""Coordinator for Onesti Lock: slot data and PIN operations."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import pin_rules
from .const import CONF_IEEE, DEFAULT_SLOT
from .zha import ZhaLockTransport


class NimlyCoordinator:
    """Manages slot data and PIN operations for one Nimly lock."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        transport: ZhaLockTransport | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.ieee: str = entry.data[CONF_IEEE]
        # Tests inject a fake with the same four methods.
        self.transport = transport or ZhaLockTransport(hass, self.ieee)
        self._slots: dict[str, dict[str, Any]] = {}
        self._listeners: list = []
        self._activity_sensor = None
        self.lock_capabilities: dict[str, Any] = {}
        # Populated from async_setup_entry: reading the translation files is
        # blocking IO and this constructor runs on the event loop.
        self.strings: Mapping[str, str] = {}
        self._load_slots()

    def _load_slots(self) -> None:
        """Load slot data from config entry options.

        Only loads slots that have been used. No pre-allocation.
        get_slot() returns DEFAULT_SLOT for unknown slots.
        """
        stored = self.entry.options.get("slots", {})
        self._slots = {k: {**DEFAULT_SLOT, **v} for k, v in stored.items()}

    async def _save_slots(self) -> None:
        """Persist slot data to config entry options.

        The slot dicts are copied because async_update_entry only writes to
        .storage when the new options compare unequal to entry.options.
        Handing HA the live _slots dict makes entry.options alias it, so
        every later in-place change compares equal and is never persisted.
        """
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={
                **self.entry.options,
                "slots": {k: dict(v) for k, v in self._slots.items()},
            },
        )

    # -- Slot data access --

    def get_slot(self, slot: int) -> dict[str, Any]:
        """Get a copy of the slot data.

        Always a copy, never the live inner dict: a caller mutating the
        return value would change _slots without going through _save_slots
        or notifying listeners, the same silent-aliasing class as the
        _save_slots persistence bug. Vacant slots already returned a fresh
        copy; this makes the contract symmetric.
        """
        return {**DEFAULT_SLOT, **self._slots.get(str(slot), {})}

    def get_slot_name(self, slot: int) -> str:
        """Get human-readable name for slot."""
        name = self._slots.get(str(slot), {}).get("name", "")
        if name:
            return name
        if slot == 0:
            # Slot 0 is the master code on every model, so an unnamed
            # master unlock reads "Master unlocked with code", not "Slot 0".
            # Slots 1-2 are only master on some models (issue #6).
            return self.strings.get("slot_fallback_master", "Master")
        return self.strings.get("slot_fallback_name", "Slot {slot}").format(slot=slot)

    def max_user_slot(self) -> int:
        """Highest slot set_pin should accept for this lock."""
        return pin_rules.max_user_slot(self.lock_capabilities)

    def first_user_slot(self) -> int:
        """Lowest slot PIN writes and clears may touch on this lock."""
        return pin_rules.first_user_slot(self.entry.options)

    def _check_writable(self, slot: int) -> None:
        """Refuse PIN writes and clears on reserved master slots.

        services.py and the options flow already stop these with a
        translated message. This is the last guard, so the rule holds for
        any future caller too: slot 0 is never written from Home Assistant.
        """
        first = self.first_user_slot()
        if slot < first:
            raise ValueError(
                f"Slot {slot} is a reserved master slot on this lock; "
                f"PIN writes and clears start at slot {first}"
            )

    async def set_slot_name(self, slot: int, name: str) -> None:
        """Set name for a slot (does not send ZCL command).

        An empty name removes the name. A slot left with no name and no
        credentials is dropped from storage rather than kept as a blank
        record.
        """
        key = str(slot)
        if name:
            self._slots.setdefault(key, {**DEFAULT_SLOT})["name"] = name
        elif key in self._slots:
            self._slots[key]["name"] = ""
            if self._slots[key] == DEFAULT_SLOT:
                del self._slots[key]
        else:
            return
        await self._save_slots()
        self._notify_listeners()

    # -- Activity sensor --

    def set_activity_sensor(self, sensor) -> None:
        """Register the activity sensor for updates."""
        self._activity_sensor = sensor

    def update_activity(self, user_slot, action, source) -> None:
        """Update the activity sensor."""
        if self._activity_sensor:
            self._activity_sensor.update_activity(user_slot, action, source)

    async def read_lock_capabilities(self) -> None:
        """Read static lock properties into lock_capabilities.

        Keeps whatever the lock reported (num_pin_users, max_pin_length,
        min_pin_length) and leaves the rest unset. The transport degrades
        silently when the lock is asleep or skips these attributes.
        """
        self.lock_capabilities.update(await self.transport.read_capabilities())

    # -- PIN operations --

    async def set_pin(self, slot: int, name: str, code: str) -> bool:
        """Set PIN code for a slot."""
        self._check_writable(slot)
        success = await self.transport.send(
            0x0005,
            {
                "user_id": slot,
                "user_status": 1,  # Enabled
                "user_type": 0,  # Unrestricted
                "pin_code": code,
            },
        )
        if success:
            slot_data = self._slots.setdefault(str(slot), {**DEFAULT_SLOT})
            slot_data["name"] = name
            slot_data["has_pin"] = True
            await self._save_slots()
            self._notify_listeners()
        return success

    async def clear_pin(self, slot: int) -> bool:
        """Clear PIN code for a slot."""
        self._check_writable(slot)
        success = await self.transport.send(
            0x0007,
            {"user_id": slot},
        )
        if success:
            self._slots.setdefault(str(slot), {**DEFAULT_SLOT})["has_pin"] = False
            await self._save_slots()
            self._notify_listeners()
        return success

    async def clear_slot(self, slot: int) -> bool:
        """Clear all credentials and name for a slot."""
        self._check_writable(slot)
        success = await self.transport.send(
            0x0007,
            {"user_id": slot},
        )
        if success:
            # Local state only follows a command that reached the lock.
            # Wiping the slot after a failed send would show it as vacant
            # while the lock still accepts the old code.
            self._slots[str(slot)] = {**DEFAULT_SLOT}
            await self._save_slots()
            self._notify_listeners()
        return success

    # -- Listener pattern for sensors --

    def add_listener(self, callback) -> None:
        """Register a callback for slot data changes."""
        self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        """Remove a callback."""
        self._listeners = [cb for cb in self._listeners if cb != callback]

    def _notify_listeners(self) -> None:
        """Notify all listeners of data change."""
        for callback in self._listeners:
            callback()


# The entry's runtime_data is its coordinator. HA drops runtime_data on
# unload, so nothing outlives the entry that owns it.
type NimlyConfigEntry = ConfigEntry[NimlyCoordinator]
