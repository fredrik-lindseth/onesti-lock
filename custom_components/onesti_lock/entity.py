"""Base class for the entities Onesti Lock creates."""
from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_MODEL, DOMAIN, MANUFACTURER
from .coordinator import OnestiCoordinator
from .zha import find_zha_device

# HA 2026.9 replaced DeviceInfo's via_device, an identifier tuple the
# registry resolved, with via_device_id, the device id itself. Both name
# the same link; which one exists decides how the link is built below.
HAS_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__optional_keys__


def device_name(ieee: str, model: str) -> str:
    """What the lock's device is called, with two of them side by side.

    The model alone does not tell two locks of the same model apart, so
    the last four characters of the IEEE address come with it. They are
    what ZHA's device page shows last under Zigbee info, and the same
    four are in the config entry title.
    """
    tail = ieee.replace(":", "")[-4:]
    return f"{model} ({tail})" if model else f"Onesti Lock ({tail})"


def build_device_info(hass: HomeAssistant, coordinator: OnestiCoordinator) -> DeviceInfo:
    """The device the lock's entities hang on.

    identifiers are keyed on the config entry, not on the IEEE address:
    a replaced Connect Module changes the address, and the reconfigure
    flow points the entry at the new one without throwing the device and
    its entities away.

    The zigbee connection ZHA registers the lock with is carried only
    from HA 2026.9, where a connection is unique within one config entry:
    the two devices stay apart, and the link is made explicitly with
    ZHA's device as the one this hangs off. Through 2026.8 the same
    connection was unique across config entries, so the registry would
    fold this device into ZHA's row. That row is ZHA's to delete: it
    removes the whole thing when the lock leaves the network or the user
    removes the device, and our sensors, their names, areas and restore
    data would go with it. So on those releases the device stands alone,
    which is also what every release up to 1.4.0 gave.
    """
    ieee = coordinator.ieee
    model = str(coordinator.entry.data.get(CONF_MODEL) or "")
    device_info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.entry.entry_id)},
        name=device_name(ieee, model),
        manufacturer=MANUFACTURER,
        model=model or None,
        serial_number=ieee,
    )
    # Set after the fact rather than as keywords, because via_device_id is
    # not in the older release's TypedDict at all.
    if HAS_VIA_DEVICE_ID:
        device_info["connections"] = {(dr.CONNECTION_ZIGBEE, ieee.lower())}
        if (zha_device := find_zha_device(hass, ieee)) is not None:
            device_info["via_device_id"] = zha_device.id
    return device_info


class OnestiEntity(Entity):
    """An entity on the Onesti Lock device of one lock.

    Every unique_id is the config entry id followed by a per-entity key,
    and the entity registry holds users' entities by it, so the format
    must not change. Never set _attr_name here or in a subclass: HA checks
    it before the translation key, which silently disables translated
    names.

    Available, deliberately, whatever ZHA is doing. Almost everything
    these entities show is Home Assistant's own stored data in
    entry.options: slot names, whether a slot holds a code, what the lock
    once reported about itself. None of it goes stale because the Zigbee
    stack is down, and all of it is still writable through the options
    flow and the services. Only a value that ZHA keeps up to date can go
    unavailable, and the activity sensor is the one that does; it
    overrides this with OnestiCoordinator.available.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: OnestiCoordinator, key: str) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}-{key}"
        self._attr_device_info = build_device_info(coordinator.hass, coordinator)

    async def async_added_to_hass(self) -> None:
        """Follow the coordinator.

        A subclass that registers its own listener (the slot sensors do,
        for slot data) may skip this; one that calls super() is written
        again whenever the coordinator's data or availability changes.
        """
        await super().async_added_to_hass()
        self._coordinator.add_listener(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.remove_listener(self._handle_coordinator_update)
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
