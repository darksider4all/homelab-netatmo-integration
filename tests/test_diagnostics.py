"""Tests for the diagnostics endpoint."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.netatmo_custom.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_reports_coordinator_health(hass):
    """Diagnostics reports coordinator health and redacts sensitive data."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.consecutive_failures = 2
    coordinator.update_interval = timedelta(seconds=60)
    coordinator.webhook_active = True
    coordinator.is_data_stale = MagicMock(return_value=False)
    coordinator.data = {"home_id": "home-1", "access_token": "super-secret", "ok": True}

    entry = MagicMock()
    entry.as_dict = MagicMock(return_value={"entry_id": "entry-1", "home_id": "home-1"})
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator_health"]["last_update_success"] is True
    assert result["coordinator_health"]["consecutive_failures"] == 2
    assert result["coordinator_health"]["update_interval_seconds"] == 60
    assert result["coordinator_health"]["webhook_active"] is True
    assert result["coordinator_health"]["data_stale"] is False
    # Sensitive values are redacted in both entry and data.
    assert result["entry"]["home_id"] == "**REDACTED**"
    assert result["data"]["access_token"] == "**REDACTED**"
    assert result["data"]["ok"] is True
