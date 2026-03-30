# Nimly PRO Integration v2 — Design

## Problem

The existing integration is service-only with no entities, no slot-to-name mapping, and ZHA cluster command responses crash due to a Nimly firmware quirk (returns unexpected response format causing `IndexError: tuple index out of range` in zigpy). Users see "User 0 locked" instead of "Kari locked the door with PIN".

## Approach

Entity-based integration with a user-per-slot model. ZHA keeps ownership of the lock entity. We add slot sensors, an activity sensor, and services for PIN management.

## Data Model

Stored in config entry options (persisted in `.storage`):

```python
{
  "slots": {
    "0": {"name": "Kari", "has_pin": true, "has_rfid": false},
    "1": {"name": "Anna", "has_pin": true, "has_rfid": false},
    "2": {"name": "", "has_pin": false, "has_rfid": false},
    # ... slots 0-9
  }
}
```

- 10 slots (0-9), matching Nimly hardware limits
- `name`: displayed in logs and sensors. Empty = "Slot X"
- `has_pin`/`has_rfid`: tracked locally (cannot query lock reliably due to quirk)
- Set optimistically after command is sent

## Entities

Per configured lock:

### Sensors

- `sensor.<lock>_slot_0` through `sensor.<lock>_slot_9`
  - State: user name ("Kari") or "Ledig"
  - Attributes: `has_pin`, `has_rfid`, `slot_id`

- `sensor.<lock>_siste_aktivitet`
  - State: human-readable string ("Kari låste opp med kode")
  - Attributes: `user_name`, `user_slot`, `action`, `source`, `timestamp`
  - Updated via `zha_event` listener (operation_event_notification 0x0020)

### No lock entity

ZHA's `lock.<name>` is kept for lock/unlock. No conflict.

## Services

- `nimly_pro.set_pin(slot, name, code)` — ZCL 0x05, updates slot data
- `nimly_pro.clear_pin(slot)` — ZCL 0x07, updates slot data
- `nimly_pro.set_name(slot, name)` — updates mapping only, no ZCL command
- `nimly_pro.clear_slot(slot)` — removes PIN + RFID + name, full slot reset

## ZHA Quirk Handling

All cluster commands wrapped in try/except catching `IndexError` and `asyncio.TimeoutError`. The command reaches the lock even when response parsing fails. Slot state updated optimistically after send.

## Event Listening

1. Register listener on `zha_event` filtered by lock's IEEE address
2. On `operation_event_notification` (0x0020): look up `user_id` → name from slot data
3. Update `sensor.<lock>_siste_aktivitet`
4. Fire `nimly_pro_lock_activity` HA event for automations

Unknown user: "Ukjent (slot 3)". Manual operation: "Manuell opplåsing".

## Config Flow

1. User adds integration
2. Shows list of Onesti/Nimly devices from ZHA
3. Select lock → stores IEEE, creates 10 slot sensors + activity sensor

## File Structure

```
custom_components/nimly_pro/
├── __init__.py          # Setup, event listener, slot storage
├── manifest.json        # Domain, dependencies: [zha]
├── config_flow.py       # Select ZHA lock → creates entry
├── const.py             # Cluster IDs, slot count, domain
├── coordinator.py       # Slot data CRUD, ZHA cluster wrapper
├── sensor.py            # Slot sensors + activity sensor
├── services.py          # set_pin, clear_pin, set_name, clear_slot
├── services.yaml        # Service descriptions for HA UI
├── strings.json         # UI strings
└── translations/
    └── en.json
```

## Dependencies

Only `zha`. No external packages.

## Future

- RFID support (set_rfid_code/clear_rfid_code) — data model already supports it
- Time-limited guest access (temporary PINs with expiry automations)
- Dashboard example card in README

## Device Info

- Manufacturer: Onesti Products AS
- Models: NimlyPRO, NimlyPRO24
- Zigbee endpoint: 11
- Door Lock cluster: 0x0101
- Battery-powered EndDevice (causes timeouts)
