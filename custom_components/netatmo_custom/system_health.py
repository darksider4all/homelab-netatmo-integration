"""System health for the Netatmo Custom integration."""

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import API_BASE_URL


@callback
def async_register(hass: HomeAssistant, register: system_health.SystemHealthRegistration) -> None:
    """Register system health callbacks."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return info for the system health page."""
    return {
        "can_reach_server": await system_health.async_check_can_reach_url(hass, API_BASE_URL),
    }
