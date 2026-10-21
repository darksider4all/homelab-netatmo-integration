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
CONF_HOME_ID = "home_id"

# Preset modes (extending HA's built-in presets)
PRESET_FROST_GUARD = "frost_guard"
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
    "hg": "frost_guard",
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

# Climate state-change verification (Netatmo can be slow to apply setpoints)
VERIFY_PROPAGATION_DELAY = 4  # seconds to wait before re-reading after an API call
VERIFY_SETTLE_DELAY = 1  # seconds to wait after a coordinator refresh
VERIFY_RETRY_BASE_DELAY = 4  # base seconds between verification retries (scaled by attempt)
VERIFY_MAX_RETRIES = 4  # additional verification attempts after the first

# Manual setpoint duration.
# Netatmo applies the home's `therm_setpoint_default_duration` whenever
# setroomthermpoint is called without an explicit endtime; that is the
# "cooldown" shown in the Netatmo app (90 min on this home). Manual setpoints
# from HA/Google now send that same duration explicitly, so the override lasts
# exactly as long as the app's setting — change it in the app, not here.
MANUAL_SETPOINT_FALLBACK_MINUTES = 90  # used if homesdata omits the setting
MANUAL_SETPOINT_MAX_MINUTES = 24 * 60  # sanity clamp on a bad API value

# Post-write setpoint guard.
# Netatmo has been observed to accept a manual setpoint, report the room back in
# "schedule" mode ~10 s later and stop the boiler (2026-10-20: 24 °C at 22:37:18,
# schedule/15 °C at 22:37:28). The verification loop only checks the value at
# write time, so such a cancellation was shown verbatim until the next command.
# Hold the requested value for the guard window and, if the room falls back to
# its schedule inside it, re-assert the setpoint once (never in a loop).
SETPOINT_GUARD_WINDOW_SECONDS = 60
SETPOINT_GUARD_POLL_SECONDS = 5
OPTIMISTIC_TEMP_HOLD_SECONDS = 60


# Webhook handling
MAX_WEBHOOK_BODY_BYTES = 256 * 1024  # reject webhook payloads larger than this

# Entity availability
MAX_CONSECUTIVE_FAILURES = 5  # mark entities unavailable above this many failures

# Service names
SERVICE_SET_SCHEDULE = "set_schedule"
