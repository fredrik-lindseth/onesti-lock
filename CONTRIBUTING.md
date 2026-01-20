# Contributing to Nimly Touch Pro Integration

## Development Setup

### Prerequisites
- Home Assistant instance with ZHA integration configured
- A Nimly Touch Pro lock paired with ZHA
- SSH access to your Home Assistant instance

### Local Development Workflow

Instead of releasing to HACS for every change, you can copy the integration directly to your Home Assistant instance for testing.

#### 1. Set up SSH access

Configure SSH access to your Home Assistant instance. Add to `~/.ssh/config`:

```
Host ha-local
    HostName <your-ha-ip>
    User root
    Port 22222
```

#### 2. Deploy changes

Copy the integration files to Home Assistant:

```bash
scp custom_components/nimly_pro/*.py ha-local:/config/custom_components/nimly_pro/
```

#### 3. Clear cache and restart

Clear Python cache and restart Home Assistant to load changes:

```bash
ssh ha-local "rm -rf /config/custom_components/nimly_pro/__pycache__ && ha core restart"
```

#### 4. Check logs

Monitor the logs for errors:

```bash
ssh ha-local "ha core logs --lines 100 2>&1" | grep -i nimly
```

### One-liner for deploy and restart

```bash
scp custom_components/nimly_pro/*.py ha-local:/config/custom_components/nimly_pro/ && \
ssh ha-local "rm -rf /config/custom_components/nimly_pro/__pycache__ && ha core restart"
```

## Project Structure

```
custom_components/nimly_pro/
├── __init__.py       # Integration setup
├── config_flow.py    # Configuration UI flow
├── const.py          # Constants and Zigbee cluster IDs
├── helpers.py        # ZHA device access helpers
├── lock.py           # Lock entity
├── sensor.py         # Sensor entities
├── binary_sensor.py  # Binary sensor entities
├── select.py         # Select entities (LED, sound volume)
├── number.py         # Number entities (auto-relock time)
├── manifest.json     # Integration metadata and version
└── strings.json      # UI strings
```

## ZHA Device Access (HA 2024.x+)

The ZHA integration changed its internal structure in Home Assistant 2024.x. Here's how to access devices:

```python
from .helpers import get_zha_device

# Get the ZHA device wrapper
zha_device = get_zha_device(hass, ieee)

# For name/availability, use zha_device directly
device_name = getattr(zha_device, 'name', 'Unknown')

# For cluster access, get the underlying zigpy device
zigpy_device = zha_device
if hasattr(zha_device, "device"):
    zigpy_device = zha_device.device

# Access endpoints and clusters
for endpoint_id, endpoint in zigpy_device.endpoints.items():
    if endpoint_id != 0:  # Skip ZDO endpoint
        for cluster in endpoint.in_clusters.values():
            if cluster.cluster_id == DOORLOCK_CLUSTER_ID:
                # Found the door lock cluster
                pass
```

## Release Process

1. Make and test your changes locally
2. Update version in `custom_components/nimly_pro/manifest.json`
3. Commit changes with a descriptive message
4. Push to GitHub (triggers automatic release via GitHub Actions)

**Important:** Always ask before pushing, as push triggers a new release!

## Code Style

- Use English for all code, comments, and documentation
- Follow Home Assistant coding conventions
- Use `_LOGGER.debug()` for development logging, not `warning()`
