"""Constants for the Netatmo Custom integration."""

# Integration domain
DOMAIN = "netatmo_custom"

# OAuth2 endpoints
OAUTH2_AUTHORIZE = "https://api.netatmo.com/oauth2/authorize"
OAUTH2_TOKEN = "https://api.netatmo.com/oauth2/token"
OAUTH2_SCOPES = ["read_thermostat", "write_thermostat"]

# API configuration
API_BASE_URL = "https://api.netatmo.com/api/"

# API endpoints
ENDPOINT_HOMESDATA = "homesdata"
ENDPOINT_HOMESTATUS = "homestatus"
ENDPOINT_SETROOMTHERMPOINT = "setroomthermpoint"
ENDPOINT_SETTHERMMODE = "setthermmode"

# Platforms
PLATFORMS = ["climate", "sensor", "binary_sensor"]

# Data storage keys
DATA_COORDINATOR = "coordinator"
DATA_API = "api"
DATA_HOME_ID = "home_id"

# Configuration keys
CONF_WEBHOOK_ID = "webhook_id"

# Preset modes (extending HA's built-in presets)
PRESET_FROST_GUARD = "Frost Guard"
PRESET_SCHEDULE = "schedule"
PRESET_MANUAL = "manual"

# Netatmo mode mappings
NETATMO_ROOM_MODES = {
    "manual": "Manual",
    "max": "Max",
    "off": "Off",
    "schedule": "Schedule",
    "home": "Home",
}

NETATMO_HOME_MODES = {
    "schedule": "Schedule",
    "away": "Away",
    "hg": "Frost Guard",
    "off": "Off",
}

# Temperature limits (Netatmo thermostat)
MIN_TEMP = 5.0
MAX_TEMP = 30.0
TEMP_STEP = 0.5

# Entity naming
ENTITY_PREFIX = "netatmo"

# Update intervals
UPDATE_INTERVAL = 60  # seconds

# Service names
SERVICE_SET_SCHEDULE = "set_schedule"
