"""Sensor platform for Netatmo Custom integration."""
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_COORDINATOR,
    DATA_HOME_ID,
    DOMAIN,
    ENTITY_PREFIX,
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

# Battery state mapping to percentage
BATTERY_STATE_MAP = {
    "full": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
    "very low": 10,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Netatmo sensor entities.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: NetatmoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    home_id: str = hass.data[DOMAIN][entry.entry_id][DATA_HOME_ID]

    entities = []

    # Get modules from homestatus
    home_status = coordinator.data.get("home_status", {}).get("body", {}).get("home", {})
    modules = home_status.get("modules", [])

    # Get module names from homesdata
    homes_data = coordinator.data.get("homes_data", {}).get("body", {}).get("homes", [])
    module_names = {}
    for home in homes_data:
        if home["id"] == home_id:
            for module in home.get("modules", []):
                module_names[module["id"]] = module.get("name", module["id"])
            break

    # Create battery sensors for each module with battery
    for module in modules:
        module_id = module.get("id")
        module_type = module.get("type")

        # Skip modules without batteries (like NAPlug relay)
        if module_type == "NAPlug":
            continue

        # Only create sensors for known device types with batteries
        if module_type in ["NATherm1", "NRV", "OTH", "OTM"]:
            module_name = module_names.get(module_id, module_id)

            # Battery level sensor
            entities.append(
                NetatmoBatteryLevelSensor(
                    coordinator, module_id, module_name, module_type, home_id
                )
            )

            # Battery state sensor
            entities.append(
                NetatmoBatteryStateSensor(
                    coordinator, module_id, module_name, module_type, home_id
                )
            )

            # RF signal strength sensor
            entities.append(
                NetatmoSignalStrengthSensor(
                    coordinator, module_id, module_name, module_type, home_id, "rf"
                )
            )

    # Add WiFi signal sensor for NAPlug (relay)
    for module in modules:
        module_id = module.get("id")
        module_type = module.get("type")

        if module_type == "NAPlug":
            module_name = module_names.get(module_id, "Relay")
            entities.append(
                NetatmoSignalStrengthSensor(
                    coordinator, module_id, module_name, module_type, home_id, "wifi"
                )
            )
            entities.append(
                NetatmoSignalStrengthSensor(
                    coordinator, module_id, module_name, module_type, home_id, "rf"
                )
            )

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Netatmo sensors")


class NetatmoBatteryLevelSensor(CoordinatorEntity, SensorEntity):
    """Battery level sensor for Netatmo devices."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NetatmoDataUpdateCoordinator,
        module_id: str,
        module_name: str,
        module_type: str,
        home_id: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._module_id = module_id
        self._module_type = module_type
        self._home_id = home_id

        self._attr_unique_id = f"{ENTITY_PREFIX}_{home_id}_{module_id}_battery"
        self._attr_name = "Battery"

        # Device info - links to parent device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module_id)},
            name=module_name,
            manufacturer="Netatmo",
            model=DEVICE_TYPES.get(module_type, module_type),
            via_device=(DOMAIN, f"{home_id}_relay") if module_type != "NAPlug" else None,
        )

    @property
    def native_value(self) -> int | None:
        """Return battery level percentage."""
        module = self._get_module()
        if not module:
            return None

        # First try battery_state for percentage
        battery_state = module.get("battery_state")
        if battery_state:
            return BATTERY_STATE_MAP.get(battery_state.lower(), 50)

        # Fallback: calculate from battery_level (mV)
        # Typical range: 2400mV (empty) to 3100mV (full) for NRV
        # NATherm1: 2200mV to 3200mV
        battery_mv = module.get("battery_level")
        if battery_mv:
            if self._module_type == "NRV":
                # NRV valve: 2400-3100mV range
                percentage = int((battery_mv - 2400) / (3100 - 2400) * 100)
            else:
                # Thermostat: 2200-3200mV range
                percentage = int((battery_mv - 2200) / (3200 - 2200) * 100)
            return max(0, min(100, percentage))

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        module = self._get_module()
        if not module:
            return {}

        return {
            "battery_voltage_mv": module.get("battery_level"),
            "battery_state": module.get("battery_state"),
            "module_type": DEVICE_TYPES.get(self._module_type, self._module_type),
            "module_id": self._module_id,
        }

    def _get_module(self) -> dict | None:
        """Get module data from coordinator."""
        home_status = self.coordinator.data.get("home_status", {}).get("body", {}).get("home", {})
        for module in home_status.get("modules", []):
            if module.get("id") == self._module_id:
                return module
        return None


class NetatmoBatteryStateSensor(CoordinatorEntity, SensorEntity):
    """Battery state sensor for Netatmo devices."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_options = ["full", "high", "medium", "low", "very low", "unknown"]

    def __init__(
        self,
        coordinator: NetatmoDataUpdateCoordinator,
        module_id: str,
        module_name: str,
        module_type: str,
        home_id: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._module_id = module_id
        self._module_type = module_type
        self._home_id = home_id

        self._attr_unique_id = f"{ENTITY_PREFIX}_{home_id}_{module_id}_battery_state"
        self._attr_name = "Battery state"

        # Device info - links to parent device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module_id)},
        )

    @property
    def native_value(self) -> str | None:
        """Return battery state."""
        module = self._get_module()
        if not module:
            return None

        return module.get("battery_state", "unknown")

    @property
    def icon(self) -> str:
        """Return icon based on battery state."""
        state = self.native_value
        if state == "full":
            return "mdi:battery"
        elif state == "high":
            return "mdi:battery-70"
        elif state == "medium":
            return "mdi:battery-50"
        elif state == "low":
            return "mdi:battery-30"
        elif state == "very low":
            return "mdi:battery-alert"
        return "mdi:battery-unknown"

    def _get_module(self) -> dict | None:
        """Get module data from coordinator."""
        home_status = self.coordinator.data.get("home_status", {}).get("body", {}).get("home", {})
        for module in home_status.get("modules", []):
            if module.get("id") == self._module_id:
                return module
        return None


class NetatmoSignalStrengthSensor(CoordinatorEntity, SensorEntity):
    """Signal strength sensor for Netatmo devices."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "dB"

    def __init__(
        self,
        coordinator: NetatmoDataUpdateCoordinator,
        module_id: str,
        module_name: str,
        module_type: str,
        home_id: str,
        signal_type: str,  # "rf" or "wifi"
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._module_id = module_id
        self._module_type = module_type
        self._home_id = home_id
        self._signal_type = signal_type

        self._attr_unique_id = f"{ENTITY_PREFIX}_{home_id}_{module_id}_{signal_type}_signal"
        self._attr_name = f"{'WiFi' if signal_type == 'wifi' else 'RF'} signal"

        if signal_type == "wifi":
            self._attr_icon = "mdi:wifi"
        else:
            self._attr_icon = "mdi:signal"

        # Device info - links to parent device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module_id)},
        )

    @property
    def native_value(self) -> int | None:
        """Return signal strength."""
        module = self._get_module()
        if not module:
            return None

        if self._signal_type == "wifi":
            return module.get("wifi_strength")
        else:
            return module.get("rf_strength")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        value = self.native_value
        if value is None:
            return {}

        # Signal quality interpretation
        if self._signal_type == "wifi":
            # WiFi: higher is better, typically 50-90
            if value >= 70:
                quality = "Excellent"
            elif value >= 50:
                quality = "Good"
            elif value >= 30:
                quality = "Fair"
            else:
                quality = "Poor"
        else:
            # RF: higher is better, typically 60-90
            if value >= 80:
                quality = "Excellent"
            elif value >= 60:
                quality = "Good"
            elif value >= 40:
                quality = "Fair"
            else:
                quality = "Poor"

        return {
            "signal_quality": quality,
            "module_type": DEVICE_TYPES.get(self._module_type, self._module_type),
        }

    def _get_module(self) -> dict | None:
        """Get module data from coordinator."""
        home_status = self.coordinator.data.get("home_status", {}).get("body", {}).get("home", {})
        for module in home_status.get("modules", []):
            if module.get("id") == self._module_id:
                return module
        return None
