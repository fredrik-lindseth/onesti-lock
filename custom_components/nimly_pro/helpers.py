"""Helper functions for Nimly Touch Pro integration."""
import logging

_LOGGER = logging.getLogger(__name__)

ZHA_DOMAIN = "zha"


def get_zha_gateway(hass):
    """Get the ZHA gateway from hass.data."""
    if ZHA_DOMAIN not in hass.data:
        _LOGGER.error("ZHA domain not found in hass.data")
        return None
    zha_data = hass.data[ZHA_DOMAIN]

    # For HA 2024.x+ with HAZHAData object
    if hasattr(zha_data, "gateway"):
        return zha_data.gateway

    # For HAZHAData object, try to access gateway_proxy
    if hasattr(zha_data, "gateway_proxy"):
        gateway_proxy = zha_data.gateway_proxy
        
        # The gateway_proxy has a 'gateway' attribute which is the actual zigpy gateway
        if hasattr(gateway_proxy, "gateway"):
            return gateway_proxy.gateway
        
        # Or it might have device_proxies directly
        if hasattr(gateway_proxy, "device_proxies"):
            return gateway_proxy
            
        return gateway_proxy

    # Legacy: dict-based storage
    if isinstance(zha_data, dict):
        if "gateway" in zha_data:
            return zha_data["gateway"]
        for entry_data in zha_data.values():
            if hasattr(entry_data, "gateway"):
                return entry_data.gateway
            if isinstance(entry_data, dict) and "gateway" in entry_data:
                return entry_data["gateway"]

    _LOGGER.error("Could not find ZHA gateway in data: %s", type(zha_data))
    return None


def get_zha_device(hass, ieee: str):
    """Get a ZHA device by IEEE address.
    
    Returns the underlying zigpy device with endpoints, not the ZHADeviceProxy.
    """
    if ZHA_DOMAIN not in hass.data:
        _LOGGER.error("ZHA domain not in hass.data")
        return None
        
    zha_data = hass.data[ZHA_DOMAIN]
    
    # Modern approach: use gateway_proxy.device_proxies
    if hasattr(zha_data, "gateway_proxy"):
        gateway_proxy = zha_data.gateway_proxy
        
        if hasattr(gateway_proxy, "device_proxies"):
            device_proxies = gateway_proxy.device_proxies
            
            # Find the device proxy
            device_proxy = None
            for dev_ieee, proxy in device_proxies.items():
                if str(dev_ieee) == ieee or str(dev_ieee).lower() == ieee.lower():
                    device_proxy = proxy
                    break
            
            if device_proxy:
                # ZHADeviceProxy wraps the actual device
                # Try to get the underlying device with endpoints
                if hasattr(device_proxy, "device"):
                    _LOGGER.debug("Returning device_proxy.device")
                    return device_proxy.device
                    
                # Some versions have _device
                if hasattr(device_proxy, "_device"):
                    _LOGGER.debug("Returning device_proxy._device")
                    return device_proxy._device
                
                # Return the proxy and let the caller handle it
                return device_proxy
                    
        # Try via gateway.devices
        if hasattr(gateway_proxy, "gateway"):
            gateway = gateway_proxy.gateway
            if hasattr(gateway, "devices"):
                for dev_ieee, device in gateway.devices.items():
                    if str(dev_ieee) == ieee or str(dev_ieee).lower() == ieee.lower():
                        return device

    # Fallback to old method
    gateway = get_zha_gateway(hass)
    if not gateway:
        return None

    if hasattr(gateway, "get_device"):
        return gateway.get_device(ieee)

    if hasattr(gateway, "devices"):
        devices = gateway.devices
        if hasattr(devices, "get"):
            return devices.get(ieee)
        for dev_ieee, device in devices.items():
            if str(dev_ieee) == ieee:
                return device

    _LOGGER.error("Could not find device %s in any location", ieee)
    return None
