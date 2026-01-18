"""Climate platform for Netatmo Custom integration."""
import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import (
    HVACAction,
    HVACMode,
    PRESET_AWAY,
    PRESET_HOME,
    PRESET_NONE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NetatmoAPI
from .const import (
    DATA_API,
    DATA_COORDINATOR,
    DATA_HOME_ID,
    DOMAIN,
    ENTITY_PREFIX,
    MAX_TEMP,
    MIN_TEMP,
    PRESET_FROST_GUARD,
    TEMP_STEP,
)
from .coordinator import NetatmoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Device type mapping
DEVICE_TYPES = {
    "NATherm1": "Smart Thermostat",
    "NRV": "Smart Radiator Valve",
    "NAPlug": "Relay",
    "OTH": "OpenTherm Thermostat",
    "OTM": "Modulating Thermostat",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Netatmo climate entities.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: NetatmoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    home_id: str = hass.data[DOMAIN][entry.entry_id][DATA_HOME_ID]

    # Get home data
    homes_data = coordinator.data["homes_data"]["body"]["homes"]
    rooms = []
    modules = []
    home_name = "Netatmo Home"

    for home in homes_data:
        if home["id"] == home_id:
            rooms = home.get("rooms", [])
            modules = home.get("modules", [])
            home_name = home.get("name", "Netatmo Home")
            break

    # Build module lookup by ID
    module_lookup = {m["id"]: m for m in modules}

    # Create climate entity for each room with thermostat
    entities = []
    for room in rooms:
        # Check if room has a thermostat (has therm_setpoint_mode)
        room_status = _get_room_status(coordinator.data, room["id"])
        if room_status and "therm_setpoint_mode" in room_status:
            # Find the thermostat module for this room
            room_module_ids = room.get("module_ids", [])
            thermostat_module = None
            for mid in room_module_ids:
                mod = module_lookup.get(mid)
                if mod and mod.get("type") in ["NATherm1", "OTH", "OTM", "NRV"]:
                    thermostat_module = mod
                    break

            entities.append(
                NetatmoThermostat(coordinator, room, home_id, home_name, thermostat_module)
            )

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homelab Climate entities")


def _get_room_status(data: dict, room_id: str) -> dict | None:
    """Get room status from coordinator data.

    Args:
        data: Coordinator data
        room_id: Room ID

    Returns:
        Room status dict or None
    """
    home_status = data.get("home_status", {}).get("body", {}).get("home", {})
    for room in home_status.get("rooms", []):
        if room["id"] == room_id:
            return room
    return None


PRESET_MODE_ICONS = {
    PRESET_HOME: "mdi:home-thermometer",
    PRESET_AWAY: "mdi:home-export-outline",
    PRESET_FROST_GUARD: "mdi:snowflake-thermometer",
    PRESET_NONE: "mdi:thermostat",
    "Frost Guard": "mdi:snowflake-thermometer",  # Also handle string directly
}


class NetatmoThermostat(CoordinatorEntity, ClimateEntity):
    """Netatmo thermostat climate entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TEMP_STEP
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP

    def __init__(
        self,
        coordinator: NetatmoDataUpdateCoordinator,
        room: dict,
        home_id: str,
        home_name: str,
        module: dict | None,
    ):
        """Initialize the thermostat.

        Args:
            coordinator: Data update coordinator
            room: Room data from homes_data
            home_id: Netatmo home ID
            home_name: Netatmo home name
            module: Module data (thermostat/valve)
        """
        super().__init__(coordinator)
        self._room = room
        self._home_id = home_id
        self._room_id = room["id"]
        self._module = module
        self._optimistic_preset = None  # For immediate UI updates

        # Get module info
        module_id = module["id"] if module else room["id"]
        module_type = module.get("type", "NATherm1") if module else "NATherm1"
        module_name = module.get("name", room["name"]) if module else room["name"]

        # Entity attributes
        self._attr_unique_id = f"{ENTITY_PREFIX}_{home_id}_{self._room_id}"
        self._attr_name = "Climate"  # Will show as "Device Name Climate"
        self._attr_has_entity_name = True

        # Device info - groups entities under a device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module_id)},
            name=module_name,
            manufacturer="Netatmo",
            model=DEVICE_TYPES.get(module_type, module_type),
            via_device=(DOMAIN, f"{home_id}_relay") if module_type != "NAPlug" else None,
            configuration_url="https://my.netatmo.com",
        )

        # Supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        )

        # Supported modes
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.AUTO, HVACMode.OFF]
        self._attr_preset_modes = [
            PRESET_HOME,
            PRESET_AWAY,
            PRESET_FROST_GUARD,
            PRESET_NONE,
        ]

    @property
    def icon(self) -> str:
        """Return icon based on current preset mode."""
        return PRESET_MODE_ICONS.get(self.preset_mode, "mdi:thermostat")

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature."""
        status = self._get_room_status()
        return status.get("therm_measured_temperature") if status else None

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        status = self._get_room_status()
        return status.get("therm_setpoint_temperature") if status else None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return HVAC mode."""
        status = self._get_room_status()
        if not status:
            return HVACMode.OFF

        mode = status.get("therm_setpoint_mode")

        # Map Netatmo modes to HA HVACMode
        if mode == "off":
            return HVACMode.OFF
        elif mode in ["manual", "max", "home"]:
            return HVACMode.HEAT
        elif mode == "schedule":
            return HVACMode.AUTO

        return HVACMode.AUTO

    @property
    def hvac_action(self) -> HVACAction:
        """Return current heating action."""
        status = self._get_room_status()
        if not status:
            return HVACAction.OFF

        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        # Check if currently heating
        heating_power = status.get("heating_power_request", 0)
        if heating_power > 0:
            return HVACAction.HEATING
        else:
            return HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        """Return current preset mode."""
        # Check for optimistic update first
        if hasattr(self, "_optimistic_preset") and self._optimistic_preset:
            return self._optimistic_preset

        # Get room-level setpoint mode
        room_status = self._get_room_status()
        setpoint_mode = room_status.get("therm_setpoint_mode") if room_status else None

        # Map Netatmo room setpoint modes to HA presets
        if setpoint_mode == "schedule":
            return PRESET_HOME
        elif setpoint_mode == "away":
            return PRESET_AWAY
        elif setpoint_mode in ("hg", "frost guard"):
            return PRESET_FROST_GUARD
        # off, manual, max, or unknown modes
        return PRESET_NONE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        status = self._get_room_status()

        attrs = {
            "room_id": self._room_id,
        }

        if status:
            attrs["heating_power_request"] = status.get("heating_power_request", 0)
            attrs["netatmo_setpoint_mode"] = status.get("therm_setpoint_mode")
            attrs["anticipating"] = status.get("anticipating", False)
            attrs["open_window"] = status.get("open_window", False)

        return attrs

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return

        api: NetatmoAPI = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id][
            DATA_API
        ]

        try:
            await api.async_set_room_thermpoint(
                self._home_id, self._room_id, mode="manual", temp=temp
            )
            # Request refresh to update state
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set temperature: {err}")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        api: NetatmoAPI = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id][
            DATA_API
        ]

        try:
            if hvac_mode == HVACMode.OFF:
                await api.async_set_room_thermpoint(
                    self._home_id, self._room_id, mode="off"
                )
            elif hvac_mode == HVACMode.HEAT:
                # Set to manual mode with current target temp
                target = self.target_temperature or 19.0
                await api.async_set_room_thermpoint(
                    self._home_id, self._room_id, mode="manual", temp=target
                )
            elif hvac_mode == HVACMode.AUTO:
                # Set home to schedule mode
                await api.async_set_therm_mode(self._home_id, mode="schedule")

            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set HVAC mode: {err}")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        api: NetatmoAPI = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id][
            DATA_API
        ]

        # Map HA presets to Netatmo modes
        mode_map = {
            PRESET_HOME: "schedule",
            PRESET_AWAY: "away",
            PRESET_FROST_GUARD: "hg",
            PRESET_NONE: "schedule",
        }

        netatmo_mode = mode_map.get(preset_mode)
        if not netatmo_mode:
            return

        try:
            self._optimistic_preset = preset_mode
            self.async_write_ha_state()

            await api.async_set_therm_mode(self._home_id, mode=netatmo_mode)

            self._optimistic_preset = None
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set preset mode: {err}")
            self._optimistic_preset = None
            self.async_write_ha_state()

    def _get_room_status(self) -> dict | None:
        """Get room status from coordinator data."""
        return _get_room_status(self.coordinator.data, self._room_id)
