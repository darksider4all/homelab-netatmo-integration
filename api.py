"""Netatmo API client for custom integration."""
import json
import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client, config_entry_oauth2_flow

from .const import (
    API_BASE_URL,
    ENDPOINT_HOMESDATA,
    ENDPOINT_HOMESTATUS,
    ENDPOINT_SETROOMTHERMPOINT,
    ENDPOINT_SETTHERMMODE,
)

_LOGGER = logging.getLogger(__name__)


class NetatmoAPIError(Exception):
    """Base exception for Netatmo API errors."""


class NetatmoAuthError(NetatmoAPIError):
    """Authentication error."""


class NetatmoAPI:
    """Netatmo API client with OAuth2 token management."""

    def __init__(self, hass: HomeAssistant, oauth_session: config_entry_oauth2_flow.OAuth2Session):
        """Initialize the API client.

        Args:
            hass: Home Assistant instance
            oauth_session: OAuth2Session for automatic token refresh
        """
        self.hass = hass
        self._oauth_session = oauth_session
        self._session = aiohttp_client.async_get_clientsession(hass)
        self._base_url = API_BASE_URL

    async def async_get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        await self._oauth_session.async_ensure_token_valid()
        return self._oauth_session.token["access_token"]

    async def async_request(
        self, method: str, endpoint: str, **kwargs
    ) -> dict[str, Any]:
        """Make authenticated API request.

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint path
            **kwargs: Additional arguments for aiohttp request

        Returns:
            API response as dict

        Raises:
            NetatmoAuthError: Authentication failed
            NetatmoAPIError: API request failed
        """
        # Get valid access token (refreshes automatically if expired)
        try:
            access_token = await self.async_get_access_token()
        except Exception as err:
            _LOGGER.error(f"Failed to get access token: {err}")
            raise NetatmoAuthError(f"Failed to get access token: {err}")

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {access_token}"
        url = f"{self._base_url}{endpoint}"

        try:
            async with self._session.request(
                method, url, headers=headers, **kwargs
            ) as resp:
                response_text = await resp.text()

                if resp.status == 401:
                    raise NetatmoAuthError(f"Unauthorized - token may be invalid. Response: {response_text}")
                elif resp.status == 403:
                    raise NetatmoAuthError(f"Forbidden - re-authentication required. Response: {response_text}")

                resp.raise_for_status()
                result = json.loads(response_text)

                # Check Netatmo API status
                if result.get("status") != "ok":
                    error_msg = result.get("error", {}).get("message", "Unknown error")
                    error_code = result.get("error", {}).get("code", "unknown")
                    _LOGGER.error(f"Netatmo API error: {error_code} - {error_msg}")
                    raise NetatmoAPIError(f"API returned error: {error_code} - {error_msg}")

                return result

        except aiohttp.ClientError as err:
            _LOGGER.error(f"API request failed: {err}")
            raise NetatmoAPIError(f"API request failed: {err}")

    async def async_get_homes_data(self) -> dict[str, Any]:
        """Get home structure (rooms, devices, schedules).

        Returns:
            Home structure data
        """
        return await self.async_request("POST", ENDPOINT_HOMESDATA)

    async def async_get_home_status(self, home_id: str) -> dict[str, Any]:
        """Get current status (temperatures, modes, setpoints).

        Args:
            home_id: Netatmo home ID

        Returns:
            Home status data
        """
        data = {"home_id": home_id}
        return await self.async_request("POST", ENDPOINT_HOMESTATUS, data=data)

    async def async_set_room_thermpoint(
        self,
        home_id: str,
        room_id: str,
        mode: str,
        temp: float | None = None,
        endtime: int | None = None,
    ) -> dict[str, Any]:
        """Set room target temperature.

        Args:
            home_id: Netatmo home ID
            room_id: Netatmo room ID
            mode: Thermostat mode (manual, max, off, home)
            temp: Target temperature (required for manual mode)
            endtime: Unix timestamp for when to end this mode

        Returns:
            API response
        """
        data = {
            "home_id": home_id,
            "room_id": room_id,
            "mode": mode,
        }

        if temp is not None:
            data["temp"] = temp
        if endtime is not None:
            data["endtime"] = endtime

        return await self.async_request("POST", ENDPOINT_SETROOMTHERMPOINT, data=data)

    async def async_set_therm_mode(
        self,
        home_id: str,
        mode: str,
        endtime: int | None = None,
        schedule_id: str | None = None,
    ) -> dict[str, Any]:
        """Change thermostat mode/schedule.

        Args:
            home_id: Netatmo home ID
            mode: Home mode (schedule, away, hg, off)
            endtime: Unix timestamp for when to end this mode
            schedule_id: Schedule ID (required for schedule mode)

        Returns:
            API response
        """
        data = {
            "home_id": home_id,
            "mode": mode,
        }

        if endtime is not None:
            data["endtime"] = endtime
        if schedule_id is not None:
            data["schedule_id"] = schedule_id

        return await self.async_request("POST", ENDPOINT_SETTHERMMODE, data=data)

    async def async_get_schedules(self, home_id: str) -> list[dict[str, Any]]:
        """Get available schedules from homesdata.

        Args:
            home_id: Netatmo home ID

        Returns:
            List of schedule dicts
        """
        homes_data = await self.async_get_homes_data()

        for home in homes_data.get("body", {}).get("homes", []):
            if home["id"] == home_id:
                return home.get("schedules", [])

        return []
