"""Coordinator for Onesti Lock: slot data and PIN operations."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import pin_rules
from .const import CONF_IEEE, DEFAULT_SLOT
from .zha import SendOutcome, ZhaLockTransport

_LOGGER = logging.getLogger(__name__)

# Options key for what the lock reported about itself. Present only once the
# lock has answered, so its presence is what marks the read as done.
OPTION_CAPABILITIES = "capabilities"

# IEEEs whose loss of lock events has been logged, so the loss is logged
# once and the return once. It lives on the module rather than on the
# coordinator because ZHA coming back reloads the entry: the coordinator
# that logged the loss is gone by the time the one that takes over can
# report the return.
_LOSS_LOGGED: set[str] = set()


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
        # Tests inject a fake with the same methods.
        self.transport = transport or ZhaLockTransport(hass, self.ieee)
        self._slots: dict[str, dict[str, Any]] = {}
        self._listeners: list = []
        self._activity_sensor = None
        # One PIN operation at a time per lock. The options flow and the
        # services can both write, and interleaved sends and saves would let
        # local state end up describing the older of two writes.
        self._pin_lock = asyncio.Lock()
        # Serialises capability reads, so a refresh asked for while one is in
        # flight waits for it and then finds the answer already stored.
        self._capabilities_lock = asyncio.Lock()
        stored_capabilities = self.entry.options.get(OPTION_CAPABILITIES)
        self.capabilities_final = isinstance(stored_capabilities, Mapping)
        self.lock_capabilities: dict[str, Any] = (
            dict(stored_capabilities) if self.capabilities_final else {}
        )
        # Populated from async_setup_entry: reading the translation files is
        # blocking IO and this constructor runs on the event loop.
        self.strings: Mapping[str, str] = {}
        # The first user slot this setup was built for. The sensor rows
        # follow it, so only a change to it is worth a reload (see the update
        # listener in __init__.py); slot and capability writes are not.
        self.setup_first_user_slot = self.first_user_slot()
        # The zigpy cluster the event listener is registered on, or None.
        # A ZHA reload replaces it, which __init__.py watches for.
        self._listened_cluster: Any = None
        # No listener yet, so no lock event can arrive. The entities read
        # this through NimlyEntity.available.
        self._available = False
        self._load_slots()

    # -- Availability --

    @property
    def listened_cluster(self) -> Any:
        """The zigpy cluster the event listener sits on, or None."""
        return self._listened_cluster

    @listened_cluster.setter
    def listened_cluster(self, cluster: Any) -> None:
        """Record the cluster, and let availability follow it.

        events.py assigns this when it has registered the listener, which
        is the moment lock events start arriving.
        """
        self._listened_cluster = cluster
        self.set_available(cluster is not None)

    @property
    def available(self) -> bool:
        """Whether lock events can reach Home Assistant right now.

        True once the event listener is registered on a cluster, false
        while ZHA is not running or its internals were missing. A sleeping
        lock stays available: the slot sensors show Home Assistant's own
        stored data and the activity sensor the last event it saw, and a
        command that times out on a sleeping radio says nothing about
        whether events arrive.
        """
        return self._available

    def set_available(self, available: bool) -> None:
        """Set whether lock events reach us, and tell the entities.

        Logs one INFO line when they stop and one when they are back, and
        never the same one twice in a row. The flag is per IEEE and not
        per coordinator, since ZHA coming back reloads the entry and the
        return is reported by a new coordinator.
        """
        changed = available is not self._available
        self._available = available
        if available:
            if self.ieee in _LOSS_LOGGED:
                _LOSS_LOGGED.discard(self.ieee)
                _LOGGER.info("Lock events for %s are arriving again, ZHA is running", self.ieee)
        elif self.ieee not in _LOSS_LOGGED:
            _LOSS_LOGGED.add(self.ieee)
            _LOGGER.info("Lock events for %s stopped, ZHA is not running", self.ieee)
        if changed:
            self._notify_listeners()

    def _load_slots(self) -> None:
        """Load slot data from config entry options.

        Only loads slots that have been used. No pre-allocation.
        get_slot() returns DEFAULT_SLOT for unknown slots.

        Called again right before every change, since the entry outlives the
        coordinator. An options-flow write keeps running through a reload
        (the dialog must not lose a code the lock already took), so the
        coordinator it started on can save after the reload built a new one.
        Without the re-read, that new coordinator's next save would write its
        own older view back over the change. Nothing suspends between the
        re-read and the save, so the two are one step on the event loop.
        """
        stored = self.entry.options.get("slots", {})
        # Only the keys DEFAULT_SLOT defines, so a field the schema dropped
        # (has_rfid) cannot come back from a hand-edited or older save.
        self._slots = {
            k: {**DEFAULT_SLOT, **{f: v[f] for f in DEFAULT_SLOT if f in v}}
            for k, v in stored.items()
        }

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
        # After a reload during a write, this is the coordinator the write
        # started on and the entry has another one. That one is what the
        # sensors read, so it takes the change over instead of showing the
        # slot as it was until something else writes.
        current = getattr(self.entry, "runtime_data", None)
        if isinstance(current, NimlyCoordinator) and current is not self:
            current.adopt_stored_slots()

    def adopt_stored_slots(self) -> None:
        """Take over slot data another coordinator on this entry just saved."""
        self._load_slots()
        self._notify_listeners()

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
        self._load_slots()
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

    def wake_echo_pending(self) -> bool:
        """Whether a Zigbee lock event now may be our own auto-wake's echo."""
        return self.transport.wake_echo_pending()

    # -- Lock capabilities --

    async def async_refresh_capabilities(self) -> None:
        """Read what the lock reports about itself, until it has answered once.

        The lock sleeps, so a read at startup usually goes unanswered. This
        runs again after every command that reached the lock and on every
        attribute report, when the radio is known to be awake. Once the lock
        has answered, even with nothing, the answer is stored in the entry
        options and every later call returns at once.
        """
        if self.capabilities_final:
            return
        async with self._capabilities_lock:
            if self.capabilities_final:
                return
            capabilities = await self.transport.read_capabilities()
            if capabilities is None:
                return
            self.lock_capabilities = dict(capabilities)
            self.capabilities_final = True
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={
                    **self.entry.options,
                    OPTION_CAPABILITIES: dict(capabilities),
                },
            )
            _LOGGER.debug("Lock %s reported capabilities %s", self.ieee, capabilities)
        # Outside the lock: the diagnostic sensors show these numbers and
        # have nothing to show until the lock has answered once.
        self._notify_listeners()

    def schedule_capability_refresh(self) -> None:
        """Run async_refresh_capabilities in the background, if still needed.

        Tied to the config entry, so an unload cancels a read in flight.
        """
        if self.capabilities_final:
            return
        self.entry.async_create_background_task(
            self.hass,
            self.async_refresh_capabilities(),
            f"onesti_lock capability refresh {self.ieee}",
        )

    # -- PIN operations --

    async def _send(self, command: int, params: dict) -> SendOutcome:
        """Send through the transport, then use the awake radio.

        A lock that answered, whether it accepted the command or refused
        it, has its radio awake right now, the one moment a capability read
        is likely to be answered.
        """
        outcome = await self.transport.send(command, params)
        if outcome.lock_answered:
            self.schedule_capability_refresh()
        return outcome

    # Each PIN operation returns the transport's outcome, and local state
    # changes only when it was delivered. A refusal leaves the slot as the
    # lock still has it.

    async def set_pin(self, slot: int, name: str, code: str) -> SendOutcome:
        """Set PIN code for a slot."""
        self._check_writable(slot)
        async with self._pin_lock:
            outcome = await self._send(
                0x0005,
                {
                    "user_id": slot,
                    "user_status": 1,  # Enabled
                    "user_type": 0,  # Unrestricted
                    "pin_code": code,
                },
            )
            if outcome.delivered:
                self._load_slots()
                slot_data = self._slots.setdefault(str(slot), {**DEFAULT_SLOT})
                slot_data["name"] = name
                slot_data["has_pin"] = True
                await self._save_slots()
                self._notify_listeners()
            return outcome

    async def clear_pin(self, slot: int) -> SendOutcome:
        """Clear PIN code for a slot."""
        self._check_writable(slot)
        async with self._pin_lock:
            outcome = await self._send(
                0x0007,
                {"user_id": slot},
            )
            if outcome.delivered:
                self._load_slots()
                self._slots.setdefault(str(slot), {**DEFAULT_SLOT})["has_pin"] = False
                await self._save_slots()
                self._notify_listeners()
            return outcome

    async def clear_slot(self, slot: int) -> SendOutcome:
        """Clear all credentials and name for a slot."""
        self._check_writable(slot)
        async with self._pin_lock:
            outcome = await self._send(
                0x0007,
                {"user_id": slot},
            )
            if outcome.delivered:
                # Local state only follows a command the lock took. Wiping
                # the slot after a failed or refused send would show it as
                # vacant while the lock still accepts the old code.
                self._load_slots()
                self._slots[str(slot)] = {**DEFAULT_SLOT}
                await self._save_slots()
                self._notify_listeners()
            return outcome

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
