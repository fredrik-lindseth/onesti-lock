# Nimly PRO v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite nimly_pro integration with entity-based slot→name mapping, activity sensor, and robust ZHA quirk handling.

**Architecture:** Service + sensor integration that wraps ZHA cluster commands. 10 slot sensors track users, 1 activity sensor shows human-readable lock events. All state stored in config entry options.

**Tech Stack:** Home Assistant custom_component, ZHA/zigpy, Python 3.12+

---

### Task 1: Clean slate — remove old code, set up structure

**Files:**
- Delete: `custom_components/nimly_pro/services.py`
- Delete: `custom_components/nimly_pro/services.yaml`
- Delete: `custom_components/nimly_pro/helpers.py`
- Delete: `custom_components/nimly_pro/__pycache__/`
- Keep: `custom_components/nimly_pro/` (directory)
- Keep: `docs/`, `hacs.json`, `LICENSE`

**Step 1: Remove old implementation files**

```bash
cd ~/dev/nimly-touch-pro-integration
rm -rf custom_components/nimly_pro/services.py
rm -rf custom_components/nimly_pro/services.yaml
rm -rf custom_components/nimly_pro/helpers.py
rm -rf custom_components/nimly_pro/__init__.py
rm -rf custom_components/nimly_pro/config_flow.py
rm -rf custom_components/nimly_pro/const.py
rm -rf custom_components/nimly_pro/strings.json
rm -rf custom_components/nimly_pro/__pycache__/
```

**Step 2: Commit clean slate**

```bash
git add -A && git commit -m "chore: remove old v1 implementation"
```

---

### Task 2: const.py — constants and slot model

**Files:**
- Create: `custom_components/nimly_pro/const.py`

**Step 1: Write const.py**

```python
"""Constants for Nimly PRO integration."""

DOMAIN = "nimly_pro"

CONF_IEEE = "ieee"

# Zigbee
DOORLOCK_CLUSTER_ID = 0x0101
ZHA_DOMAIN = "zha"

# Nimly hardware
NUM_SLOTS = 10  # Slots 0-9
SUPPORTED_MODELS = ["NimlyPRO", "NimlyPRO24"]
MANUFACTURER = "Onesti Products AS"

# ZCL Door Lock commands
CMD_SET_PIN = 0x0005
CMD_GET_PIN = 0x0006
CMD_CLEAR_PIN = 0x0007
CMD_CLEAR_ALL_PINS = 0x0008
CMD_OPERATION_EVENT = 0x0020

# ZCL User status
USER_STATUS_AVAILABLE = 0
USER_STATUS_ENABLED = 1
USER_STATUS_DISABLED = 3

# ZCL User type
USER_TYPE_UNRESTRICTED = 0

# Default empty slot
DEFAULT_SLOT = {
    "name": "",
    "has_pin": False,
    "has_rfid": False,
}

# Operation event sources
SOURCE_KEYPAD = "keypad"
SOURCE_RF = "rf"
SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"
SOURCE_UNKNOWN = "unknown"

# Operation event actions
ACTION_LOCK = "lock"
ACTION_UNLOCK = "unlock"
ACTION_UNKNOWN = "unknown"
```

**Step 2: Commit**

```bash
git add custom_components/nimly_pro/const.py
git commit -m "feat: const.py with slot model and ZCL constants"
```

---

### Task 3: coordinator.py — slot storage and ZHA cluster wrapper

**Files:**
- Create: `custom_components/nimly_pro/coordinator.py`

**Step 1: Write coordinator.py**

This is the core — manages slot data and wraps ZHA calls with quirk handling.

```python
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
```

**Step 2: Commit**

```bash
git add custom_components/nimly_pro/coordinator.py
git commit -m "feat: coordinator with slot storage and ZHA quirk handling"
```

---

### Task 4: sensor.py — slot sensors and activity sensor

**Files:**
- Create: `custom_components/nimly_pro/sensor.py`

**Step 1: Write sensor.py**

```python
"""Sensors for Nimly PRO — slot status and activity."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUM_SLOTS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nimly PRO sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SensorEntity] = []

    # Slot sensors
    for slot in range(NUM_SLOTS):
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
        return {"identifiers": {(DOMAIN, self._coordinator.ieee)}}

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
        elif source == "rf":
            return f"{name} {verb} med RFID"
        elif source == "manual":
            return f"Manuell {verb.replace('låste', 'lås')}"
        elif source == "auto":
            return f"Auto-lås"
        else:
            return f"{name} {verb}"

    @property
    def extra_state_attributes(self) -> dict:
        return dict(self._activity) if self._activity else {}

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._coordinator.ieee)}}

    def update_activity(
        self,
        user_slot: int | None,
        action: str,
        source: str,
    ) -> None:
        """Called by event listener when lock activity occurs."""
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
```

**Step 2: Commit**

```bash
git add custom_components/nimly_pro/sensor.py
git commit -m "feat: slot sensors and activity sensor"
```

---

### Task 5: services.py + services.yaml — PIN management services

**Files:**
- Create: `custom_components/nimly_pro/services.py`
- Create: `custom_components/nimly_pro/services.yaml`

**Step 1: Write services.py**

```python
"""Services for Nimly PRO — PIN code management."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, NUM_SLOTS

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
    raise HomeAssistantError(f"Nimly lock not found{f' for {ieee}' if ieee else ''}")


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Nimly PRO services."""

    async def handle_set_pin(call: ServiceCall) -> None:
        slot = call.data["slot"]
        name = call.data["name"]
        code = call.data["code"]
        ieee = call.data.get("ieee")

        if not 0 <= slot < NUM_SLOTS:
            raise HomeAssistantError(f"Slot must be 0-{NUM_SLOTS - 1}")
        if not code.isdigit() or len(code) < 4 or len(code) > 8:
            raise HomeAssistantError("PIN must be 4-8 digits")

        coordinator = _get_coordinator(hass, ieee)
        success = await coordinator.set_pin(slot, name, code)
        if not success:
            raise HomeAssistantError(
                "Kunne ikke nå låsen — trykk en knapp på låsen og prøv igjen"
            )

    async def handle_clear_pin(call: ServiceCall) -> None:
        slot = call.data["slot"]
        ieee = call.data.get("ieee")

        if not 0 <= slot < NUM_SLOTS:
            raise HomeAssistantError(f"Slot must be 0-{NUM_SLOTS - 1}")

        coordinator = _get_coordinator(hass, ieee)
        success = await coordinator.clear_pin(slot)
        if not success:
            raise HomeAssistantError(
                "Kunne ikke nå låsen — trykk en knapp på låsen og prøv igjen"
            )

    async def handle_set_name(call: ServiceCall) -> None:
        slot = call.data["slot"]
        name = call.data["name"]
        ieee = call.data.get("ieee")

        if not 0 <= slot < NUM_SLOTS:
            raise HomeAssistantError(f"Slot must be 0-{NUM_SLOTS - 1}")

        coordinator = _get_coordinator(hass, ieee)
        await coordinator.set_slot_name(slot, name)

    async def handle_clear_slot(call: ServiceCall) -> None:
        slot = call.data["slot"]
        ieee = call.data.get("ieee")

        if not 0 <= slot < NUM_SLOTS:
            raise HomeAssistantError(f"Slot must be 0-{NUM_SLOTS - 1}")

        coordinator = _get_coordinator(hass, ieee)
        await coordinator.clear_slot(slot)

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
    """Remove Nimly PRO services."""
    for service in ("set_pin", "clear_pin", "set_name", "clear_slot"):
        hass.services.async_remove(DOMAIN, service)
```

**Step 2: Write services.yaml**

```yaml
set_pin:
  name: Set PIN code
  description: Set a PIN code for a lock slot
  fields:
    slot:
      name: Slot
      description: User slot number (0-9)
      required: true
      selector:
        number:
          min: 0
          max: 9
          mode: box
    name:
      name: Name
      description: Name for this user (e.g. "Kari")
      required: true
      selector:
        text:
    code:
      name: PIN code
      description: PIN code (4-8 digits)
      required: true
      selector:
        text:
    ieee:
      name: IEEE address
      description: Lock IEEE address (optional if only one lock)
      required: false
      selector:
        text:

clear_pin:
  name: Clear PIN code
  description: Remove a PIN code from a lock slot
  fields:
    slot:
      name: Slot
      description: User slot number (0-9)
      required: true
      selector:
        number:
          min: 0
          max: 9
          mode: box
    ieee:
      name: IEEE address
      description: Lock IEEE address (optional if only one lock)
      required: false
      selector:
        text:

set_name:
  name: Set slot name
  description: Set or change the name for a slot without changing the PIN
  fields:
    slot:
      name: Slot
      description: User slot number (0-9)
      required: true
      selector:
        number:
          min: 0
          max: 9
          mode: box
    name:
      name: Name
      description: Name for this user
      required: true
      selector:
        text:
    ieee:
      name: IEEE address
      description: Lock IEEE address (optional if only one lock)
      required: false
      selector:
        text:

clear_slot:
  name: Clear slot
  description: Remove all credentials and name from a slot
  fields:
    slot:
      name: Slot
      description: User slot number (0-9)
      required: true
      selector:
        number:
          min: 0
          max: 9
          mode: box
    ieee:
      name: IEEE address
      description: Lock IEEE address (optional if only one lock)
      required: false
      selector:
        text:
```

**Step 3: Commit**

```bash
git add custom_components/nimly_pro/services.py custom_components/nimly_pro/services.yaml
git commit -m "feat: PIN management services with validation"
```

---

### Task 6: config_flow.py — ZHA device selection

**Files:**
- Create: `custom_components/nimly_pro/config_flow.py`

**Step 1: Write config_flow.py**

```python
"""Config flow for Nimly PRO."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_IEEE, DOMAIN, MANUFACTURER, SUPPORTED_MODELS, ZHA_DOMAIN

_LOGGER = logging.getLogger(__name__)


class NimlyProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Nimly PRO."""

    VERSION = 2

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle user step — select a Nimly lock from ZHA."""
        if ZHA_DOMAIN not in self.hass.data:
            return self.async_abort(reason="zha_not_found")

        zha_data = self.hass.data[ZHA_DOMAIN]
        if not hasattr(zha_data, "gateway_proxy"):
            return self.async_abort(reason="zha_not_found")

        # Find Nimly devices
        devices = {}
        for ieee, proxy in zha_data.gateway_proxy.device_proxies.items():
            device = proxy.device if hasattr(proxy, "device") else proxy
            manufacturer = getattr(device, "manufacturer", "")
            model = getattr(device, "model", "")
            if manufacturer == MANUFACTURER and model in SUPPORTED_MODELS:
                ieee_str = str(ieee)
                # Skip already configured
                existing = {
                    entry.data.get(CONF_IEEE)
                    for entry in self._async_current_entries()
                }
                if ieee_str not in existing:
                    devices[ieee_str] = f"{model} ({ieee_str})"

        if not devices:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            ieee = user_input["device"]
            await self.async_set_unique_id(ieee)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Nimly PRO ({ieee[-8:]})",
                data={CONF_IEEE: ieee},
                options={"slots": {}},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(devices),
                }
            ),
        )
```

**Step 2: Commit**

```bash
git add custom_components/nimly_pro/config_flow.py
git commit -m "feat: config flow — select Nimly lock from ZHA"
```

---

### Task 7: __init__.py — setup with event listener

**Files:**
- Create: `custom_components/nimly_pro/__init__.py`

**Step 1: Write __init__.py**

```python
"""Nimly PRO — PIN management and activity tracking for Nimly locks."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    ACTION_LOCK,
    ACTION_UNLOCK,
    ACTION_UNKNOWN,
    DOMAIN,
    SOURCE_AUTO,
    SOURCE_KEYPAD,
    SOURCE_MANUAL,
    SOURCE_RF,
    SOURCE_UNKNOWN,
)
from .coordinator import NimlyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nimly PRO from a config entry."""
    coordinator = NimlyCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    # Register services (idempotent)
    from .services import async_setup_services
    await async_setup_services(hass)

    # Set up sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for ZHA events from this lock
    unsub = _setup_event_listener(hass, coordinator)
    hass.data[DOMAIN][entry.entry_id]["unsub_event"] = unsub

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unsubscribe from events
    unsub = hass.data[DOMAIN][entry.entry_id].get("unsub_event")
    if unsub:
        unsub()

    # Unload platforms
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove entry data
    hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove services if no more entries
    if not hass.data[DOMAIN]:
        from .services import async_unload_services
        await async_unload_services(hass)

    return True


def _setup_event_listener(hass: HomeAssistant, coordinator: NimlyCoordinator):
    """Listen for zha_event from this lock and update activity sensor."""

    @callback
    def _handle_zha_event(event: Event) -> None:
        """Handle ZHA event from the lock."""
        data = event.data
        device_ieee = data.get("device_ieee", "")

        if device_ieee.lower() != coordinator.ieee.lower():
            return

        command = data.get("command")
        args = data.get("args", {})

        _LOGGER.debug("ZHA event from %s: command=%s args=%s", device_ieee, command, args)

        # Parse operation_event_notification
        if command == "operation_event_notification":
            source_raw = args.get("operation_event_source", 0)
            operation = args.get("operation_event_code", 0)
            user_id = args.get("userid", None)

            # Map source
            source_map = {0: SOURCE_KEYPAD, 1: SOURCE_RF, 2: SOURCE_MANUAL}
            source = source_map.get(source_raw, SOURCE_UNKNOWN)

            # Map action (bit 0: 0=lock, 1=unlock for most sources)
            if operation in (1, 3, 5, 7, 9, 11):
                action = ACTION_UNLOCK
            elif operation in (0, 2, 4, 6, 8, 10):
                action = ACTION_LOCK
            else:
                action = ACTION_UNKNOWN

            # Auto-lock has no user
            if source_raw == 3 or operation == 11:
                source = SOURCE_AUTO
                user_id = None

            # Find activity sensor and update it
            entry_data = hass.data.get(DOMAIN, {})
            for ed in entry_data.values():
                coord = ed.get("coordinator")
                if coord and coord.ieee.lower() == coordinator.ieee.lower():
                    # Find the activity sensor entity
                    # We'll iterate entities — sensor registers itself
                    break

            # Fire HA event for automations
            hass.bus.async_fire(
                "nimly_pro_lock_activity",
                {
                    "ieee": coordinator.ieee,
                    "user_slot": user_id,
                    "user_name": coordinator.get_slot_name(user_id)
                    if user_id is not None
                    else None,
                    "action": action,
                    "source": source,
                },
            )

    return hass.bus.async_listen("zha_event", _handle_zha_event)
```

Note: The activity sensor update from events needs the sensor to register itself with the coordinator. We need to add this connection.

**Step 2: Add activity sensor registration to coordinator**

Add to `coordinator.py`:

```python
    # In __init__:
    self._activity_sensor = None

    def set_activity_sensor(self, sensor) -> None:
        """Register the activity sensor for updates."""
        self._activity_sensor = sensor

    def update_activity(self, user_slot, action, source) -> None:
        """Update the activity sensor."""
        if self._activity_sensor:
            self._activity_sensor.update_activity(user_slot, action, source)
```

Then in `__init__.py` `_handle_zha_event`, replace the "find activity sensor" block with:

```python
            coordinator.update_activity(user_id, action, source)
```

And in `sensor.py` `NimlyActivitySensor.async_added_to_hass`:

```python
    async def async_added_to_hass(self) -> None:
        self._coordinator.set_activity_sensor(self)
```

**Step 3: Commit**

```bash
git add custom_components/nimly_pro/__init__.py
git commit -m "feat: init with ZHA event listener and activity tracking"
```

---

### Task 8: manifest.json + strings.json

**Files:**
- Create: `custom_components/nimly_pro/manifest.json`
- Create: `custom_components/nimly_pro/strings.json`

**Step 1: Write manifest.json**

```json
{
  "domain": "nimly_pro",
  "name": "Nimly PRO",
  "codeowners": ["@fredrik-lindseth"],
  "config_flow": true,
  "dependencies": ["zha"],
  "documentation": "https://github.com/fredrik-lindseth/nimly-touch-pro-integration",
  "iot_class": "local_push",
  "issue_tracker": "https://github.com/fredrik-lindseth/nimly-touch-pro-integration/issues",
  "requirements": [],
  "version": "1.0.0"
}
```

**Step 2: Write strings.json**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Select Nimly PRO Lock",
        "description": "Select the Nimly lock to manage PIN codes for.",
        "data": {
          "device": "Device"
        }
      }
    },
    "abort": {
      "zha_not_found": "ZHA integration not found. Set up ZHA first.",
      "no_devices_found": "No Nimly PRO locks found in ZHA.",
      "already_configured": "This lock is already configured."
    }
  }
}
```

**Step 3: Commit**

```bash
git add custom_components/nimly_pro/manifest.json custom_components/nimly_pro/strings.json
git commit -m "feat: manifest v1.0.0 and config flow strings"
```

---

### Task 9: Deploy and test on HA Leirnes

**Step 1: Copy to HA**

```bash
scp -r ~/dev/nimly-touch-pro-integration/custom_components/nimly_pro ha-leirnes-local:/root/config/custom_components/
```

**Step 2: Remove old scripts/input helpers from configuration.yaml**

Remove the `input_number`, `input_text`, `input_select`, `input_boolean`, and `lovelace` dashboard sections we added earlier. Keep `default_config`, `automation`, `script`, `scene`, `recorder`, and `frontend`.

**Step 3: Restart HA**

```bash
ssh ha-leirnes-local 'ha core restart'
```

**Step 4: Add integration via UI**

Settings → Devices & Services → Add Integration → Nimly PRO → Select lock

**Step 5: Verify entities exist**

Check that `sensor.nimly_pro_*_slot_0` through `slot_9` and `sensor.nimly_pro_*_siste_aktivitet` appear.

**Step 6: Test set_pin via Developer Tools → Services**

```yaml
service: nimly_pro.set_pin
data:
  slot: 0
  name: "Ola"
  code: "1234"
```

Verify slot sensor updates to "Ola".

**Step 7: Test on keypad**

Walk to door, enter PIN, verify activity sensor updates.

**Step 8: Commit any fixes**

```bash
git add -A && git commit -m "fix: deployment adjustments from live testing"
```

---

### Task 10: Clean up HA config — remove old workarounds

**Step 1: Remove old scripts, input helpers, automations, dashboard**

On HA, edit `configuration.yaml` to remove all `input_number`, `input_text`, `input_select`, `input_boolean` sections for dørlås. Remove `lovelace` dashboard config. Reset `scripts.yaml` and `automations.yaml` to `[]`.

**Step 2: Restart and verify**

```bash
ssh ha-leirnes-local 'ha core restart'
```

Verify only nimly_pro entities remain for the lock.
