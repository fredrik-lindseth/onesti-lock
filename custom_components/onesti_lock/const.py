"""Constants for Onesti Lock integration."""

DOMAIN = "onesti_lock"

CONF_IEEE = "ieee"
# Per-lock option: how many slots from 0 up are master codes that set_pin,
# clear_pin and clear_slot must never touch. Naming is not affected.
CONF_RESERVED_SLOTS = "reserved_slots"
RESERVED_SLOTS_MIN = 1  # slot 0 is the master code on every model
RESERVED_SLOTS_MAX = 3

# Zigbee
DOORLOCK_CLUSTER_ID = 0x0101
ZHA_DOMAIN = "zha"

# Onesti hardware: all known whitelabel models
MAX_SLOTS = 1000  # ZCL slots 0-999 (per Nimly manual)
# Default first user slot, i.e. the default for CONF_RESERVED_SLOTS. The
# manuals differ per model: Touch Pro, PRO and Code reserve 000-002 as master
# codes, Code Pro only 000 (001-999 are user codes). The reported model string
# cannot pick between them (issue #5), so 3 is the safe default and the user
# lowers it per lock.
SLOT_FIRST_USER = 3
# Number of user slots to show as sensors in UI
NUM_USER_SLOTS = 10  # Shows slots 3-12
# Known model_id strings from zigbee-herdsman-converters (onesti.ts). This list
# is informational: it labels the hardware we know about and lets config flow
# warn about a model string nobody has seen before. It is not a discovery
# filter, because a Connect Module can report a sibling model name (issue #5: a
# NimlyCodePRO presenting itself as NimlyTwist), and every Onesti lock runs the
# same firmware on the same module either way.
SUPPORTED_MODELS = [
    "NimlyPRO",
    "NimlyPRO24",
    "NimlyCode",
    "NimlyCodePRO",
    "NimlyTouch",
    "NimlyIn",
    "NimlyShared",
    "easyCodeTouch_v1",
    "EasyCodeTouch",
    "EasyFingerTouch",
]
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

# Operation event sources (verified against Z2M converter)
SOURCE_ZIGBEE = "zigbee"
SOURCE_KEYPAD = "keypad"
SOURCE_FINGERPRINT = "fingerprint"
SOURCE_RFID = "rfid"
SOURCE_AUTO = "auto"
SOURCE_UNATTRIBUTED = "unattributed"
SOURCE_UNKNOWN = "unknown"

# Operation event actions
ACTION_LOCK = "lock"
ACTION_UNLOCK = "unlock"
ACTION_UNKNOWN = "unknown"
