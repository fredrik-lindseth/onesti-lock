"""Coordinator for Onesti Lock — slot data and ZHA cluster access."""
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
    MAX_SLOTS,
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
        self.lock_capabilities: dict[str, Any] = {}
        self._load_slots()

    def _load_slots(self) -> None:
        """Load slot data from config entry options.

        Only loads slots that have been used — no pre-allocation.
        get_slot() returns DEFAULT_SLOT for unknown slots.
        """
        stored = self.entry.options.get("slots", {})
        self._slots = {k: {**DEFAULT_SLOT, **v} for k, v in stored.items()}

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
        self._slots.setdefault(str(slot), {**DEFAULT_SLOT})["name"] = name
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

    def update_last_pin_code(self, pin_code: str | None) -> None:
        """Store the last-used PIN code (attrid 0x0101).

        Onesti reports the actual digits used on the keypad. Kept as an
        attribute on the activity sensor for audit and automation use.
        """
        if self._activity_sensor:
            self._activity_sensor.update_last_pin_code(pin_code)

    async def read_lock_capabilities(self) -> None:
        """Read static lock properties from the DoorLock cluster.

        Populates lock_capabilities with num_pin_users, max_pin_length,
        min_pin_length. Degrades silently if the lock does not expose them —
        some Onesti variants skip these standard ZCL attributes, and a sleepy
        device may never respond.
        """
        cluster = self._get_cluster()
        if cluster is None:
            return
        # Standard ZCL DoorLock attributes (per zigpy.zcl.clusters.closures):
        #   0x0012 NumberOfPINUsersSupported
        #   0x0017 MaxPINCodeLength
        #   0x0018 MinPINCodeLength
        attr_ids = [0x0012, 0x0017, 0x0018]
        attr_names = {
            0x0012: "num_pin_users",
            0x0017: "max_pin_length",
            0x0018: "min_pin_length",
        }
        try:
            result = await cluster.read_attributes(attr_ids)
        except (asyncio.TimeoutError, TimeoutError):
            _LOGGER.debug("Lock capabilities read timed out — lock asleep or out of range")
            return
        except (AttributeError, TypeError):
            _LOGGER.debug("Lock capabilities read failed — cluster API shape changed", exc_info=True)
            return
        except Exception:
            # zigpy/ZHA-side errors: DeliveryError, ZigbeeException, etc.
            # We deliberately keep this wide so an exotic firmware quirk on one
            # lock does not block integration setup for everyone else.
            _LOGGER.debug("Lock capabilities read failed", exc_info=True)
            return

        # zigpy returns (success_dict, failure_dict). Keys may be attribute
        # IDs or attribute names depending on cluster metadata.
        success = result[0] if isinstance(result, tuple) and len(result) >= 1 else {}
        failure = result[1] if isinstance(result, tuple) and len(result) >= 2 else {}
        if failure:
            _LOGGER.debug("Lock did not expose capabilities: %s", failure)
        for attr_id, value in success.items():
            name = attr_names.get(attr_id)
            if name and value is not None:
                self.lock_capabilities[name] = int(value)

    # -- ZHA cluster access --

    def _get_cluster(self):
        """Get the Door Lock cluster from ZHA.

        Walks the ZHA object chain: ZHADeviceProxy → Device → CustomDeviceV2
        because clusters live on the deepest zigpy device object, not the
        ZHA wrapper layers.
        """
        if ZHA_DOMAIN not in self.hass.data:
            _LOGGER.error("ZHA not found")
            return None

        zha_data = self.hass.data[ZHA_DOMAIN]

        if not hasattr(zha_data, "gateway_proxy"):
            _LOGGER.error("ZHA gateway_proxy not found")
            return None

        for dev_ieee, proxy in zha_data.gateway_proxy.device_proxies.items():
            if str(dev_ieee).lower() != self.ieee.lower():
                continue

            # Walk down .device chain until we find clusters
            obj = proxy
            for _ in range(4):
                if hasattr(obj, "endpoints"):
                    for ep_id, ep in obj.endpoints.items():
                        if ep_id == 0:
                            continue
                        clusters = getattr(ep, "in_clusters", {})
                        if DOORLOCK_CLUSTER_ID in clusters:
                            return clusters[DOORLOCK_CLUSTER_ID]
                if hasattr(obj, "device"):
                    obj = obj.device
                else:
                    break

        _LOGGER.error("Door Lock cluster not found for %s", self.ieee)
        return None

    async def _wake_lock(self) -> None:
        """Wake the lock by sending a lock state read via ZHA.

        ZHA's lock entity uses extended timeout for sleepy devices,
        so this reliably wakes the lock's Zigbee radio.
        """
        try:
            # Find the lock entity for this device
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(self.hass)
            for entity in registry.entities.values():
                if entity.platform != "zha":
                    continue
                uid = entity.unique_id or ""
                if self.ieee.lower() in uid.lower() and uid.endswith("257"):
                    _LOGGER.debug("Waking lock via %s", entity.entity_id)
                    await self.hass.services.async_call(
                        "lock", "lock",
                        {"entity_id": entity.entity_id},
                        blocking=True,
                    )
                    await asyncio.sleep(1)
                    return
        except Exception:
            _LOGGER.debug("Wake attempt failed, proceeding anyway")

    async def _send_cluster_command(self, command: int, params: dict) -> bool:
        """Send a ZCL command, handling Nimly response quirk.

        Tries ZHA issue_zigbee_cluster_command first. If it times out,
        wakes the lock and retries once.

        Returns True if command was sent (even if response parsing failed).
        Returns False if command could not be sent at all.
        """
        for attempt in range(2):
            try:
                await self.hass.services.async_call(
                    "zha",
                    "issue_zigbee_cluster_command",
                    {
                        "ieee": self.ieee,
                        "endpoint_id": 11,
                        "cluster_id": DOORLOCK_CLUSTER_ID,
                        "cluster_type": "in",
                        "command": command,
                        "command_type": "server",
                        "params": params,
                    },
                    blocking=True,
                )
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
            except TimeoutError:
                if attempt == 0:
                    _LOGGER.info(
                        "Timeout on attempt 1 for command 0x%04x — waking lock and retrying",
                        command,
                    )
                    await self._wake_lock()
                    continue
                _LOGGER.warning(
                    "Timeout sending command 0x%04x to %s after wake+retry — "
                    "lock may be unreachable",
                    command,
                    self.ieee,
                )
                return False
            except Exception:
                _LOGGER.exception("Failed to send command 0x%04x to %s", command, self.ieee)
                return False
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
            slot_data = self._slots.setdefault(str(slot), {**DEFAULT_SLOT})
            slot_data["name"] = name
            slot_data["has_pin"] = True
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
            self._slots.setdefault(str(slot), {**DEFAULT_SLOT})["has_pin"] = False
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
