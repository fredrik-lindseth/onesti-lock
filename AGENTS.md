# Agent Instructions for Nimly Touch Pro Integration

## Project Description
Home Assistant custom integration for Nimly Touch Pro smart locks, providing extended functionality beyond the standard ZHA integration:
- **Lock Control** - Lock/unlock with user tracking
- **Sensors** - Door state, battery, firmware version
- **Settings** - LED brightness, sound volume, auto-relock time

## Language
- Code: English (variable names, functions, code comments)
- Commit messages: English
- Documentation: English
- Communication: English

## Git Preferences
- Write descriptive commit messages in English
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
| File | Description |
|------|-------------|
| `custom_components/nimly_pro/manifest.json` | Version and dependencies |
| `custom_components/nimly_pro/config_flow.py` | Configuration flow for adding locks |
| `custom_components/nimly_pro/const.py` | Constants and Zigbee cluster IDs |
| `custom_components/nimly_pro/lock.py` | Lock entity implementation |
| `custom_components/nimly_pro/sensor.py` | Sensor entities |
| `custom_components/nimly_pro/strings.json` | UI strings for config flow |

## ZHA Integration
This integration depends on ZHA (Zigbee Home Automation). Key points:
- Locks must be paired with ZHA first
- Uses Zigbee cluster IDs (Door Lock cluster: 0x0101)
- Manufacturer: "Onesti Products AS"
- Models: "NimlyPRO", "NimlyPRO24"

## Testing
- Verify the integration loads without errors in Home Assistant
- Test config flow with ZHA gateway available
- Verify lock entities respond correctly
