# Nimly Touch Pro Integration for Home Assistant

This custom integration enhances the functionality of Nimly Touch Pro locks in Home Assistant, providing access to additional features not available in the standard ZHA integration.

## Features

- **Enhanced Lock Control**
  - Basic lock/unlock functionality
  - Tracks who unlocked the door (Home Assistant, keypad, manual, etc.)
  - Last user tracking with timestamp

- **Sensors**
  - Door state sensor (separate from lock state)
  - Firmware version sensor
  - Battery information

- **Settings Control**
  - LED brightness settings (Off/Low/Medium/High)
  - Sound volume settings (Off/Low/Medium/High)
  - Auto-relock time configuration (0-3600 seconds)

## Requirements

- Home Assistant with ZHA integration
- Nimly Touch Pro lock already paired to ZHA

## Installation

### HACS Installation (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance
2. Add this repository as a custom repository in HACS:
   - Go to HACS → Integrations
   - Click on the three dots in the upper right corner
   - Select "Custom repositories"
   - Add the URL of this repository
   - Category: Integration
3. Click "Add"
4. Search for "Nimly Touch Pro" in HACS and install it
5. Restart Home Assistant

### Manual Installation

1. Download this repository as a ZIP file
2. Extract the ZIP file
3. Copy the `custom_components/nimly_pro` directory to your Home Assistant's `custom_components` directory
4. Restart Home Assistant

## Configuration

1. Go to Settings → Devices & Services
2. Click "Add Integration" and search for "Nimly Touch Pro"
3. Select your Nimly Touch Pro lock from the list of ZHA devices

## Troubleshooting

- If the integration doesn't appear after installation, try clearing your browser cache and restarting Home Assistant
- Check the Home Assistant logs for any error messages related to the integration
- Make sure your lock is properly paired with ZHA before adding this integration

## Support

For issues, feature requests, or contributions, please use the GitHub issues section.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
