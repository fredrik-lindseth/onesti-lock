"""Constants for Onesti Lock integration."""

DOMAIN = "onesti_lock"

CONF_IEEE = "ieee"

# Zigbee
DOORLOCK_CLUSTER_ID = 0x0101
ZHA_DOMAIN = "zha"

# Onesti hardware — all known whitelabel models
MAX_SLOTS = 1000  # ZCL slots 0-999 (per Nimly manual)
# Slots 0-2: reserved for master codes (per Nimly/EasyAccess manual)
# Slots 3-199: user codes
SLOT_FIRST_USER = 3
# Number of user slots to show as sensors in UI
NUM_USER_SLOTS = 10  # Shows slots 3-12
# All model_id strings from zigbee-herdsman-converters (onesti.ts)
# EasyAccess series: easyCodeTouch_v1, EasyCodeTouch, EasyFingerTouch
# Nimly series: NimlyPRO, NimlyPRO24, NimlyCode, NimlyTouch, NimlyIn, NimlyShared
SUPPORTED_MODELS = [
    "NimlyPRO",
    "NimlyPRO24",
    "NimlyCode",
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
SOURCE_UNKNOWN = "unknown"

# Operation event actions
ACTION_LOCK = "lock"
ACTION_UNLOCK = "unlock"
ACTION_UNKNOWN = "unknown"
