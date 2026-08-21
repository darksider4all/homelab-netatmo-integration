"""Tests for Netatmo sensor value logic (battery + signal)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.netatmo_custom.sensor import (
    NetatmoBatteryLevelSensor,
    NetatmoBatteryStateSensor,
    NetatmoEnvironmentSensor,
    NetatmoSignalStrengthSensor,
    async_setup_entry,
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


# --- Platform setup (reads entry.runtime_data) ---


def _entry_with(coordinator):
    entry = MagicMock()
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, home_id="home-1", api=MagicMock())
    return entry


async def test_setup_entry_creates_expected_sensors(hass, home_status, homes_data):
    """Setup creates battery/signal sensors for each module type."""
    coordinator = MagicMock()
    coordinator.data = {"home_status": home_status, "homes_data": homes_data}
    added = []
    await async_setup_entry(hass, _entry_with(coordinator), added.extend)
    uids = {e.unique_id for e in added}
    # therm-1 (NATherm1): battery level, battery state, rf signal
    # plug-1 (NAPlug): wifi signal, rf signal
    assert uids == {
        "netatmo_home-1_therm-1_battery",
        "netatmo_home-1_therm-1_battery_state",
        "netatmo_home-1_therm-1_rf_signal",
        "netatmo_home-1_plug-1_wifi_signal",
        "netatmo_home-1_plug-1_rf_signal",
    }


async def test_setup_entry_creates_environment_sensors(hass):
    """Modules reporting humidity/co2 get environment sensors."""
    coordinator = MagicMock()
    coordinator.data = {
        "home_status": {
            "body": {
                "home": {"modules": [{"id": "m1", "type": "NATherm1", "humidity": 55, "co2": 900}]}
            }
        },
        "homes_data": {"body": {"homes": []}},
    }
    added = []
    await async_setup_entry(hass, _entry_with(coordinator), added.extend)
    uids = {e.unique_id for e in added}
    assert "netatmo_home-1_m1_humidity" in uids
    assert "netatmo_home-1_m1_co2" in uids


# --- Environment sensors ---


def test_env_sensor_direct_value():
    """Environment sensor reads the direct module key."""
    coordinator = _coordinator([{"id": "m1", "humidity": 55}])
    sensor = NetatmoEnvironmentSensor(coordinator, "m1", "M", "NATherm1", "home-1", "humidity")
    assert sensor.native_value == 55
    assert sensor.device_class == "humidity"
    assert sensor.native_unit_of_measurement == "%"


def test_env_sensor_dashboard_value():
    """Environment sensor falls back to dashboard_data keys."""
    coordinator = _coordinator([{"id": "m1", "dashboard_data": {"CO2": 800}}])
    sensor = NetatmoEnvironmentSensor(coordinator, "m1", "M", "NATherm1", "home-1", "co2")
    assert sensor.native_value == 800
    assert sensor.device_class == "carbon_dioxide"


def test_env_sensor_missing_module_returns_none():
    """No matching module yields None."""
    coordinator = _coordinator([])
    sensor = NetatmoEnvironmentSensor(coordinator, "m1", "M", "NATherm1", "home-1", "humidity")
    assert sensor.native_value is None


# --- Battery extra attributes ---


def test_battery_extra_state_attributes():
    """Battery sensor exposes voltage/state/module metadata."""
    coordinator = _coordinator([{"id": "m1", "battery_level": 3000, "battery_state": "high"}])
    sensor = NetatmoBatteryLevelSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    attrs = sensor.extra_state_attributes
    assert attrs["battery_voltage_mv"] == 3000
    assert attrs["battery_state"] == "high"
    assert attrs["module_type"] == "Smart Thermostat"
    assert attrs["module_id"] == "m1"


def test_battery_extra_state_attributes_missing_module():
    """No matching module yields empty attributes."""
    coordinator = _coordinator([])
    sensor = NetatmoBatteryLevelSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.extra_state_attributes == {}


# --- Battery state sensor ---


def test_battery_state_value_and_icon():
    """Battery state maps to a percentage icon."""
    coordinator = _coordinator([{"id": "m1", "battery_state": "low"}])
    sensor = NetatmoBatteryStateSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.native_value == "low"
    assert sensor.icon == "mdi:battery-30"


def test_battery_state_unknown_icon():
    """An unknown battery state reports unknown with the default icon."""
    coordinator = _coordinator([{"id": "m1"}])
    sensor = NetatmoBatteryStateSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.native_value == "unknown"
    assert sensor.icon == "mdi:battery-unknown"


# --- Signal strength extra attributes ---


def test_rf_signal_quality_excellent():
    """RF >= 80 is Excellent."""
    coordinator = _coordinator([{"id": "m1", "rf_strength": 85}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "rf")
    attrs = sensor.extra_state_attributes
    assert attrs["signal_quality"] == "Excellent"
    assert attrs["module_type"] == "Smart Thermostat"


def test_wifi_signal_quality_good():
    """WiFi 50-69 is Good."""
    coordinator = _coordinator([{"id": "m1", "wifi_strength": 55}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "wifi")
    assert sensor.extra_state_attributes["signal_quality"] == "Good"


def test_wifi_signal_quality_poor():
    """WiFi < 30 is Poor."""
    coordinator = _coordinator([{"id": "m1", "wifi_strength": 10}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "wifi")
    assert sensor.extra_state_attributes["signal_quality"] == "Poor"


def test_signal_missing_value_has_no_attributes():
    """No signal value yields empty attributes."""
    coordinator = _coordinator([{"id": "m1"}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "wifi")
    assert sensor.extra_state_attributes == {}


# --- Silver quality scale: PARALLEL_UPDATES + remaining coverage ---


def test_parallel_updates_declared_zero():
    """Silver rule parallel-updates: the sensor entity explicitly serialises updates."""
    assert NetatmoBatteryLevelSensor.PARALLEL_UPDATES == 0
    assert NetatmoEnvironmentSensor.PARALLEL_UPDATES == 0
    assert NetatmoBatteryStateSensor.PARALLEL_UPDATES == 0
    assert NetatmoSignalStrengthSensor.PARALLEL_UPDATES == 0


def test_battery_from_millivolts_nrv():
    """NRV valves use the 2400-3100mV range."""
    coordinator = _coordinator([{"id": "m1", "battery_level": 2750}])
    sensor = NetatmoBatteryLevelSensor(coordinator, "m1", "Valve", "NRV", "home-1")
    # (2750-2400)/(3100-2400)*100 = 50
    assert sensor.native_value == 50


def test_battery_no_state_no_voltage_returns_none():
    """A module without battery_state or battery_level yields None."""
    coordinator = _coordinator([{"id": "m1"}])
    sensor = NetatmoBatteryLevelSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.native_value is None


def test_battery_state_missing_module_returns_none():
    """Battery state with no matching module yields None."""
    coordinator = _coordinator([])
    sensor = NetatmoBatteryStateSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.native_value is None


def test_signal_missing_module_returns_none():
    """Signal sensor with no matching module yields None."""
    coordinator = _coordinator([])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "rf")
    assert sensor.native_value is None


def test_wifi_signal_quality_excellent():
    """WiFi >= 70 is Excellent."""
    coordinator = _coordinator([{"id": "m1", "wifi_strength": 85}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "wifi")
    assert sensor.extra_state_attributes["signal_quality"] == "Excellent"


def test_wifi_signal_quality_fair():
    """WiFi 30-49 is Fair."""
    coordinator = _coordinator([{"id": "m1", "wifi_strength": 40}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "wifi")
    assert sensor.extra_state_attributes["signal_quality"] == "Fair"


def test_rf_signal_quality_good():
    """RF 60-79 is Good."""
    coordinator = _coordinator([{"id": "m1", "rf_strength": 68}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "rf")
    assert sensor.extra_state_attributes["signal_quality"] == "Good"


def test_rf_signal_quality_fair():
    """RF 40-59 is Fair."""
    coordinator = _coordinator([{"id": "m1", "rf_strength": 50}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "rf")
    assert sensor.extra_state_attributes["signal_quality"] == "Fair"


def test_rf_signal_quality_poor():
    """RF < 40 is Poor."""
    coordinator = _coordinator([{"id": "m1", "rf_strength": 30}])
    sensor = NetatmoSignalStrengthSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "rf")
    assert sensor.extra_state_attributes["signal_quality"] == "Poor"
