"""relay_device_id: the registry lookup that replaced the deprecated via_device.

HA 2027.8 removes the identifier form of `via_device` from the device registry, so
modules must hang off the relay by its device id. The id is captured when the relay
device is registered in async_setup_entry; this guards the lookup itself and the
device_info each platform builds from it.
"""

import inspect
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers import device_registry
from homeassistant.helpers.device_registry import DeviceRegistry
import pytest

from custom_components.netatmo_custom import async_setup_entry, relay_device_id
from custom_components.netatmo_custom.binary_sensor import NetatmoReachableSensor
from custom_components.netatmo_custom.climate import NetatmoThermostat
from custom_components.netatmo_custom.const import DOMAIN
from custom_components.netatmo_custom.sensor import NetatmoBatteryLevelSensor


class _FakeHass:
    """Minimal stand-in: only hass.data is consulted."""

    def __init__(self, store):
        self.data = store


_REGISTRY_ACCEPTS_VIA_DEVICE_ID = (
    "via_device_id" in inspect.signature(DeviceRegistry.async_get_or_create).parameters
)


def _coordinator(hass=None):
    coordinator = MagicMock()
    coordinator.hass = hass or _FakeHass({})
    coordinator.data = {}
    return coordinator


def _hass_with_relay(relay_id="plug-1", device_id="device-relay"):
    return _FakeHass({DOMAIN: {"relay_devices": {relay_id: device_id}}})


def test_returns_registered_device_id():
    hass = _FakeHass({DOMAIN: {"relay_devices": {"relay-1": "device-abc"}}})
    assert relay_device_id(hass, "relay-1") == "device-abc"


def test_missing_relay_returns_none():
    hass = _FakeHass({DOMAIN: {"relay_devices": {"relay-1": "device-abc"}}})
    assert relay_device_id(hass, "relay-unknown") is None


def test_no_relay_id_returns_none():
    hass = _FakeHass({DOMAIN: {"relay_devices": {}}})
    assert relay_device_id(hass, None) is None


def test_empty_hass_data_returns_none():
    hass = _FakeHass({})
    assert relay_device_id(hass, "relay-1") is None


def test_climate_device_info_uses_via_device_id():
    """A thermostat device hangs off the relay by id, not by identifier tuple."""
    coordinator = _coordinator(_hass_with_relay())
    room = {"id": "room-1", "name": "Living Room"}
    module = {"id": "therm-1", "type": "NATherm1", "name": "Living Room"}
    entity = NetatmoThermostat(coordinator, room, "home-1", "Test Home", module, "plug-1")

    info = entity.device_info
    assert info["via_device_id"] == "device-relay"
    assert "via_device" not in info


def test_climate_relay_itself_has_no_parent():
    coordinator = _coordinator(_hass_with_relay())
    room = {"id": "room-1", "name": "Living Room"}
    module = {"id": "plug-1", "type": "NAPlug", "name": "Relay"}
    entity = NetatmoThermostat(coordinator, room, "home-1", "Test Home", module, "plug-1")

    assert entity.device_info["via_device_id"] is None


def test_battery_sensor_device_info_uses_via_device_id():
    entity = NetatmoBatteryLevelSensor(
        _coordinator(_hass_with_relay()),
        "therm-1",
        "Living Room",
        "NATherm1",
        "home-1",
        "plug-1",
    )

    info = entity.device_info
    assert info["via_device_id"] == "device-relay"
    assert "via_device" not in info


def test_reachable_sensor_device_info_uses_via_device_id():
    entity = NetatmoReachableSensor(
        _coordinator(_hass_with_relay()),
        "therm-1",
        "Living Room",
        "NATherm1",
        "home-1",
        "plug-1",
    )

    info = entity.device_info
    assert info["via_device_id"] == "device-relay"
    assert "via_device" not in info


def test_unresolved_relay_yields_no_parent():
    """If the relay id is unknown the device is simply left unparented."""
    entity = NetatmoReachableSensor(
        _coordinator(_hass_with_relay(relay_id="plug-1")),
        "therm-1",
        "Living Room",
        "NATherm1",
        "home-1",
        "plug-other",
    )

    assert entity.device_info["via_device_id"] is None


async def test_real_registry_links_module_to_relay_without_deprecation_warning(hass, caplog):
    """The device_info we build passes a real device registry and logs no warning."""
    if not _REGISTRY_ACCEPTS_VIA_DEVICE_ID:
        pytest.skip("test harness pins Home Assistant 2024.10, which predates via_device_id")

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    registry = device_registry.async_get(hass)
    relay = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "plug-1")},
        manufacturer="Netatmo",
        model="Relay",
    )
    hass.data.setdefault(DOMAIN, {})["relay_devices"] = {"plug-1": relay.id}

    entity = NetatmoReachableSensor(
        _coordinator(hass),
        "therm-1",
        "Living Room",
        "NATherm1",
        "home-1",
        "plug-1",
    )
    info = dict(entity.device_info)
    info.pop("identifiers")
    with caplog.at_level(logging.WARNING):
        module = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "therm-1")},
            **info,
        )

    assert module.via_device_id == relay.id
    assert "deprecated" not in caplog.text


async def test_setup_merges_relay_map_across_homes(hass, mock_oauth_session):
    """A second config entry must not drop the first home's relay ids."""
    hass.data.setdefault(DOMAIN, {})["relay_devices"] = {"plug-0": "device-other-home"}

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {"home_id": "home-1"}

    coordinator = MagicMock()
    coordinator.data = {
        "homes_data": {
            "body": {
                "homes": [
                    {
                        "id": "home-1",
                        "modules": [{"id": "plug-1", "type": "NAPlug", "name": "Relay"}],
                    }
                ]
            }
        }
    }
    coordinator.async_config_entry_first_refresh = AsyncMock(return_value=None)
    registry = MagicMock()
    registry.async_get_or_create.return_value = SimpleNamespace(id="device-relay")

    with (
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow"
            ".async_get_config_entry_implementation",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.netatmo_custom.config_entry_oauth2_flow.OAuth2Session",
            return_value=mock_oauth_session,
        ),
        patch("custom_components.netatmo_custom.NetatmoAPI", return_value=MagicMock()),
        patch(
            "custom_components.netatmo_custom.NetatmoDataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch("custom_components.netatmo_custom.dr.async_get", return_value=registry),
        patch("custom_components.netatmo_custom.async_setup_services", new=AsyncMock()),
    ):
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        assert await async_setup_entry(hass, entry) is True

    assert hass.data[DOMAIN]["relay_devices"] == {
        "plug-0": "device-other-home",
        "plug-1": "device-relay",
    }
