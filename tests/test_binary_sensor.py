"""Tests for the Netatmo binary sensor platform."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.netatmo_custom.binary_sensor import (
    NetatmoAnticipatingStatusSensor,
    NetatmoBoilerStatusSensor,
    NetatmoReachableSensor,
    async_setup_entry,
)


def _coordinator(modules, rooms=None):
    coordinator = MagicMock()
    coordinator.data = {
        "home_status": {"body": {"home": {"modules": modules, "rooms": rooms or []}}}
    }
    return coordinator


def _entry_with(coordinator):
    entry = MagicMock()
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, home_id="home-1", api=MagicMock())
    return entry


# --- Platform setup (reads entry.runtime_data) ---


async def test_setup_entry_creates_binary_sensors(hass, home_status, homes_data):
    """Setup creates boiler/anticipating/reachable sensors per module."""
    coordinator = MagicMock()
    coordinator.data = {"home_status": home_status, "homes_data": homes_data}
    added = []
    await async_setup_entry(hass, _entry_with(coordinator), added.extend)
    uids = {e.unique_id for e in added}
    # therm-1 (NATherm1, mapped to room-1): boiler + anticipating + reachable
    # plug-1 (NAPlug): reachable only
    assert uids == {
        "netatmo_home-1_therm-1_boiler",
        "netatmo_home-1_therm-1_anticipating",
        "netatmo_home-1_therm-1_reachable",
        "netatmo_home-1_plug-1_reachable",
    }


async def test_setup_entry_skips_anticipating_without_room(hass):
    """A thermostat not mapped to a room skips the anticipating sensor."""
    coordinator = MagicMock()
    coordinator.data = {
        "home_status": {
            "body": {"home": {"modules": [{"id": "m1", "type": "NATherm1"}], "rooms": []}}
        },
        "homes_data": {"body": {"homes": []}},
    }
    added = []
    await async_setup_entry(hass, _entry_with(coordinator), added.extend)
    uids = {e.unique_id for e in added}
    assert "netatmo_home-1_m1_boiler" in uids
    assert "netatmo_home-1_m1_anticipating" not in uids
    assert "netatmo_home-1_m1_reachable" in uids


# --- Boiler status sensor ---


def test_boiler_status_on():
    """boiler_status True is reported on."""
    coordinator = _coordinator([{"id": "m1", "boiler_status": True}])
    sensor = NetatmoBoilerStatusSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.is_on is True


def test_boiler_status_missing_module():
    """No matching module yields None."""
    coordinator = _coordinator([])
    sensor = NetatmoBoilerStatusSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.is_on is None


def test_boiler_extra_attributes():
    """Boiler attributes include comfort boost and module type."""
    coordinator = _coordinator([{"id": "m1", "boiler_valve_comfort_boost": True}])
    sensor = NetatmoBoilerStatusSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    attrs = sensor.extra_state_attributes
    assert attrs["boiler_valve_comfort_boost"] is True
    assert attrs["module_type"] == "Smart Thermostat"


def test_boiler_extra_attributes_missing_module():
    """No matching module yields empty attributes."""
    coordinator = _coordinator([])
    sensor = NetatmoBoilerStatusSensor(coordinator, "m1", "Therm", "NATherm1", "home-1")
    assert sensor.extra_state_attributes == {}


# --- Anticipating sensor ---


def test_anticipating_on():
    """Room anticipating True is reported on."""
    coordinator = _coordinator([], rooms=[{"id": "room-1", "anticipating": True}])
    sensor = NetatmoAnticipatingStatusSensor(
        coordinator, "m1", "Therm", "NATherm1", "home-1", "room-1"
    )
    assert sensor.is_on is True


def test_anticipating_missing_room():
    """No matching room yields None."""
    coordinator = _coordinator([])
    sensor = NetatmoAnticipatingStatusSensor(
        coordinator, "m1", "Therm", "NATherm1", "home-1", "room-1"
    )
    assert sensor.is_on is None


# --- Reachable sensor ---


def test_reachable_thermostat_module():
    """A reachable thermostat module is on."""
    coordinator = _coordinator([{"id": "m1", "reachable": True}])
    sensor = NetatmoReachableSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "plug-1")
    assert sensor.is_on is True


def test_reachable_naplug_uses_wifi():
    """NAPlug reachability derives from wifi_strength."""
    coordinator = _coordinator([{"id": "plug-1", "wifi_strength": 60}])
    sensor = NetatmoReachableSensor(coordinator, "plug-1", "Relay", "NAPlug", "home-1", None)
    assert sensor.is_on is True


def test_reachable_naplug_no_wifi():
    """A NAPlug without wifi strength is not reachable."""
    coordinator = _coordinator([{"id": "plug-1", "wifi_strength": 0}])
    sensor = NetatmoReachableSensor(coordinator, "plug-1", "Relay", "NAPlug", "home-1", None)
    assert sensor.is_on is False


def test_reachable_missing_module():
    """No matching module yields None."""
    coordinator = _coordinator([])
    sensor = NetatmoReachableSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "plug-1")
    assert sensor.is_on is None


def test_reachable_extra_attributes():
    """Reachable attributes include firmware and module type."""
    coordinator = _coordinator([{"id": "m1", "firmware_revision": "1.2", "reachable": False}])
    sensor = NetatmoReachableSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "plug-1")
    attrs = sensor.extra_state_attributes
    assert attrs["firmware_revision"] == "1.2"
    assert attrs["module_type"] == "Smart Thermostat"


def test_reachable_extra_attributes_missing_module():
    """No matching module yields empty attributes."""
    coordinator = _coordinator([])
    sensor = NetatmoReachableSensor(coordinator, "m1", "Therm", "NATherm1", "home-1", "plug-1")
    assert sensor.extra_state_attributes == {}
