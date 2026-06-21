"""Tests for the Netatmo climate entity mapping logic."""

from unittest.mock import MagicMock

from homeassistant.components.climate.const import (
    PRESET_HOME,
    PRESET_NONE,
    HVACAction,
    HVACMode,
)
import pytest

from custom_components.netatmo_custom.climate import NetatmoThermostat


def _make_entity(home_status, homes_data, failures=0) -> NetatmoThermostat:
    coordinator = MagicMock()
    coordinator.data = {"home_status": home_status, "homes_data": homes_data}
    coordinator.consecutive_failures = failures
    room = {"id": "room-1", "name": "Living Room"}
    module = {"id": "therm-1", "type": "NATherm1", "name": "Living Room"}
    return NetatmoThermostat(coordinator, room, "home-1", "Test Home", module, "plug-1")


def _set_room_mode(home_status, mode):
    home_status["body"]["home"]["rooms"][0]["therm_setpoint_mode"] = mode
    return home_status


@pytest.fixture
def entity(home_status, homes_data) -> NetatmoThermostat:
    return _make_entity(home_status, homes_data)


def test_unique_id_is_stable(entity):
    """The unique_id scheme must remain netatmo_{home}_{room} (no orphaning)."""
    assert entity.unique_id == "netatmo_home-1_room-1"


def test_schedule_mode_maps_to_auto_home(entity):
    """Schedule mode -> AUTO / PRESET_HOME."""
    assert entity.hvac_mode == HVACMode.AUTO
    assert entity.preset_mode == PRESET_HOME


def test_temperatures(entity):
    """Current and target temperatures are read from room status."""
    assert entity.current_temperature == 19.5
    assert entity.target_temperature == 20.0


def test_hvac_action_heating(entity):
    """heating_power_request > 0 reports HEATING."""
    assert entity.hvac_action == HVACAction.HEATING


def test_off_mode(home_status, homes_data):
    """Off mode -> HVACMode.OFF and HVACAction.OFF."""
    _set_room_mode(home_status, "off")
    entity = _make_entity(home_status, homes_data)
    assert entity.hvac_mode == HVACMode.OFF
    assert entity.hvac_action == HVACAction.OFF


def test_manual_mode_heat_preset_none(home_status, homes_data):
    """Manual mode -> HEAT with PRESET_NONE."""
    _set_room_mode(home_status, "manual")
    entity = _make_entity(home_status, homes_data)
    assert entity.hvac_mode == HVACMode.HEAT
    assert entity.preset_mode == PRESET_NONE


def test_unavailable_after_too_many_failures(home_status, homes_data):
    """Entity becomes unavailable past the consecutive-failure threshold."""
    entity = _make_entity(home_status, homes_data, failures=99)
    assert entity.available is False
