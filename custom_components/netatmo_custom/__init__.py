"""Netatmo Custom Thermostat integration."""

import contextlib
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import device_registry as dr

from .api import NetatmoAPI, NetatmoAPIError, NetatmoAuthError
from .const import (
    CONF_HOME_ID,
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

        # Get home ID stored during config flow
        home_id = entry.data.get(CONF_HOME_ID)
        if not home_id:
            raise ConfigEntryAuthFailed(
                "No home ID in config entry — please re-add the integration"
            )

        _LOGGER.info("Setting up Homelab Climate integration")
        _LOGGER.debug("Configured home id: %s", home_id)

        # Setup coordinator for polling
        coordinator = NetatmoDataUpdateCoordinator(hass, api, home_id)

        # Fetch initial data
        await coordinator.async_config_entry_first_refresh()

        # Pre-register relay devices so via_device references don't warn.
        device_registry = dr.async_get(hass)
        homes_data = coordinator.data.get("homes_data", {}).get("body", {}).get("homes", [])
        for home in homes_data:
            if home["id"] == home_id:
                for module in home.get("modules", []):
                    if module.get("type") == "NAPlug":
                        device_registry.async_get_or_create(
                            config_entry_id=entry.entry_id,
                            identifiers={(DOMAIN, module["id"])},
                            manufacturer="Netatmo",
                            model="Relay",
                            name=module.get("name", "Netatmo Relay"),
                            configuration_url="https://my.netatmo.com",
                        )
                break

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
            client_secret = getattr(implementation, "client_secret", None)
            webhook_url = await async_setup_webhook(hass, webhook_id, coordinator, client_secret)
            if webhook_url:
                _LOGGER.info(
                    "Netatmo webhook registered. " "Webhook URL for dev.netatmo.com: %s",
                    webhook_url,
                )

        # Forward setup to platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Register services
        await async_setup_services(hass, entry)

        return True

    except (ConfigEntryAuthFailed, ConfigEntryNotReady):
        # Let Home Assistant handle reauth / retry signalling.
        raise
    except NetatmoAuthError as err:
        _LOGGER.error("Authentication error during setup: %s", err)
        raise ConfigEntryAuthFailed(str(err)) from err
    except Exception as err:
        # Treat unexpected setup failures as transient so HA retries instead of
        # silently disabling the entry.
        _LOGGER.exception("Error setting up Netatmo Custom")
        raise ConfigEntryNotReady(f"Error setting up Netatmo Custom: {err}") from err


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

        # Remove data (use pop with default to avoid KeyError)
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Unregister service if this is the last entry
        if not hass.data[DOMAIN] and hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
            hass.services.async_remove(DOMAIN, SERVICE_SET_SCHEDULE)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry to the current schema.

    There is only one schema version today; this hook is in place so future
    breaking data changes can be migrated without orphaning existing entries.
    """
    if entry.version == 1:
        return True

    # Unknown (newer) version — refuse rather than corrupt data.
    _LOGGER.error("Cannot downgrade config entry from version %s", entry.version)
    return False


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up when a config entry is removed.

    Platforms and the webhook are already torn down in async_unload_entry; this
    ensures the webhook registration is gone even if the entry is removed while
    not loaded.
    """
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if webhook_id:
        # May already be unregistered if the entry was loaded.
        with contextlib.suppress(ValueError, KeyError):
            async_unregister_webhook(hass, webhook_id)


async def async_setup_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up services for Netatmo Custom integration.

    Args:
        hass: Home Assistant instance
        entry: Config entry
    """

    async def async_handle_set_schedule(call: ServiceCall) -> None:
        """Handle set_schedule service call."""
        entity_id = call.data.get("entity_id")
        schedule_name = call.data.get("schedule_name")

        if not entity_id or not schedule_name:
            raise ServiceValidationError("Both 'entity_id' and 'schedule_name' are required")

        # Get API and home_id from hass.data
        entry_data = hass.data[DOMAIN].get(entry.entry_id)
        if not entry_data:
            raise HomeAssistantError("Netatmo integration data not found")

        api: NetatmoAPI = entry_data[DATA_API]
        home_id: str = entry_data[DATA_HOME_ID]
        coordinator: NetatmoDataUpdateCoordinator = entry_data[DATA_COORDINATOR]

        try:
            schedules = await api.async_get_schedules(home_id)
        except NetatmoAPIError as err:
            raise HomeAssistantError(f"Could not fetch Netatmo schedules: {err}") from err

        # Find schedule by name
        schedule_id = next((s["id"] for s in schedules if s.get("name") == schedule_name), None)

        if schedule_id is None:
            available = ", ".join(sorted(s.get("name", "?") for s in schedules))
            raise ServiceValidationError(
                f"Schedule '{schedule_name}' not found. Available schedules: {available}"
            )

        try:
            await api.async_set_therm_mode(home_id, mode="schedule", schedule_id=schedule_id)
        except NetatmoAPIError as err:
            raise HomeAssistantError(f"Failed to set schedule: {err}") from err

        # Refresh coordinator
        await coordinator.async_request_refresh()
        _LOGGER.info("Set schedule to '%s'", schedule_name)

    # Register service
    if not hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, async_handle_set_schedule)
