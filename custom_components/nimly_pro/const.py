"""Constants for the Nimly Touch Pro integration."""

# Integration domain
DOMAIN = "nimly_pro"

# Configuration
CONF_IEEE = "ieee"
CONF_DEVICE_PATH = "device_path"

# Zigbee Cluster Identifiers
DOORLOCK_CLUSTER_ID = "0x0101"
POWER_CLUSTER_ID = "0x0001"
BASIC_CLUSTER_ID = "0x0000"
OTA_CLUSTER_ID = "0x0019"
MANUFACTURER_SPECIFIC_CLUSTER_ID = "0xfea2"

# Attribute IDs from the diagnostics file
ATTR_LOCK_STATE = "0x0000"
ATTR_LED_SETTINGS = "0x0022"
ATTR_SOUND_VOLUME = "0x0024"
ATTR_DOOR_STATE = "0x0003"
ATTR_BATTERY_PERCENTAGE = "0x0021"
ATTR_CURRENT_FILE_VERSION = "0x0002"
ATTR_ENABLE_INSIDE_STATUS_LED = "0x002a"
ATTR_KEYPAD_OPERATION_EVENT_MASK = "0x0041"
ATTR_MANUAL_OPERATION_EVENT_MASK = "0x0043"
ATTR_RF_OPERATION_EVENT_MASK = "0x0042"
ATTR_AUTO_RELOCK_TIME = "0x0023"

# Event types (to be expanded based on documentation)
EVENT_TYPE_KEYPAD_UNLOCK = "keypad_unlock"
EVENT_TYPE_MANUAL_UNLOCK = "manual_unlock"
EVENT_TYPE_RF_UNLOCK = "rf_unlock"
EVENT_TYPE_AUTO_LOCK = "auto_lock"

# Entity naming
NAME_DOOR_STATE = "Door State"
NAME_FIRMWARE = "Firmware Version"
NAME_LAST_USER = "Last User"
NAME_LED_SETTINGS = "LED Settings"
NAME_SOUND_VOLUME = "Sound Volume"
NAME_AUTO_RELOCK = "Auto Relock Time"

# LED Settings options
LED_SETTINGS_OPTIONS = {
    0: "Off",
    1: "Low",
    2: "Medium", 
    3: "High"
}

# Default values
DEFAULT_AUTO_RELOCK_TIME = 30  # seconds
