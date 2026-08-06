"""Common fixtures for Netatmo Custom integration tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in all tests."""
    yield


@pytest.fixture
def mock_oauth_session() -> MagicMock:
    """Return a mock OAuth2Session with a valid token."""
    session = MagicMock()
    session.async_ensure_token_valid = AsyncMock(return_value=None)
    session.token = {"access_token": "test-access-token"}
    return session


@pytest.fixture
def homes_data() -> dict:
    """Return a representative homesdata API payload."""
    return {
        "status": "ok",
        "body": {
            "homes": [
                {
                    "id": "home-1",
                    "name": "Test Home",
                    "rooms": [{"id": "room-1", "name": "Living Room", "module_ids": ["therm-1"]}],
                    "modules": [
                        {"id": "plug-1", "type": "NAPlug", "name": "Relay"},
                        {
                            "id": "therm-1",
                            "type": "NATherm1",
                            "name": "Living Room",
                            "bridge": "plug-1",
                        },
                    ],
                }
            ]
        },
    }


@pytest.fixture
def home_status() -> dict:
    """Return a representative homestatus API payload."""
    return {
        "status": "ok",
        "body": {
            "home": {
                "id": "home-1",
                "rooms": [
                    {
                        "id": "room-1",
                        "therm_setpoint_mode": "schedule",
                        "therm_setpoint_temperature": 20.0,
                        "therm_measured_temperature": 19.5,
                        "heating_power_request": 50,
                    }
                ],
                "modules": [
                    {
                        "id": "therm-1",
                        "type": "NATherm1",
                        "battery_level": 3200,
                        "battery_state": "full",
                        "rf_strength": 70,
                        "boiler_status": True,
                        "reachable": True,
                    },
                    {"id": "plug-1", "type": "NAPlug", "wifi_strength": 60},
                ],
            }
        },
    }
