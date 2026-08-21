"""Tests for integration setup-lifecycle helpers (migrate / remove)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
import pytest

from custom_components.netatmo_custom import (
    DOMAIN,
    PLATFORMS,
    SERVICE_SET_SCHEDULE,
    async_migrate_entry,
    async_remove_entry,
    async_setup_entry,
    async_setup_services,
    async_unload_entry,
)


async def test_migrate_entry_current_version(hass):
    """A current-version (1) entry needs no migration."""
    entry = MagicMock(version=1)
    assert await async_migrate_entry(hass, entry) is True


async def test_migrate_entry_future_version_refused(hass):
    """A newer-than-known version is refused rather than corrupted."""
    entry = MagicMock(version=2)
    assert await async_migrate_entry(hass, entry) is False


async def test_remove_entry_unregisters_webhook(hass):
    """Removing an entry unregisters its webhook."""
    entry = MagicMock()
    entry.data = {"webhook_id": "wh-123"}
    with patch("custom_components.netatmo_custom.async_unregister_webhook") as unregister:
        await async_remove_entry(hass, entry)
    unregister.assert_called_once_with(hass, "wh-123")


async def test_remove_entry_handles_missing_webhook(hass):
    """Removing an entry without a webhook id is a no-op."""
    entry = MagicMock()
    entry.data = {}
    # Should not raise.
    await async_remove_entry(hass, entry)


def _runtime_entry(entry_id="entry-1", home_id="home-1", webhook_id=None):
    """Build a config entry carrying runtime data (post-refactor shape)."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"home_id": home_id, **({"webhook_id": webhook_id} if webhook_id else {})}
    entry.runtime_data = SimpleNamespace(coordinator=MagicMock(), api=MagicMock(), home_id=home_id)
    return entry


async def test_setup_entry_attaches_runtime_data(hass, mock_oauth_session):
    """Setup stores the coordinator/api/home_id on entry.runtime_data."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {"home_id": "home-1", "webhook_id": "wh-1"}

    api = MagicMock()
    coordinator = MagicMock()
    coordinator.data = {"homes_data": {"body": {"homes": []}}}
    coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)

    with (
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            return_value=MagicMock(client_secret="secret"),
        ),
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow.OAuth2Session",
            return_value=mock_oauth_session,
        ),
        patch("custom_components.netatmo_custom.NetatmoAPI", return_value=api),
        patch(
            "custom_components.netatmo_custom.NetatmoDataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch("custom_components.netatmo_custom.dr.async_get", return_value=MagicMock()),
        patch(
            "custom_components.netatmo_custom.async_setup_webhook",
            new=AsyncMock(return_value="https://example.com/api/webhook/wh-1"),
        ) as setup_webhook,
        patch("custom_components.netatmo_custom.async_setup_services", new=AsyncMock()),
    ):
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        result = await async_setup_entry(hass, entry)

    assert result is True
    assert entry.runtime_data is not None
    assert entry.runtime_data.coordinator is coordinator
    assert entry.runtime_data.api is api
    assert entry.runtime_data.home_id == "home-1"
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(entry, PLATFORMS)
    setup_webhook.assert_awaited_once()


async def test_setup_entry_without_webhook_id_skips_webhook(hass, mock_oauth_session):
    """An entry without a webhook id skips webhook registration."""
    entry = MagicMock()
    entry.entry_id = "entry-2"
    entry.data = {"home_id": "home-1"}

    coordinator = MagicMock()
    coordinator.data = {"homes_data": {"body": {"homes": []}}}
    coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)

    with (
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            return_value=MagicMock(client_secret=None),
        ),
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow.OAuth2Session",
            return_value=mock_oauth_session,
        ),
        patch("custom_components.netatmo_custom.NetatmoAPI", return_value=MagicMock()),
        patch(
            "custom_components.netatmo_custom.NetatmoDataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch("custom_components.netatmo_custom.dr.async_get", return_value=MagicMock()),
        patch(
            "custom_components.netatmo_custom.async_setup_webhook", new=AsyncMock()
        ) as setup_webhook,
        patch("custom_components.netatmo_custom.async_setup_services", new=AsyncMock()),
    ):
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        result = await async_setup_entry(hass, entry)

    assert result is True
    setup_webhook.assert_not_awaited()


async def test_setup_entry_missing_home_id_raises_auth_failed(hass, mock_oauth_session):
    """An entry without a home id cannot be set up (reauth required)."""
    entry = MagicMock()
    entry.entry_id = "entry-3"
    entry.data = {}

    with (
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow.OAuth2Session",
            return_value=mock_oauth_session,
        ),
        patch("custom_components.netatmo_custom.NetatmoAPI", return_value=MagicMock()),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_entry_registers_relay_device(hass, mock_oauth_session):
    """A NAPlug module in the payload pre-registers a relay device."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {"home_id": "home-1"}

    coordinator = MagicMock()
    coordinator.data = {
        "homes_data": {
            "body": {
                "homes": [
                    {
                        "id": "home-1",
                        "modules": [{"id": "plug-1", "type": "NAPlug", "name": "Relay"}],
                    }
                ]
            }
        }
    }
    coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)
    registry = MagicMock()

    with (
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow.OAuth2Session",
            return_value=mock_oauth_session,
        ),
        patch("custom_components.netatmo_custom.NetatmoAPI", return_value=MagicMock()),
        patch(
            "custom_components.netatmo_custom.NetatmoDataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch("custom_components.netatmo_custom.dr.async_get", return_value=registry),
        patch("custom_components.netatmo_custom.async_setup_services", new=AsyncMock()),
    ):
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        result = await async_setup_entry(hass, entry)

    assert result is True
    registry.async_get_or_create.assert_called_once()
    call_kwargs = registry.async_get_or_create.call_args.kwargs
    assert call_kwargs["config_entry_id"] == "entry-1"
    assert call_kwargs["identifiers"] == {("netatmo_custom", "plug-1")}
    assert call_kwargs["model"] == "Relay"


async def test_setup_entry_auth_error_raises_auth_failed(hass, mock_oauth_session):
    """A Netatmo auth failure during setup surfaces as ConfigEntryAuthFailed."""
    from custom_components.netatmo_custom.api import NetatmoAuthError

    entry = MagicMock()
    entry.entry_id = "entry-4"
    entry.data = {"home_id": "home-1"}

    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(side_effect=NetatmoAuthError("denied"))

    with (
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow.OAuth2Session",
            return_value=mock_oauth_session,
        ),
        patch("custom_components.netatmo_custom.NetatmoAPI", return_value=MagicMock()),
        patch(
            "custom_components.netatmo_custom.NetatmoDataUpdateCoordinator",
            return_value=coordinator,
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_entry_unexpected_error_not_ready(hass, mock_oauth_session):
    """An unexpected setup failure raises ConfigEntryNotReady so HA retries."""
    entry = MagicMock()
    entry.entry_id = "entry-5"
    entry.data = {"home_id": "home-1"}

    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow.OAuth2Session",
            return_value=mock_oauth_session,
        ),
        patch("custom_components.netatmo_custom.NetatmoAPI", return_value=MagicMock()),
        patch(
            "custom_components.netatmo_custom.NetatmoDataUpdateCoordinator",
            return_value=coordinator,
        ),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)


async def test_unload_entry_clears_runtime_data(hass):
    """Unloading clears entry.runtime_data and unregisters the webhook."""
    entry = _runtime_entry(webhook_id="wh-1")
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    services = MagicMock()
    services.has_service.return_value = False
    hass.services = services

    with patch("custom_components.netatmo_custom.async_unregister_webhook") as unregister:
        result = await async_unload_entry(hass, entry)

    assert result is True
    assert entry.runtime_data is None
    unregister.assert_called_once_with(hass, "wh-1")


async def test_unload_last_entry_removes_service(hass):
    """Unloading the last loaded entry removes the set_schedule service."""
    entry = _runtime_entry()
    other = MagicMock()
    other.entry_id = "entry-2"
    other.runtime_data = None
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries = MagicMock(return_value=[entry, other])
    services = MagicMock()
    services.has_service.return_value = True
    hass.services = services

    await async_unload_entry(hass, entry)

    services.async_remove.assert_called_once_with(DOMAIN, SERVICE_SET_SCHEDULE)


async def test_unload_keeps_service_for_other_loaded_entries(hass):
    """Unloading one of several loaded entries keeps the service registered."""
    entry = _runtime_entry()
    other = _runtime_entry(entry_id="entry-2")
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries = MagicMock(return_value=[entry, other])
    services = MagicMock()
    services.has_service.return_value = True
    hass.services = services

    await async_unload_entry(hass, entry)

    services.async_remove.assert_not_called()


async def test_set_schedule_service_uses_runtime_data(hass):
    """The set_schedule service reads api/home_id/coordinator from runtime_data."""
    api = MagicMock()
    api.async_get_schedules = AsyncMock(return_value=[{"id": "s-eco", "name": "Eco"}])
    api.async_set_therm_mode = AsyncMock(return_value=None)
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock(return_value=None)
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, api=api, home_id="home-1")

    await async_setup_services(hass, entry)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        {"entity_id": "climate.living_room", "schedule_name": "Eco"},
        blocking=True,
    )

    api.async_set_therm_mode.assert_awaited_once_with(
        "home-1", mode="schedule", schedule_id="s-eco"
    )
    coordinator.async_request_refresh.assert_awaited_once()


async def test_set_schedule_missing_args_raises(hass):
    """Calling set_schedule without entity_id/schedule_name raises."""
    entry = _runtime_entry()
    await async_setup_services(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_SCHEDULE, {"entity_id": "climate.x"}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_SCHEDULE, {"schedule_name": "Eco"}, blocking=True
        )


async def test_set_schedule_unknown_schedule_raises(hass):
    """An unknown schedule name lists the available schedules."""
    api = MagicMock()
    api.async_get_schedules = AsyncMock(return_value=[{"id": "s-eco", "name": "Eco"}])
    coordinator = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, api=api, home_id="home-1")

    await async_setup_services(hass, entry)
    with pytest.raises(ServiceValidationError, match="NotHere"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_SCHEDULE,
            {"entity_id": "climate.living_room", "schedule_name": "NotHere"},
            blocking=True,
        )


async def test_set_schedule_api_error_raises(hass):
    """An API failure while fetching schedules raises HomeAssistantError."""
    from custom_components.netatmo_custom.api import NetatmoAPIError

    api = MagicMock()
    api.async_get_schedules = AsyncMock(side_effect=NetatmoAPIError("boom"))
    coordinator = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, api=api, home_id="home-1")

    await async_setup_services(hass, entry)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_SCHEDULE,
            {"entity_id": "climate.living_room", "schedule_name": "Eco"},
            blocking=True,
        )


async def test_set_schedule_missing_runtime_data_raises(hass):
    """A call on an entry without runtime data raises HomeAssistantError."""
    from custom_components.netatmo_custom.api import NetatmoAPIError

    api = MagicMock()
    api.async_get_schedules = AsyncMock(side_effect=NetatmoAPIError("boom"))
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.runtime_data = None

    await async_setup_services(hass, entry)
    with pytest.raises(HomeAssistantError, match="data not found"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_SCHEDULE,
            {"entity_id": "climate.living_room", "schedule_name": "Eco"},
            blocking=True,
        )


async def test_set_schedule_set_mode_error_raises(hass):
    """An API failure while applying the schedule raises HomeAssistantError."""
    from custom_components.netatmo_custom.api import NetatmoAPIError

    api = MagicMock()
    api.async_get_schedules = AsyncMock(return_value=[{"id": "s-eco", "name": "Eco"}])
    api.async_set_therm_mode = AsyncMock(side_effect=NetatmoAPIError("boom"))
    coordinator = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, api=api, home_id="home-1")

    await async_setup_services(hass, entry)
    with pytest.raises(HomeAssistantError, match="Failed to set schedule"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_SCHEDULE,
            {"entity_id": "climate.living_room", "schedule_name": "Eco"},
            blocking=True,
        )
