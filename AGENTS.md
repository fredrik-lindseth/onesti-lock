# Agent Instructions for Nimly Touch Pro Integration

## Project Description
Home Assistant custom integration for Nimly Touch Pro smart locks, providing extended functionality beyond the standard ZHA integration:
- **Lock Control** - Lock/unlock with user tracking
- **Sensors** - Door state, battery, firmware version
- **Settings** - LED brightness, sound volume, auto-relock time

## Language
- Code: English (variable names, functions, code comments)
- Commit messages: Norwegian with descriptive body
- Documentation: English
- Communication: English or Norwegian

## Git Preferences
- Skriv commit-meldinger på norsk med beskrivende body
- Bruk commit-historikken som en logg over hva som er forsøkt, hva som feilet, og kontekst for senere arbeid
- Eksempel på god commit-melding:
  ```
  Fiks ZHA device-tilgang for HA 2024.x+
  
  Problemet var at ZHA-strukturen endret seg i nyere HA-versjoner.
  Tidligere: hass.data["zha"]["gateway"]
  Nå: hass.data["zha"].gateway_proxy.device_proxies
  
  Feilet først med get_zha_gateway() som ikke fantes lenger.
  Løst ved å lage helpers.py som navigerer den nye strukturen.
  ```
- **Always ask before pushing to remote** (push triggers a new release!)
- Bump version in `manifest.json` before pushing new releases
- Follow semantic versioning (MAJOR.MINOR.PATCH)

## Release Process
1. Make your changes
2. Update version in `custom_components/nimly_pro/manifest.json`
3. Commit changes
4. Ask user before pushing
5. Push triggers GitHub Action that creates release automatically

## Release Notes Guidelines
- Write release notes for **end users**, not developers
- Only include changes that are relevant to users (bug fixes, new features, improvements)
- Skip internal changes (refactoring, CI/CD, code cleanup) unless they affect functionality
- Use clear, non-technical language when possible
- Format with sections: "Bug Fixes", "New Features", "Improvements" as needed

## Important Files
| File                                         | Description                         |
|----------------------------------------------|-------------------------------------|
| `custom_components/nimly_pro/manifest.json`  | Version and dependencies            |
| `custom_components/nimly_pro/config_flow.py` | Configuration flow for adding locks |
| `custom_components/nimly_pro/const.py`       | Constants and Zigbee cluster IDs    |
| `custom_components/nimly_pro/helpers.py`     | ZHA device access helpers           |
| `custom_components/nimly_pro/lock.py`        | Lock entity implementation          |
| `custom_components/nimly_pro/sensor.py`      | Sensor entities                     |
| `custom_components/nimly_pro/strings.json`   | UI strings for config flow          |

## Version Compatibility

### Home Assistant
- **Target version**: 2024.x+ (tested with 2024.12+)
- ZHA integration structure changed significantly in 2024.x
- Use `helpers.py` functions to access ZHA devices

### ZHA Data Structure (HA 2024.x+)
The ZHA integration uses this object hierarchy:
```
hass.data["zha"]                    # HAZHAData object
  └── .gateway_proxy                # ZHAGatewayProxy object
        └── .device_proxies         # Dict[EUI64, ZHADeviceProxy]
              └── [ieee].device     # zha.zigbee.device.Device (actual device)
                    └── .device     # zigpy device with endpoints/clusters
```

### Nimly Lock Models
- **NimlyPRO** - Original model
- **NimlyPRO24** - 2024 version
- Manufacturer: "Onesti Products AS"
- Door Lock cluster: 0x0101

### Key Dependencies
- `homeassistant.components.zha` - ZHA integration
- `zigpy` - Zigbee protocol library (via ZHA)
- No external pip requirements

## Testing via SSH

### SSH Setup
The test Home Assistant instance is accessible via SSH:
```bash
# Host configured in ~/.ssh/config as "ha-local"
ssh ha-local
```

### Deploy and Test Workflow
```bash
# 1. Copy files to HA
scp custom_components/nimly_pro/*.py ha-local:/config/custom_components/nimly_pro/

# 2. Clear cache and restart
ssh ha-local "rm -rf /config/custom_components/nimly_pro/__pycache__ && ha core restart"

# 3. Wait for restart and check logs
sleep 30 && ssh ha-local "ha core logs --lines 100 2>&1" | grep -i nimly
```

### One-liner
```bash
scp custom_components/nimly_pro/*.py ha-local:/config/custom_components/nimly_pro/ && \
ssh ha-local "rm -rf /config/custom_components/nimly_pro/__pycache__ && ha core restart"
```

### Checking Logs
```bash
# All nimly-related logs
ssh ha-local "ha core logs --lines 200 2>&1" | grep -i nimly

# Errors only
ssh ha-local "ha core logs --lines 200 2>&1" | grep -i -E "(nimly.*error|error.*nimly)"

# Full recent logs
ssh ha-local "ha core logs --lines 50"
```

### Entity Registry
Check which entities are registered:
```bash
ssh ha-local "grep -i nimly /config/.storage/core.entity_registry"
```

## Common Pitfalls

### 1. ZHA API Changes
The ZHA integration internal API is not stable. When something breaks:
- Check `homeassistant/components/zha/` source code
- Look for `HAZHAData`, `ZHAGatewayProxy`, `ZHADeviceProxy` classes
- Update `helpers.py` to match current structure

### 2. Deprecated Imports
Common deprecations to watch for:
- `STATE_LOCKED`/`STATE_UNLOCKED` -> Use `LockState.LOCKED`/`LockState.UNLOCKED`
- `get_zha_gateway()` from ZHA -> Use custom helper in `helpers.py`
- `dt_util.timedelta` -> Use `from datetime import timedelta`

### 3. Device vs DeviceProxy
- `ZHADeviceProxy` - Wrapper with name, availability info
- `ZHADeviceProxy.device` - Actual `zha.zigbee.device.Device`
- `zha_device.device.device` - Underlying `zigpy` device with endpoints/clusters

Always get both and use appropriately:
```python
zha_device = get_zha_device(hass, ieee)  # ZHA device wrapper
zigpy_device = zha_device
if hasattr(zha_device, "device"):
    zigpy_device = zha_device.device  # For cluster access
```

## ZHA Integration
This integration depends on ZHA (Zigbee Home Automation). Key points:
- Locks must be paired with ZHA first
- Uses Zigbee cluster IDs (Door Lock cluster: 0x0101)
- Manufacturer: "Onesti Products AS"
- Models: "NimlyPRO", "NimlyPRO24"
