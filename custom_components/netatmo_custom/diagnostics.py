"""Diagnostics for Netatmo Custom integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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
    coordinator: NetatmoDataUpdateCoordinator = entry.runtime_data.coordinator

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator_health": {
            "last_update_success": coordinator.last_update_success,
            "consecutive_failures": coordinator.consecutive_failures,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds() if coordinator.update_interval else None
            ),
            "webhook_active": getattr(coordinator, "webhook_active", None),
            "data_stale": coordinator.is_data_stale(),
        },
        "data": async_redact_data(coordinator.data, TO_REDACT),
    }
