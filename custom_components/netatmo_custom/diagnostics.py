"""Diagnostics for Netatmo Custom integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import NetatmoDataUpdateCoordinator

TO_REDACT = {
    "access_token",
    "refresh_token",
    "client_id",
    "client_secret",
    "api_key",
    "mac_address",
    "serial_number",
    "station_name",
    "pseudo",
    "city",
    "country",
    "region",
    "address",
    "location",
    "lat",
    "lon",
    "id",  # IDs might be sensitive or just UUIDs, but often contain macs in Netatmo
    "home_id",
    "home_name",
    "persons",
    "email",
}

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: NetatmoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": async_redact_data(coordinator.data, TO_REDACT),
    }
