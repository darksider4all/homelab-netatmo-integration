"""Netatmo API client for custom integration."""
import asyncio
import json
import logging
import time
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

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 30  # seconds
REQUEST_TIMEOUT = 30  # seconds

# Rate limiting (Netatmo allows ~50 requests per 10 seconds)
RATE_LIMIT_WINDOW = 10  # seconds
RATE_LIMIT_MAX_REQUESTS = 40  # stay under limit

# Netatmo error codes that are transient and worth retrying
TRANSIENT_ERROR_CODES = {"9", "10", "13", "26"}  # 13 = Couldn't apply setpoint, Device unreachable, internal error


class NetatmoAPIError(Exception):
    """Base exception for Netatmo API errors."""


class NetatmoAuthError(NetatmoAPIError):
    """Authentication error."""


class NetatmoRateLimitError(NetatmoAPIError):
    """Rate limit exceeded error."""


class NetatmoTimeoutError(NetatmoAPIError):
    """Request timeout error."""


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
        self._request_timestamps: list[float] = []
        self._consecutive_failures = 0

    async def async_get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        await self._oauth_session.async_ensure_token_valid()
        return self._oauth_session.token["access_token"]

    async def _check_rate_limit(self) -> None:
        """Check and enforce rate limiting."""
        now = time.time()
        # Remove timestamps outside the window
        self._request_timestamps = [
            ts for ts in self._request_timestamps
            if now - ts < RATE_LIMIT_WINDOW
        ]

        if len(self._request_timestamps) >= RATE_LIMIT_MAX_REQUESTS:
            # Calculate wait time until oldest request exits the window
            wait_time = RATE_LIMIT_WINDOW - (now - self._request_timestamps[0]) + 0.5
            if wait_time > 0:
                _LOGGER.warning(f"Rate limit approaching, waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)

        self._request_timestamps.append(time.time())

    async def _do_request(
        self, method: str, endpoint: str, headers: dict, timeout: aiohttp.ClientTimeout, **kwargs
    ) -> tuple[int, str, dict]:
        """Execute a single HTTP request.

        Returns:
            Tuple of (status_code, response_text, response_headers)
        """
        url = f"{self._base_url}{endpoint}"
        async with self._session.request(
            method, url, headers=headers, timeout=timeout, **kwargs
        ) as resp:
            response_text = await resp.text()
            return resp.status, response_text, dict(resp.headers)

    async def async_request(
        self, method: str, endpoint: str, **kwargs
    ) -> dict[str, Any]:
        """Make authenticated API request with retry logic.

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint path
            **kwargs: Additional arguments for aiohttp request

        Returns:
            API response as dict

        Raises:
            NetatmoAuthError: Authentication failed
            NetatmoAPIError: API request failed after retries
        """
        # Extract custom headers if provided (preserve for potential retries)
        custom_headers = kwargs.pop("headers", {})
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            # Enforce rate limiting
            await self._check_rate_limit()

            # Get valid access token (refreshes automatically if expired)
            try:
                access_token = await self.async_get_access_token()
            except Exception as err:
                _LOGGER.error(f"Failed to get access token: {err}")
                raise NetatmoAuthError(f"Failed to get access token: {err}")

            # Build headers for this request (fresh copy each attempt)
            headers = {**custom_headers, "Authorization": f"Bearer {access_token}"}

            try:
                status, response_text, resp_headers = await self._do_request(
                    method, endpoint, headers, timeout, **kwargs
                )

                # Handle authentication errors (no retry)
                if status == 401:
                    self._consecutive_failures += 1
                    raise NetatmoAuthError(f"Unauthorized - token may be invalid. Response: {response_text}")
                elif status == 403:
                    # Look at response text to see if it's transient
                    try:
                        err_res = json.loads(response_text)
                        err_code = err_res.get("error", {}).get("code")
                        if str(err_code) in TRANSIENT_ERROR_CODES:
                            if attempt < MAX_RETRIES:
                                backoff = min(INITIAL_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                                _LOGGER.warning(f"Transient Netatmo error 403 (code {err_code}), retrying in {backoff}s")
                                await asyncio.sleep(backoff)
                                continue
                    except json.JSONDecodeError:
                        pass
                    
                    self._consecutive_failures += 1
                    raise NetatmoAuthError(f"Forbidden - re-authentication required. Response: {response_text}")

                # Handle rate limiting (429)
                if status == 429:
                    # HTTP headers are case-insensitive, normalize lookup
                    retry_after_str = resp_headers.get("Retry-After") or resp_headers.get("retry-after") or "60"
                    retry_after = int(retry_after_str)
                    _LOGGER.warning(f"Rate limited by Netatmo API, retry after {retry_after}s")
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(min(retry_after, MAX_BACKOFF))
                        continue
                    self._consecutive_failures += 1
                    raise NetatmoRateLimitError(f"Rate limited after {MAX_RETRIES} retries")

                # Handle server errors (5xx) with retry
                if status >= 500:
                    if attempt < MAX_RETRIES:
                        backoff = min(INITIAL_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                        _LOGGER.warning(f"Server error {status}, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                        await asyncio.sleep(backoff)
                        continue
                    self._consecutive_failures += 1
                    raise NetatmoAPIError(f"Server error {status} after {MAX_RETRIES} retries: {response_text}")

                # Handle other client errors (4xx)
                if status >= 400:
                    self._consecutive_failures += 1
                    raise NetatmoAPIError(f"Client error {status}: {response_text}")

                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as err:
                    self._consecutive_failures += 1
                    raise NetatmoAPIError(f"Invalid JSON response: {err}")

                # Check Netatmo API status
                if result.get("status") != "ok":
                    error_msg = result.get("error", {}).get("message", "Unknown error")
                    error_code = result.get("error", {}).get("code", "unknown")

                    # Some errors are transient and worth retrying
                    if str(error_code) in TRANSIENT_ERROR_CODES:
                        if attempt < MAX_RETRIES:
                            backoff = min(INITIAL_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                            _LOGGER.warning(f"Netatmo error {error_code}, retrying in {backoff}s")
                            await asyncio.sleep(backoff)
                            continue

                    self._consecutive_failures += 1
                    _LOGGER.error(f"Netatmo API error: {error_code} - {error_msg}")
                    raise NetatmoAPIError(f"API returned error: {error_code} - {error_msg}")

                # Success - reset failure counter
                self._consecutive_failures = 0
                return result

            except asyncio.TimeoutError as err:
                last_error = err
                if attempt < MAX_RETRIES:
                    backoff = min(INITIAL_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                    _LOGGER.warning(f"Request timeout, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(backoff)
                    continue

            except aiohttp.ClientError as err:
                last_error = err
                if attempt < MAX_RETRIES:
                    backoff = min(INITIAL_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                    _LOGGER.warning(f"Connection error: {err}, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(backoff)
                    continue

        # All retries exhausted
        self._consecutive_failures += 1
        if isinstance(last_error, asyncio.TimeoutError):
            raise NetatmoTimeoutError(f"Request timed out after {MAX_RETRIES} retries")
        elif last_error:
            _LOGGER.error(f"API request failed after {MAX_RETRIES} retries: {last_error}")
            raise NetatmoAPIError(f"API request failed: {last_error}")
        raise NetatmoAPIError("Request failed for unknown reason")

    @property
    def consecutive_failures(self) -> int:
        """Return count of consecutive API failures."""
        return self._consecutive_failures

    def reset_failure_count(self) -> None:
        """Reset the consecutive failure counter."""
        self._consecutive_failures = 0

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
