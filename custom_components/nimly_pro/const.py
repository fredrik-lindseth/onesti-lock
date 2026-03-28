"""Constants for Nimly PRO integration."""

DOMAIN = "nimly_pro"

CONF_IEEE = "ieee"

# Zigbee
DOORLOCK_CLUSTER_ID = 0x0101
ZHA_DOMAIN = "zha"

# Nimly hardware
NUM_SLOTS = 10  # Slots 0-9
SUPPORTED_MODELS = ["NimlyPRO", "NimlyPRO24"]
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

# Operation event sources
SOURCE_KEYPAD = "keypad"
SOURCE_RF = "rf"
SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"
SOURCE_UNKNOWN = "unknown"

# Operation event actions
ACTION_LOCK = "lock"
ACTION_UNLOCK = "unlock"
ACTION_UNKNOWN = "unknown"
