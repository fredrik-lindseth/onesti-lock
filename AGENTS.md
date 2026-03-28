# Agent Instructions for Nimly Touch Pro Integration

## Generelle regler
Se OpenCode "developer" agent for standard utviklingspraksis.

## Prosjektspesifikk

## Prosjektbeskrivelse
Home Assistant custom integration for Nimly Touch Pro smart locks som gir PIN-kode management via services. ZHA håndterer grunnleggende låskontroll (lås/lås opp, sensorer).

**Arkitektur:**
- `PLATFORMS = []` - Ingen egne entiteter, ZHA håndterer dette
- Services for PIN-kode management (`nimly_pro.set_pin_code`, etc.)
- Bruker ZHA/zigpy for Zigbee-kommunikasjon

## Important Files
| File                                         | Description                         |
|----------------------------------------------|-------------------------------------|
| `custom_components/nimly_pro/manifest.json`  | Version and dependencies            |
| `custom_components/nimly_pro/__init__.py`    | Entry point, service registration   |
| `custom_components/nimly_pro/services.py`    | PIN code service implementations    |
| `custom_components/nimly_pro/services.yaml`  | Service descriptions for HA UI      |
| `custom_components/nimly_pro/helpers.py`     | ZHA device/cluster access helpers   |
| `custom_components/nimly_pro/config_flow.py` | Configuration flow for adding locks |
| `custom_components/nimly_pro/const.py`       | Constants and Zigbee cluster IDs    |
| `custom_components/nimly_pro/strings.json`   | UI strings for config flow          |

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
# 1. Deploy files (use cat redirect - scp may not work with rules)
ssh ha-local "cat > /config/custom_components/nimly_pro/services.py" < custom_components/nimly_pro/services.py
ssh ha-local "cat > /config/custom_components/nimly_pro/helpers.py" < custom_components/nimly_pro/helpers.py

# 2. Clear cache and restart
ssh ha-local "rm -rf /config/custom_components/nimly_pro/__pycache__ && ha core restart"

# 3. Check logs after restart
ssh ha-local "ha core logs --lines 100" | grep -i nimly
```

### Checking Logs
```bash
# All nimly-related logs
ssh ha-local "ha core logs --lines 200" | grep -i nimly

# Errors only
ssh ha-local "ha core logs --lines 200" | grep -i -E "(nimly.*error|error.*nimly)"
```

## Development Notes

### ZCL Door Lock Cluster (0x0101)
Nimly implements the standard ZCL Door Lock cluster. Key commands:

| Command ID | Name | Parameters |
|------------|------|------------|
| 0x00 | lock_door | pin_code? |
| 0x01 | unlock_door | pin_code? |
| 0x05 | set_pin_code | user_id, user_status, user_type, pin_code |
| 0x06 | get_pin_code | user_id |
| 0x07 | clear_pin_code | user_id |
| 0x08 | clear_all_pin_codes | - |
| 0x09 | set_user_status | user_id, user_status |
| 0x0A | get_user_status | user_id |

### Batteridrevne enheter og timeout
Nimly er en batteridrevet EndDevice som sover for å spare strøm. Dette gir utfordringer:

1. **Direkte cluster-kall får ofte timeout** - Enheten sover
2. **ZHA lock/unlock fungerer** - ZHA bruker sannsynligvis en annen mekanisme
3. **Mulige løsninger:**
   - Bruk `zha_device.issue_cluster_command()` hvis tilgjengelig
   - Undersøk hvordan ZHA sin lock-entity sender kommandoer
   - Vurder å bruke ZHA's websocket API

### Kjente problemer
- PIN-kommandoer får timeout selv om lock/unlock fungerer via ZHA
- Må undersøke hvordan ZHA sender lock-kommandoer for å kopiere mekanismen

### Input validering
Alltid trim IEEE-adresser: `ieee = ieee.strip()` - UI kan legge til mellomrom.

## Common Pitfalls

### 1. ZHA API Changes
The ZHA integration internal API is not stable. When something breaks:
- Check `homeassistant/components/zha/` source code
- Look for `HAZHAData`, `ZHAGatewayProxy`, `ZHADeviceProxy` classes
- Update `helpers.py` to match current structure

### 2. Device vs DeviceProxy
- `ZHADeviceProxy` - Wrapper with name, availability info
- `ZHADeviceProxy.device` - Actual `zha.zigbee.device.Device`
- `zha_device.device.device` - Underlying `zigpy` device with endpoints/clusters

```python
zha_device, cluster, endpoint_id = get_zha_device_and_cluster(hass, ieee)
# zha_device = ZHADeviceProxy (for issue_cluster_command)
# cluster = zigpy cluster (for direct calls)
# endpoint_id = endpoint number (usually 11 for Nimly)
```

## ZHA Integration
This integration depends on ZHA (Zigbee Home Automation). Key points:
- Locks must be paired with ZHA first
- Uses Zigbee cluster IDs (Door Lock cluster: 0x0101)
- Manufacturer: "Onesti Products AS"
- Models: "NimlyPRO", "NimlyPRO24"

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
Use 'bd' for task tracking
