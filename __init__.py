"""Netatmo Custom Thermostat integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow

from .api import NetatmoAPI, NetatmoAuthError
from .const import (
    CONF_WEBHOOK_ID,
    DATA_API,
    DATA_COORDINATOR,
    DATA_HOME_ID,
    DOMAIN,
    PLATFORMS,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import NetatmoDataUpdateCoordinator
from .webhook import async_setup_webhook, async_unregister_webhook

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Netatmo Custom from a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry with OAuth token

    Returns:
        True if setup successful
    """
    try:
        # Get OAuth2 implementation and create session for automatic token refresh
        implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
        oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

        # Initialize API client with OAuth session (handles token refresh)
        api = NetatmoAPI(hass, oauth_session)

        # Get home ID from homesdata
        homes_data = await api.async_get_homes_data()
        homes = homes_data.get("body", {}).get("homes", [])

        if not homes:
            raise ConfigEntryAuthFailed("No homes found in Netatmo account")

        home_id = homes[0]["id"]
        _LOGGER.info(f"Setting up Homelab Climate for home: {home_id}")

        # Setup coordinator for polling
        coordinator = NetatmoDataUpdateCoordinator(hass, api, home_id)

        # Fetch initial data
        await coordinator.async_config_entry_first_refresh()

        # Store coordinator and API in hass.data
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {
            DATA_COORDINATOR: coordinator,
            DATA_API: api,
            DATA_HOME_ID: home_id,
        }

        # Setup webhook if webhook_id exists
        webhook_id = entry.data.get(CONF_WEBHOOK_ID)
        if webhook_id:
            webhook_url = await async_setup_webhook(hass, webhook_id, coordinator)
            _LOGGER.warning(
                f"\n{'='*80}\n"
                f"HOMELAB CLIMATE - WEBHOOK SETUP\n"
                f"{'='*80}\n"
                f"Copy this URL to dev.netatmo.com > App Settings > Webhook URI:\n\n"
                f"  {webhook_url}\n\n"
                f"{'='*80}\n"
            )

        # Forward setup to platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Register services
        await async_setup_services(hass, entry)

        return True

    except NetatmoAuthError as err:
        _LOGGER.error(f"Authentication error during setup: {err}")
        raise ConfigEntryAuthFailed(err)
    except Exception as err:
        _LOGGER.error(f"Error setting up Netatmo Custom: {err}")
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry to unload

    Returns:
        True if unload successful
    """
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Unregister webhook
        webhook_id = entry.data.get(CONF_WEBHOOK_ID)
        if webhook_id:
            async_unregister_webhook(hass, webhook_id)

        # Remove data
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_setup_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up services for Netatmo Custom integration.

    Args:
        hass: Home Assistant instance
        entry: Config entry
    """

    async def async_handle_set_schedule(call):
        """Handle set_schedule service call."""
        entity_id = call.data.get("entity_id")
        schedule_name = call.data.get("schedule_name")

        if not entity_id or not schedule_name:
            _LOGGER.error("Missing required service parameters")
            return

        # Get API and home_id from hass.data
        entry_data = hass.data[DOMAIN].get(entry.entry_id)
        if not entry_data:
            _LOGGER.error("Integration data not found")
            return

        api: NetatmoAPI = entry_data[DATA_API]
        home_id: str = entry_data[DATA_HOME_ID]
        coordinator: NetatmoDataUpdateCoordinator = entry_data[DATA_COORDINATOR]

        try:
            # Get schedules
            schedules = await api.async_get_schedules(home_id)

            # Find schedule by name
            schedule_id = None
            for schedule in schedules:
                if schedule.get("name") == schedule_name:
                    schedule_id = schedule["id"]
                    break

            if schedule_id is None:
                _LOGGER.error(
                    f"Schedule '{schedule_name}' not found. Available schedules: "
                    f"{[s.get('name') for s in schedules]}"
                )
                return

            # Set schedule
            await api.async_set_therm_mode(
                home_id, mode="schedule", schedule_id=schedule_id
            )

            # Refresh coordinator
            await coordinator.async_request_refresh()

            _LOGGER.info(f"Set schedule to '{schedule_name}' (ID: {schedule_id})")

        except Exception as err:
            _LOGGER.error(f"Error setting schedule: {err}")

    # Register service
    if not hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_SCHEDULE, async_handle_set_schedule
        )
