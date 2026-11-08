"""Netatmo Custom Thermostat integration."""

import asyncio
import contextlib
from dataclasses import dataclass
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
    DOMAIN,
    PLATFORMS,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import NetatmoDataUpdateCoordinator
from .webhook import async_setup_webhook, async_unregister_webhook

_LOGGER = logging.getLogger(__name__)

WEBHOOK_REGISTER_ATTEMPTS = 2
WEBHOOK_REGISTER_RETRY_DELAY = 5  # seconds


async def _async_register_netatmo_webhook(api: NetatmoAPI, webhook_url: str) -> bool:
    """Tell Netatmo where to push events.

    One retry, never fatal: if this fails the integration keeps polling at the old
    interval, so a broken registration degrades instead of taking the entry down (#11).
    """
    for attempt in range(1, WEBHOOK_REGISTER_ATTEMPTS + 1):
        try:
            await api.async_add_webhook(webhook_url)
        except Exception as err:
            if attempt == WEBHOOK_REGISTER_ATTEMPTS:
                _LOGGER.warning("Netatmo webhook registration failed, staying on polling: %s", err)
                return False
            await asyncio.sleep(WEBHOOK_REGISTER_RETRY_DELAY)
        else:
            _LOGGER.info("Netatmo will push events to %s", webhook_url)
            return True
    return False


def relay_device_id(hass: HomeAssistant, relay_module_id: str | None) -> str | None:
    """Return the registry id of the relay a module hangs from.

    `via_device` (an identifier tuple) is deprecated and stops working in HA 2027.8;
    the registry now only accepts the parent's device id, so the id captured when the
    relay device was registered is looked up here instead.
    """
    if not relay_module_id:
        return None
    store = hass.data.get(DOMAIN) or {}
    return (store.get("relay_devices") or {}).get(relay_module_id)


@dataclass
class NetatmoRuntimeData:
    """Runtime data attached to a loaded config entry."""

    coordinator: NetatmoDataUpdateCoordinator
    api: NetatmoAPI
    home_id: str


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

        # Pre-register relay devices so modules can hang off them by device id.
        device_registry = dr.async_get(hass)
        homes_data = coordinator.data.get("homes_data", {}).get("body", {}).get("homes", [])
        relay_devices: dict[str, str] = {}
        for home in homes_data:
            if home["id"] == home_id:
                for module in home.get("modules", []):
                    if module.get("type") == "NAPlug":
                        relay = device_registry.async_get_or_create(
                            config_entry_id=entry.entry_id,
                            identifiers={(DOMAIN, module["id"])},
                            manufacturer="Netatmo",
                            model="Relay",
                            name=module.get("name", "Netatmo Relay"),
                            configuration_url="https://my.netatmo.com",
                        )
                        relay_devices[module["id"]] = relay.id
                break

        # Merge rather than replace: a second home (second config entry) must not
        # drop the first home's relay ids, or those modules would lose their parent.
        hass.data.setdefault(DOMAIN, {}).setdefault("relay_devices", {}).update(relay_devices)

        # Store runtime data on the config entry (ConfigEntry.runtime_data).
        entry.runtime_data = NetatmoRuntimeData(coordinator=coordinator, api=api, home_id=home_id)

        # Setup webhook if webhook_id exists
        webhook_id = entry.data.get(CONF_WEBHOOK_ID)
        if webhook_id:
            client_secret = getattr(implementation, "client_secret", None)
            webhook_url = await async_setup_webhook(hass, webhook_id, coordinator, client_secret)
            if webhook_url:
                _LOGGER.info("Webhook URL: %s", webhook_url)
                if await _async_register_netatmo_webhook(api, webhook_url):
                    coordinator.enable_reconcile_polling()

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
        # Unregister webhook, and tell Netatmo to stop pushing to it.
        webhook_id = entry.data.get(CONF_WEBHOOK_ID)
        if webhook_id:
            async_unregister_webhook(hass, webhook_id)
            runtime = entry.runtime_data
            if runtime is not None:
                with contextlib.suppress(Exception):
                    await runtime.api.async_drop_webhook()

        # Release runtime data
        entry.runtime_data = None

        # Unregister service if this is the last loaded entry
        if not any(
            other.entry_id != entry.entry_id and other.runtime_data is not None
            for other in hass.config_entries.async_entries(DOMAIN)
        ) and hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
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

        # Get API and home_id from the entry's runtime data
        entry_data = entry.runtime_data
        if entry_data is None:
            raise HomeAssistantError("Netatmo integration data not found")

        api: NetatmoAPI = entry_data.api
        home_id: str = entry_data.home_id
        coordinator: NetatmoDataUpdateCoordinator = entry_data.coordinator

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
