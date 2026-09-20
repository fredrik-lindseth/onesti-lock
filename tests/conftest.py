"""One shared Home Assistant and voluptuous stub for every test module.

CI runs tests/ in the uv group `unit`, which has no homeassistant or
voluptuous, so the integration modules cannot import the real packages.
The stubs below carry just the names the integration touches, and they go
into sys.modules because scripts/ci_sim.py blocks the real packages with a
meta path finder, which sys.modules bypasses.

load_component_module() loads the integration's modules under one stub
package name. A relative import inside one module (`from .coordinator
import ...` in __init__.py) then resolves to the same module object a test
loaded directly, so a test that patches or inspects that module sees what
the code under test sees.

pytest imports this file before it collects any test module, so the stubs
are in place however the test files are ordered or selected.
"""
from __future__ import annotations

import enum
import importlib.util
import os
import sys
import types

COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "..", "custom_components", "onesti_lock")
PACKAGE = "onesti_lock_under_test"


def _module(name: str, *, package: bool = False) -> types.ModuleType:
    """Create a stub module, register it and attach it to its parent."""
    module = types.ModuleType(name)
    if package:
        module.__path__ = []
    sys.modules[name] = module
    parent_name, _, child = name.rpartition(".")
    if parent_name:
        setattr(sys.modules[parent_name], child, module)
    return module


# --- homeassistant -----------------------------------------------------------

_module("homeassistant", package=True)

core = _module("homeassistant.core")


class HomeAssistant:
    """Type-hint target only. Tests pass their own fake hass objects."""


class ServiceCall:
    """Type-hint target only. Tests pass their own fake call objects."""


def callback(func):
    return func


core.HomeAssistant = HomeAssistant
core.ServiceCall = ServiceCall
core.callback = callback


exceptions = _module("homeassistant.exceptions")


class HomeAssistantError(Exception):
    """Keeps the translation metadata the handlers attach."""

    def __init__(
        self,
        message="",
        *,
        translation_domain=None,
        translation_key=None,
        translation_placeholders=None,
    ):
        super().__init__(message)
        self.message = message
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders or {}


class ServiceValidationError(HomeAssistantError):
    """An error in the service call itself, as HA's own subclass is."""


exceptions.HomeAssistantError = HomeAssistantError
exceptions.ServiceValidationError = ServiceValidationError


config_entries = _module("homeassistant.config_entries")


class ConfigEntry[DataT]:
    """Type-hint target only. Tests pass their own fake entries.

    Generic like HA's, so ConfigEntry[OnestiCoordinator] resolves if anything
    ever evaluates the OnestiConfigEntry alias.
    """


class ConfigEntryState(enum.Enum):
    """The entry states the options flow compares against, as HA names them."""

    LOADED = "loaded"
    SETUP_RETRY = "setup_retry"
    NOT_LOADED = "not_loaded"


class _FlowResultsMixin:
    """Records every flow result as a plain dict, keyed like HA's FlowResult."""

    def async_show_form(self, *, step_id, data_schema=None, **kwargs):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema, **kwargs}

    def async_show_menu(self, *, step_id, menu_options, **kwargs):
        return {"type": "menu", "step_id": step_id, "menu_options": menu_options, **kwargs}

    def async_create_entry(self, *, data, title="", **kwargs):
        return {"type": "create_entry", "title": title, "data": data, **kwargs}

    def async_abort(self, *, reason, **kwargs):
        return {"type": "abort", "reason": reason, **kwargs}


class ConfigFlow(_FlowResultsMixin):
    """Accepts the domain= class keyword like HA's ConfigFlow."""

    domain: str | None = None

    def __init_subclass__(cls, *, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if domain is not None:
            cls.domain = domain

    async def async_set_unique_id(self, unique_id=None, **kwargs):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self, **kwargs):
        return None


class OptionsFlow(_FlowResultsMixin):
    """HA injects hass and config_entry after construction; tests set them."""


config_entries.SOURCE_IGNORE = "ignore"
config_entries.ConfigEntry = ConfigEntry
config_entries.ConfigEntryState = ConfigEntryState
config_entries.ConfigFlow = ConfigFlow
config_entries.ConfigFlowResult = dict
config_entries.OptionsFlow = OptionsFlow


_module("homeassistant.helpers", package=True)

config_validation = _module("homeassistant.helpers.config_validation")
config_validation.string = str

# zha.py imports this at module level, and ZhaLockTransport.wake looks the
# lock entity up through it.
entity_registry = _module("homeassistant.helpers.entity_registry")


def _entity_registry_async_get(hass):
    """Tests give their fake hass an entity_registry attribute."""
    return hass.entity_registry


def _async_entries_for_device(registry, device_id, include_disabled_entities=False):
    """Like HA's: the device's entities, disabled ones only on request."""
    return [
        entry
        for entry in registry.entities.values()
        if entry.device_id == device_id
        and (include_disabled_entities or getattr(entry, "disabled_by", None) is None)
    ]


entity_registry.async_get = _entity_registry_async_get
entity_registry.async_entries_for_device = _async_entries_for_device

# services.py resolves a device_id through it.
device_registry = _module("homeassistant.helpers.device_registry")


def _device_registry_async_get(hass):
    """Tests give their fake hass a device_registry attribute."""
    return hass.device_registry


def _device_registry_entries_for_config_entry(registry, config_entry_id):
    """Like HA's: the devices that belong to one config entry."""
    return [
        device
        for device in registry.devices
        if config_entry_id in getattr(device, "config_entries", ())
    ]


device_registry.async_get = _device_registry_async_get
device_registry.async_entries_for_config_entry = _device_registry_entries_for_config_entry
# zha.py finds the ZHA device behind a lock by this connection type.
device_registry.CONNECTION_ZIGBEE = "zigbee"


_module("homeassistant.components", package=True)

# zha.py reaches ZHA's gateway proxy through ZHA's own helper. The stub reads
# it the way the real one does, from hass.data["zha"].gateway_proxy, and
# raises the same ValueError when there is none.
_module("homeassistant.components.zha", package=True)
zha_helpers = _module("homeassistant.components.zha.helpers")


def _get_zha_gateway_proxy(hass):
    gateway_proxy = getattr(hass.data.get("zha"), "gateway_proxy", None)
    if gateway_proxy is None:
        raise ValueError("No gateway object exists")
    return gateway_proxy


zha_helpers.get_zha_gateway_proxy = _get_zha_gateway_proxy


# bluetooth.py reaches Home Assistant's Bluetooth integration through these
# names from homeassistant.components.bluetooth. The stub hands every call to
# hass.bluetooth, which a test sets to its own fake (tests/test_bluetooth.py
# has one), the way the zha stub reads hass.data.
bluetooth = _module("homeassistant.components.bluetooth")


class BluetoothChange(enum.Enum):
    ADVERTISEMENT = 1


class BluetoothScanningMode(enum.Enum):
    PASSIVE = "passive"
    ACTIVE = "active"


class BluetoothServiceInfoBleak:
    """The fields of habluetooth's service info that bluetooth.py reads."""

    def __init__(self, *, name, address, rssi, service_data, connectable=True):
        self.name = name
        self.address = address
        self.rssi = rssi
        self.service_data = service_data
        self.connectable = connectable


bluetooth.BluetoothChange = BluetoothChange
bluetooth.BluetoothScanningMode = BluetoothScanningMode
bluetooth.BluetoothServiceInfoBleak = BluetoothServiceInfoBleak
# A TypedDict in Home Assistant, so a dict at runtime.
bluetooth.BluetoothCallbackMatcher = dict
bluetooth.async_discovered_service_info = lambda hass, connectable=True: hass.bluetooth.discovered(connectable)
bluetooth.async_ble_device_from_address = lambda hass, address, connectable=True: hass.bluetooth.ble_device(
    address, connectable
)
bluetooth.async_register_callback = lambda hass, callback, matcher, mode: hass.bluetooth.register(
    callback, matcher, mode
)


# --- bleak-retry-connector ---------------------------------------------------

# Home Assistant's Bluetooth integration ships it, and bluetooth.py connects
# through it. The unit group has bleak itself (the BLE library's transport
# needs it) but not this, so the stub derives its errors from the real
# BleakError, as the package does. Without bleak there is nothing to derive
# from, and tests/test_bluetooth.py skips.
try:
    from bleak.exc import BleakError as _BleakError
except ImportError:
    _BleakError = None

if _BleakError is not None:
    bleak_retry_connector = _module("bleak_retry_connector")

    class BleakNotFoundError(_BleakError):
        """The device was not found, or vanished while connecting."""

    class BleakOutOfConnectionSlotsError(_BleakError):
        """No adapter or proxy had a free connection slot."""

    class BleakClientWithServiceCache:
        """Only passed through to establish_connection, which tests replace."""

    async def _establish_connection(*args, **kwargs):
        raise AssertionError("tests replace establish_connection on the module under test")

    async def _close_stale_connections_by_address(address, only_other_adapters=False):
        return None

    bleak_retry_connector.BleakNotFoundError = BleakNotFoundError
    bleak_retry_connector.BleakOutOfConnectionSlotsError = BleakOutOfConnectionSlotsError
    bleak_retry_connector.BleakClientWithServiceCache = BleakClientWithServiceCache
    bleak_retry_connector.establish_connection = _establish_connection
    bleak_retry_connector.close_stale_connections_by_address = _close_stale_connections_by_address


# --- zigpy -------------------------------------------------------------------

# ZHA ships zigpy, and zha.py tells a sleeping lock's errors apart by these
# two classes. Same hierarchy as zigpy.exceptions: DeliveryError is a
# ZigbeeException, so the order of except clauses matters in the tests too.
_module("zigpy", package=True)
zigpy_exceptions = _module("zigpy.exceptions")


class ZigbeeException(Exception):
    """Base class for zigpy's Zigbee errors."""


class DeliveryError(ZigbeeException):
    """A frame the radio could not deliver, typically to a sleeping device."""


zigpy_exceptions.ZigbeeException = ZigbeeException
zigpy_exceptions.DeliveryError = DeliveryError

# zha.py reads the status in the lock's answer against zigpy's ZCL Status.
_module("zigpy.zcl", package=True)
zigpy_foundation = _module("zigpy.zcl.foundation")


class Status(enum.IntEnum):
    """The part of zigpy.zcl.foundation.Status the tests use."""

    SUCCESS = 0x00
    FAILURE = 0x01
    NOT_AUTHORIZED = 0x7E


zigpy_foundation.Status = Status


# --- voluptuous --------------------------------------------------------------

vol = _module("voluptuous")


class Schema:
    def __init__(self, schema):
        self.schema = schema


class Marker:
    """Required/Optional: hashable by key so a schema dict can be read back."""

    def __init__(self, key, **kwargs):
        self.key = key
        self.default = kwargs.get("default")

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return isinstance(other, Marker) and other.key == self.key


class In:
    def __init__(self, container):
        self.container = container


vol.Schema = Schema
vol.Required = Marker
vol.Optional = Marker
vol.In = In
vol.All = lambda *validators: validators
vol.Range = lambda **kwargs: kwargs
vol.Coerce = lambda type_: type_


# --- integration loader ------------------------------------------------------


def load_component_module(name: str) -> types.ModuleType:
    """Load custom_components/onesti_lock/<name>.py under the shared stub package.

    The stub package is never executed, which keeps the real __init__.py out
    of the way unless a test asks for it by name ("__init__"). A dotted name
    ("ble.const") is a module in a subpackage: the normal import machinery
    finds it through the stub package's __path__ and runs the subpackage's own
    __init__.py first, but still never the component's.
    """
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [COMPONENT_DIR]
        sys.modules[PACKAGE] = package
    full_name = f"{PACKAGE}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    if "." in name:
        return importlib.import_module(full_name)
    spec = importlib.util.spec_from_file_location(full_name, os.path.join(COMPONENT_DIR, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
