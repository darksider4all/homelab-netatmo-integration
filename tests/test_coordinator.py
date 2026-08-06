"""Tests for the Netatmo data update coordinator."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.netatmo_custom.api import NetatmoAPIError, NetatmoAuthError
from custom_components.netatmo_custom.coordinator import (
    MIN_UPDATE_INTERVAL,
    NetatmoDataUpdateCoordinator,
)


@pytest.fixture
def coordinator(hass, homes_data, home_status) -> NetatmoDataUpdateCoordinator:
    """Return a coordinator with a mocked API."""
    api = MagicMock()
    api.async_get_homes_data = AsyncMock(return_value=homes_data)
    api.async_get_home_status = AsyncMock(return_value=home_status)
    return NetatmoDataUpdateCoordinator(hass, api, "home-1")


async def test_update_success(coordinator):
    """A successful update returns combined data and resets failures."""
    data = await coordinator._async_update_data()
    assert data["update_successful"] is True
    assert data["homes_data"]["status"] == "ok"
    assert data["home_status"]["status"] == "ok"
    assert coordinator.consecutive_failures == 0


async def test_auth_error_triggers_reauth(coordinator):
    """An auth error raises ConfigEntryAuthFailed to start reauth."""
    coordinator.api.async_get_homes_data = AsyncMock(side_effect=NetatmoAuthError("401"))
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_api_error_without_cache_raises_update_failed(coordinator):
    """An API error with no cached data raises UpdateFailed."""
    coordinator.api.async_get_homes_data = AsyncMock(side_effect=NetatmoAPIError("boom"))
    coordinator.data = None
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_api_error_with_cache_returns_stale(coordinator):
    """An API error with cached data returns stale data (graceful degradation)."""
    coordinator.data = {"homes_data": {}, "home_status": {}, "timestamp": 123}
    coordinator.api.async_get_home_status = AsyncMock(side_effect=NetatmoAPIError("boom"))
    data = await coordinator._async_update_data()
    assert data["stale"] is True
    assert data["update_successful"] is False
    assert coordinator.consecutive_failures == 1


async def test_api_error_exhausts_stale_window(coordinator):
    """After too many consecutive failures, UpdateFailed is raised."""
    coordinator.data = {"timestamp": 123}
    coordinator._consecutive_update_failures = 3  # next failure -> 4 (> 3)
    coordinator.api.async_get_home_status = AsyncMock(side_effect=NetatmoAPIError("boom"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_failure_backs_off_interval(coordinator):
    """A failure increases the polling interval (backoff)."""
    base = coordinator.update_interval
    coordinator._adjust_update_interval(success=False)
    assert coordinator.update_interval > base
    coordinator._adjust_update_interval(success=True)
    assert coordinator.consecutive_failures == 0


async def test_webhook_speeds_up_and_refreshes(coordinator):
    """A webhook marks active, lowers the interval, and requests a refresh."""
    coordinator.async_request_refresh = AsyncMock()
    await coordinator.async_handle_webhook({"push_type": "therm-mode"})
    assert coordinator.webhook_active is True
    assert coordinator.update_interval.total_seconds() == MIN_UPDATE_INTERVAL
    coordinator.async_request_refresh.assert_awaited_once()


async def test_is_data_stale(coordinator):
    """is_data_stale reflects missing/old/flagged data."""
    coordinator.data = None
    assert coordinator.is_data_stale() is True
    coordinator.data = {"stale": True, "timestamp": 9_999_999_999}
    assert coordinator.is_data_stale() is True
    coordinator.data = {"stale": False, "timestamp": 9_999_999_999}
    assert coordinator.is_data_stale() is False
