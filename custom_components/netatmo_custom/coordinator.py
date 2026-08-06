"""Data update coordinator for Netatmo Custom integration."""

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NetatmoAPI, NetatmoAPIError, NetatmoAuthError
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Adaptive polling configuration
MIN_UPDATE_INTERVAL = 30  # seconds (faster when active)
MAX_UPDATE_INTERVAL = 300  # seconds (slower after failures)
FAILURE_BACKOFF_MULTIPLIER = 1.5


class NetatmoDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Netatmo data from API."""

    def __init__(self, hass: HomeAssistant, api: NetatmoAPI, home_id: str):
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            api: Netatmo API client
            home_id: Netatmo home ID
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.api = api
        self.home_id = home_id
        self.webhook_active = False
        self._consecutive_update_failures = 0
        self._last_successful_update: float | None = None
        self._base_update_interval = UPDATE_INTERVAL

    @property
    def consecutive_failures(self) -> int:
        """Return number of consecutive update failures."""
        return self._consecutive_update_failures

    @property
    def last_successful_update(self) -> float | None:
        """Return timestamp of last successful update."""
        return self._last_successful_update

    @property
    def seconds_since_last_update(self) -> float | None:
        """Return seconds since last successful update."""
        if self._last_successful_update is None:
            return None
        return time.time() - self._last_successful_update

    def _adjust_update_interval(self, success: bool) -> None:
        """Adjust polling interval based on success/failure.

        Args:
            success: Whether the last update was successful
        """
        new_interval: float
        if success:
            # Successful update - reset to base interval
            self._consecutive_update_failures = 0
            new_interval = self._base_update_interval
        else:
            # Failed update - exponential backoff
            self._consecutive_update_failures += 1
            backoff_factor = FAILURE_BACKOFF_MULTIPLIER ** min(self._consecutive_update_failures, 5)
            new_interval = min(self._base_update_interval * backoff_factor, MAX_UPDATE_INTERVAL)
            _LOGGER.warning(
                f"Update failed ({self._consecutive_update_failures} consecutive). "
                f"Adjusting poll interval to {new_interval:.0f}s"
            )

        self.update_interval = timedelta(seconds=new_interval)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Netatmo API.

        Returns:
            Combined data from homesdata and homestatus

        Raises:
            UpdateFailed: If update fails
        """
        try:
            # Fetch both structure and status
            homes_data = await self.api.async_get_homes_data()
            home_status = await self.api.async_get_home_status(self.home_id)

            # Successful update - check if we're recovering from failures
            previous_failures = self._consecutive_update_failures
            self._last_successful_update = time.time()
            self._adjust_update_interval(success=True)

            # Log recovery if we had coordinator-level failures
            if previous_failures > 0:
                _LOGGER.info(
                    f"Netatmo coordinator recovered after {previous_failures} consecutive failures"
                )

            return {
                "homes_data": homes_data,
                "home_status": home_status,
                "timestamp": time.time(),
                "update_successful": True,
            }

        except NetatmoAuthError as err:
            # Auth errors need reauth, not retry: raising ConfigEntryAuthFailed
            # makes Home Assistant start the reauthentication flow.
            self._adjust_update_interval(success=False)
            _LOGGER.error("Authentication error: %s", err)
            raise ConfigEntryAuthFailed(str(err)) from err

        except NetatmoAPIError as err:
            self._adjust_update_interval(success=False)

            # If we have cached data and haven't failed too many times, return stale data
            if self.data is not None and self._consecutive_update_failures <= 3:
                _LOGGER.warning(
                    "API error, returning cached data (failure %d/3): %s",
                    self._consecutive_update_failures,
                    err,
                )
                # Return existing data with staleness indicator
                return {
                    **self.data,
                    "timestamp": self.data.get("timestamp", 0),
                    "update_successful": False,
                    "stale": True,
                    "last_error": str(err),
                }

            raise UpdateFailed(f"Error communicating with Netatmo API: {err}") from err

        except Exception as err:
            self._adjust_update_interval(success=False)
            _LOGGER.exception("Unexpected error during update")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_handle_webhook(self, webhook_data: dict) -> None:
        """Handle an incoming Netatmo webhook by triggering a fresh pull.

        Netatmo webhooks are used purely as a "something changed" signal: we
        speed up the poll interval and request an immediate refresh so the
        authoritative state comes from the API rather than the (untrusted)
        webhook payload.
        """
        self.webhook_active = True
        self.update_interval = timedelta(seconds=MIN_UPDATE_INTERVAL)

        push_type = webhook_data.get("push_type")
        _LOGGER.debug("Received webhook event: %s", push_type)

        await self.async_request_refresh()

    async def async_force_refresh(self) -> bool:
        """Force a refresh and return success status.

        Returns:
            True if refresh succeeded, False otherwise
        """
        try:
            await self.async_request_refresh()
            return self.data is not None and self.data.get("update_successful", False)
        except Exception:
            return False

    def is_data_stale(self, max_age_seconds: int = 300) -> bool:
        """Check if the current data is considered stale.

        Args:
            max_age_seconds: Maximum age in seconds before data is stale

        Returns:
            True if data is stale or missing
        """
        if self.data is None:
            return True
        if self.data.get("stale", False):
            return True
        timestamp = self.data.get("timestamp", 0)
        return (time.time() - timestamp) > max_age_seconds
