"""Coordinator for Nimly PRO — slot data and ZHA cluster access."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_IEEE,
    DEFAULT_SLOT,
    DOORLOCK_CLUSTER_ID,
    NUM_SLOTS,
    ZHA_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class NimlyCoordinator:
    """Manages slot data and ZHA communication for one Nimly lock."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.ieee: str = entry.data[CONF_IEEE]
        self._slots: dict[str, dict[str, Any]] = {}
        self._listeners: list = []
        self._activity_sensor = None
        self._load_slots()

    def _load_slots(self) -> None:
        """Load slot data from config entry options."""
        stored = self.entry.options.get("slots", {})
        self._slots = {}
        for i in range(NUM_SLOTS):
            key = str(i)
            self._slots[key] = {**DEFAULT_SLOT, **stored.get(key, {})}

    async def _save_slots(self) -> None:
        """Persist slot data to config entry options."""
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, "slots": self._slots}
        )

    # -- Slot data access --

    def get_slot(self, slot: int) -> dict[str, Any]:
        """Get slot data."""
        return self._slots.get(str(slot), {**DEFAULT_SLOT})

    def get_slot_name(self, slot: int) -> str:
        """Get human-readable name for slot."""
        name = self._slots.get(str(slot), {}).get("name", "")
        return name if name else f"Slot {slot}"

    def get_all_slots(self) -> dict[str, dict[str, Any]]:
        """Get all slot data."""
        return dict(self._slots)

    async def set_slot_name(self, slot: int, name: str) -> None:
        """Set name for a slot (does not send ZCL command)."""
        self._slots[str(slot)]["name"] = name
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

    # -- ZHA cluster access --

    def _get_cluster(self):
        """Get the Door Lock cluster from ZHA."""
        if ZHA_DOMAIN not in self.hass.data:
            _LOGGER.error("ZHA not found")
            return None

        zha_data = self.hass.data[ZHA_DOMAIN]

        if not hasattr(zha_data, "gateway_proxy"):
            _LOGGER.error("ZHA gateway_proxy not found")
            return None

        device_proxies = zha_data.gateway_proxy.device_proxies

        for dev_ieee, proxy in device_proxies.items():
            if str(dev_ieee).lower() == self.ieee.lower():
                device = proxy.device if hasattr(proxy, "device") else proxy
                for ep_id, ep in device.endpoints.items():
                    if ep_id == 0:
                        continue
                    if hasattr(ep, "in_clusters") and DOORLOCK_CLUSTER_ID in ep.in_clusters:
                        return ep.in_clusters[DOORLOCK_CLUSTER_ID]

        _LOGGER.error("Door Lock cluster not found for %s", self.ieee)
        return None

    async def _send_cluster_command(self, command: int, params: dict) -> bool:
        """Send a ZCL command, handling Nimly response quirk.

        Returns True if command was sent (even if response parsing failed).
        Returns False if command could not be sent at all.
        """
        cluster = self._get_cluster()
        if not cluster:
            return False

        try:
            commands = cluster.server_commands
            cmd_name = commands[command].name
            await getattr(cluster, cmd_name)(**params)
            return True
        except IndexError:
            # Nimly quirk: command was sent and received, but response
            # format is unexpected causing "tuple index out of range"
            # in zigpy response parsing. Command still reached the lock.
            _LOGGER.debug(
                "Nimly response quirk (IndexError) for command 0x%04x — "
                "command was sent successfully",
                command,
            )
            return True
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timeout sending command 0x%04x to %s — "
                "lock may be asleep, press a button and retry",
                command,
                self.ieee,
            )
            return False
        except Exception:
            _LOGGER.exception("Failed to send command 0x%04x to %s", command, self.ieee)
            return False

    # -- PIN operations --

    async def set_pin(self, slot: int, name: str, code: str) -> bool:
        """Set PIN code for a slot."""
        success = await self._send_cluster_command(
            0x0005,
            {
                "user_id": slot,
                "user_status": 1,  # Enabled
                "user_type": 0,  # Unrestricted
                "pin_code": code,
            },
        )
        if success:
            self._slots[str(slot)]["name"] = name
            self._slots[str(slot)]["has_pin"] = True
            await self._save_slots()
            self._notify_listeners()
        return success

    async def clear_pin(self, slot: int) -> bool:
        """Clear PIN code for a slot."""
        success = await self._send_cluster_command(
            0x0007,
            {"user_id": slot},
        )
        if success:
            self._slots[str(slot)]["has_pin"] = False
            await self._save_slots()
            self._notify_listeners()
        return success

    async def clear_slot(self, slot: int) -> bool:
        """Clear all credentials and name for a slot."""
        success = await self._send_cluster_command(
            0x0007,
            {"user_id": slot},
        )
        # Reset slot even if command failed — user wants it cleared
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
