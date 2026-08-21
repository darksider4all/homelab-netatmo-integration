"""Tests for the Netatmo climate entity mapping logic."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate.const import (
    PRESET_AWAY,
    PRESET_HOME,
    PRESET_NONE,
    HVACAction,
    HVACMode,
)
import pytest

from custom_components.netatmo_custom.climate import NetatmoThermostat, async_setup_entry
from custom_components.netatmo_custom.const import PRESET_FROST_GUARD


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


# --- Platform setup (reads entry.runtime_data) ---


async def test_setup_entry_creates_thermostat(hass, home_status, homes_data):
    """Setup creates a thermostat for each room with a setpoint mode."""
    coordinator = MagicMock()
    coordinator.data = {"home_status": home_status, "homes_data": homes_data}
    entry = MagicMock()
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, home_id="home-1", api=MagicMock())
    added = []
    await async_setup_entry(hass, entry, added.extend)
    assert len(added) == 1
    assert added[0].unique_id == "netatmo_home-1_room-1"
    assert added[0].current_temperature == 19.5


async def test_setup_entry_skips_room_without_setpoint(hass):
    """A room without a setpoint mode yields no thermostat."""
    coordinator = MagicMock()
    coordinator.data = {
        "home_status": {
            "body": {
                "home": {
                    "rooms": [{"id": "room-1", "therm_measured_temperature": 19.0}],
                    "modules": [],
                }
            }
        },
        "homes_data": {
            "body": {"homes": [{"id": "home-1", "name": "Test Home", "rooms": [], "modules": []}]}
        },
    }
    entry = MagicMock()
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, home_id="home-1", api=MagicMock())
    added = []
    await async_setup_entry(hass, entry, added.extend)
    assert added == []


# --- API actions resolve the client through coordinator.api ---


def _entity_with_api(home_status, homes_data, api=None, coordinator=None):
    """Build an entity whose coordinator carries the API client."""
    if coordinator is None:
        coordinator = MagicMock()
        coordinator.data = {"home_status": home_status, "homes_data": homes_data}
        coordinator.consecutive_failures = 0
        coordinator.api = api or MagicMock()
        coordinator.async_request_refresh = AsyncMock(return_value=None)
    room = {"id": "room-1", "name": "Living Room"}
    module = {"id": "therm-1", "type": "NATherm1", "name": "Living Room"}
    return NetatmoThermostat(coordinator, room, "home-1", "Test Home", module, "plug-1")


def _run_api_call_verification(entity):
    """Replace verification with a helper that executes the API call once."""

    async def fake_verify(api_call, verification_func, description, max_retries=4):
        await api_call()
        return True

    entity._async_call_api_with_verification = fake_verify


async def test_set_temperature_uses_coordinator_api(home_status, homes_data):
    """set_temperature drives the API client held by the coordinator."""
    api = MagicMock()
    api.async_set_room_thermpoint = AsyncMock(return_value=None)
    entity = _entity_with_api(home_status, homes_data, api=api)
    _run_api_call_verification(entity)

    await entity.async_set_temperature(temperature=21.0)

    api.async_set_room_thermpoint.assert_awaited_once_with(
        "home-1", "room-1", mode="manual", temp=21.0
    )


@pytest.mark.parametrize(
    ("hvac_mode", "expected_mode"),
    [
        (HVACMode.OFF, "off"),
        (HVACMode.HEAT, "manual"),
        (HVACMode.AUTO, "home"),
    ],
)
async def test_set_hvac_mode_uses_coordinator_api(
    home_status, homes_data, hvac_mode, expected_mode
):
    """set_hvac_mode maps HA modes to Netatmo room modes via coordinator.api."""
    api = MagicMock()
    api.async_set_room_thermpoint = AsyncMock(return_value=None)
    entity = _entity_with_api(home_status, homes_data, api=api)
    _run_api_call_verification(entity)

    await entity.async_set_hvac_mode(hvac_mode)

    assert api.async_set_room_thermpoint.await_args.kwargs["mode"] == expected_mode


async def test_set_preset_mode_uses_coordinator_api(home_status, homes_data):
    """set_preset_mode maps presets to Netatmo home modes via coordinator.api."""
    api = MagicMock()
    api.async_set_therm_mode = AsyncMock(return_value=None)
    entity = _entity_with_api(home_status, homes_data, api=api)
    _run_api_call_verification(entity)
    # async_write_ha_state is called without await; a plain mock avoids warnings.
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_preset_mode(PRESET_AWAY)

    api.async_set_therm_mode.assert_awaited_once_with("home-1", mode="away")
    # Optimistic state is cleared after the call.
    assert entity._optimistic_preset is None


# --- Verification helper (retry/backoff behaviour) ---


@pytest.fixture
def zero_delays():
    """Zero out all verification sleep constants for fast tests."""
    with (
        patch("custom_components.netatmo_custom.climate.VERIFY_PROPAGATION_DELAY", 0),
        patch("custom_components.netatmo_custom.climate.VERIFY_SETTLE_DELAY", 0),
        patch("custom_components.netatmo_custom.climate.VERIFY_RETRY_BASE_DELAY", 0),
    ):
        yield


async def test_verification_succeeds_first_attempt(home_status, homes_data, zero_delays):
    """A change verified on the first attempt returns True immediately."""
    entity = _entity_with_api(home_status, homes_data)
    api_call = AsyncMock(return_value=None)
    success = await entity._async_call_api_with_verification(api_call, lambda: True, "test")
    assert success is True
    assert api_call.await_count == 1


async def test_verification_retries_until_verified(home_status, homes_data, zero_delays):
    """A change verified on a later attempt returns True."""
    entity = _entity_with_api(home_status, homes_data)
    api_call = AsyncMock(return_value=None)
    attempts = {"n": 0}

    def verify():
        attempts["n"] += 1
        return attempts["n"] >= 2

    success = await entity._async_call_api_with_verification(
        api_call, verify, "test", max_retries=3
    )
    assert success is True
    assert api_call.await_count == 2


async def test_verification_gives_up_after_retries(home_status, homes_data, zero_delays):
    """An unverified change returns False after the retry budget is spent."""
    entity = _entity_with_api(home_status, homes_data)
    api_call = AsyncMock(return_value=None)
    success = await entity._async_call_api_with_verification(
        api_call, lambda: False, "test", max_retries=1
    )
    assert success is False
    assert api_call.await_count == 2


async def test_verification_retries_on_exception(home_status, homes_data, zero_delays):
    """An API exception is treated as a retryable attempt."""
    entity = _entity_with_api(home_status, homes_data)
    api_call = AsyncMock(side_effect=Exception("boom"))
    success = await entity._async_call_api_with_verification(
        api_call, lambda: True, "test", max_retries=1
    )
    assert success is False
    assert api_call.await_count == 2


# --- Remaining entity property edge cases ---


def test_icon_reflects_preset(entity):
    """The icon follows the current preset (home in the default fixture)."""
    assert entity.icon == "mdi:home-thermometer"


def test_no_room_status_returns_off(home_status, homes_data):
    """Missing room status maps to OFF / OFF."""
    home_status["body"]["home"]["rooms"] = []
    entity = _make_entity(home_status, homes_data)
    assert entity.hvac_mode == HVACMode.OFF
    assert entity.hvac_action == HVACAction.OFF
    assert entity.current_temperature is None
    assert entity.target_temperature is None


def test_frost_guard_preset_mapping(home_status, homes_data):
    """Frost guard mode maps to the frost guard preset."""
    _set_room_mode(home_status, "hg")
    entity = _make_entity(home_status, homes_data)
    assert entity.preset_mode == PRESET_FROST_GUARD


def test_away_preset_mapping(home_status, homes_data):
    """Away mode maps to the away preset."""
    _set_room_mode(home_status, "away")
    entity = _make_entity(home_status, homes_data)
    assert entity.preset_mode == PRESET_AWAY


def test_optimistic_preset_takes_priority(entity):
    """An optimistic preset overrides the underlying room mode."""
    entity._optimistic_preset = PRESET_AWAY
    assert entity.preset_mode == PRESET_AWAY


def test_hvac_action_idle_when_not_heating(home_status, homes_data):
    """No heating request and no boiler firing reports IDLE."""
    home_status["body"]["home"]["rooms"][0]["heating_power_request"] = 0
    for module in home_status["body"]["home"]["modules"]:
        module["boiler_status"] = False
    entity = _make_entity(home_status, homes_data)
    assert entity.hvac_action == HVACAction.IDLE


def test_extra_state_attributes(entity):
    """extra_state_attributes exposes room + coordinator health."""
    attrs = entity.extra_state_attributes
    assert attrs["room_id"] == "room-1"
    assert attrs["heating_power_request"] == 50
    assert attrs["netatmo_setpoint_mode"] == "schedule"
    assert attrs["data_stale"] is False
    assert attrs["last_update_successful"] is True
    assert attrs["consecutive_failures"] == 0


async def test_set_temperature_without_temp_returns(home_status, homes_data):
    """set_temperature without a temperature is a no-op."""
    api = MagicMock()
    api.async_set_room_thermpoint = AsyncMock()
    entity = _entity_with_api(home_status, homes_data, api=api)
    _run_api_call_verification(entity)
    result = await entity.async_set_temperature()
    assert result is None
    api.async_set_room_thermpoint.assert_not_awaited()


async def test_set_preset_unknown_preset_returns(home_status, homes_data):
    """An unmapped preset is a no-op (no API call)."""
    api = MagicMock()
    api.async_set_therm_mode = AsyncMock()
    entity = _entity_with_api(home_status, homes_data, api=api)
    _run_api_call_verification(entity)
    entity.async_write_ha_state = MagicMock()
    result = await entity.async_set_preset_mode("not-a-preset")
    assert result is None
    api.async_set_therm_mode.assert_not_awaited()
