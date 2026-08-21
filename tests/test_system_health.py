"""Tests for the system health integration."""

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.netatmo_custom.const import API_BASE_URL
from custom_components.netatmo_custom.system_health import (
    async_register,
    system_health_info,
)


async def test_register_system_health(hass):
    """async_register wires the health info callback."""
    register = MagicMock()
    async_register(hass, register)  # @callback: sync function
    register.async_register_info.assert_called_once_with(system_health_info)


async def test_system_health_info_reports_reachability(hass):
    """system_health_info reports the API reachability check."""
    with patch(
        "custom_components.netatmo_custom.system_health.system_health.async_check_can_reach_url",
        new=AsyncMock(return_value=True),
    ) as check:
        info = await system_health_info(hass)
    assert info == {"can_reach_server": True}
    check.assert_awaited_once_with(hass, API_BASE_URL)
