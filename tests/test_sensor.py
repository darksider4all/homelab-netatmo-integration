"""Tests for Netatmo sensor value logic (battery + signal)."""

from unittest.mock import MagicMock

from custom_components.netatmo_custom.sensor import (
    NetatmoBatteryLevelSensor,
    NetatmoSignalStrengthSensor,
)


def _coordinator(modules: list[dict]) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {"home_status": {"body": {"home": {"modules": modules}}}}
    return coordinator


def test_battery_from_state():
    """A reported battery_state maps to a percentage."""
    coordinator = _coordinator([{"id": "m1", "battery_state": "high"}])
    sensor = NetatmoBatteryLevelSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.native_value == 75


def test_battery_from_millivolts_thermostat():
    """Without battery_state, the mV fallback computes a percentage."""
    coordinator = _coordinator([{"id": "m1", "battery_level": 2700}])
    sensor = NetatmoBatteryLevelSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    # (2700-2200)/(3200-2200)*100 = 50
    assert sensor.native_value == 50


def test_battery_clamped_to_range():
    """An out-of-range voltage is clamped to 0-100."""
    coordinator = _coordinator([{"id": "m1", "battery_level": 5000}])
    sensor = NetatmoBatteryLevelSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.native_value == 100


def test_battery_missing_module_returns_none():
    """No matching module yields None."""
    coordinator = _coordinator([])
    sensor = NetatmoBatteryLevelSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.native_value is None


def test_rf_signal_value():
    """RF signal sensor reads rf_strength."""
    coordinator = _coordinator([{"id": "m1", "rf_strength": 68}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "rf")
    assert sensor.native_value == 68
    assert sensor.unique_id == "netatmo_home-1_m1_rf_signal"


def test_wifi_signal_value():
    """WiFi signal sensor reads wifi_strength."""
    coordinator = _coordinator([{"id": "plug-1", "wifi_strength": 55}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "plug-1", "Relay", "NAPlug", "home-1", "wifi")
    assert sensor.native_value == 55
