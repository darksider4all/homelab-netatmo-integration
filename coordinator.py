"""Data update coordinator for Netatmo Custom integration."""
import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NetatmoAPI, NetatmoAPIError
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


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

    async def _async_update_data(self) -> dict:
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

            # Merge data for easy access by entities
            data = {
                "homes_data": homes_data,
                "home_status": home_status,
                "timestamp": time.time(),
            }

            _LOGGER.debug(
                f"Updated Netatmo data (webhook_active: {self.webhook_active})"
            )
            return data

        except NetatmoAPIError as err:
            raise UpdateFailed(f"Error communicating with Netatmo API: {err}")

    async def async_handle_webhook(self, webhook_data: dict) -> None:
        """Handle webhook update and immediately refresh coordinator data.

        Args:
            webhook_data: Webhook event data from Netatmo
        """
        _LOGGER.debug(f"Webhook received: {webhook_data}")

        # Mark webhook as active
        self.webhook_active = True

        # Trigger immediate data refresh
        await self.async_request_refresh()
