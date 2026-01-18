"""Binary sensor platform for Netatmo Custom integration."""
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Netatmo binary sensor entities.

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

    # Get module names from homesdata and find relay ID
    homes_data = coordinator.data.get("homes_data", {}).get("body", {}).get("homes", [])
    module_names = {}
    relay_id = None
    for home in homes_data:
        if home["id"] == home_id:
            for module in home.get("modules", []):
                module_names[module["id"]] = module.get("name", module["id"])
                if module.get("type") == "NAPlug":
                    relay_id = module["id"]
            break

    # Create boiler status sensor for thermostat modules
    for module in modules:
        module_id = module.get("id")
        module_type = module.get("type")

        # Boiler status is available on thermostats (NATherm1, OTH, OTM)
        if module_type in ["NATherm1", "OTH", "OTM"]:
            module_name = module_names.get(module_id, module_id)

            # Boiler status binary sensor
            entities.append(
                NetatmoBoilerStatusSensor(
                    coordinator, module_id, module_name, module_type, home_id
                )
            )

            # Anticipating binary sensor (pre-heating)
            entities.append(
                NetatmoAnticipatingStatusSensor(
                    coordinator, module_id, module_name, module_type, home_id
                )
            )

        # Reachable sensor for all modules
        module_name = module_names.get(module_id, module_id)
        entities.append(
            NetatmoReachableSensor(
                coordinator, module_id, module_name, module_type, home_id, relay_id
            )
        )

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Netatmo binary sensors")


class NetatmoBoilerStatusSensor(CoordinatorEntity, BinarySensorEntity):
    """Boiler status binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.HEAT
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

        self._attr_unique_id = f"{ENTITY_PREFIX}_{home_id}_{module_id}_boiler"
        self._attr_name = "Boiler"
        self._attr_icon = "mdi:fire"

        # Device info - links to parent device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module_id)},
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if boiler is firing."""
        module = self._get_module()
        if not module:
            return None

        return module.get("boiler_status", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        module = self._get_module()
        if not module:
            return {}

        return {
            "boiler_valve_comfort_boost": module.get("boiler_valve_comfort_boost", False),
            "module_type": DEVICE_TYPES.get(self._module_type, self._module_type),
        }

    def _get_module(self) -> dict | None:
        """Get module data from coordinator."""
        home_status = self.coordinator.data.get("home_status", {}).get("body", {}).get("home", {})
        for module in home_status.get("modules", []):
            if module.get("id") == self._module_id:
                return module
        return None


class NetatmoAnticipatingStatusSensor(CoordinatorEntity, BinarySensorEntity):
    """Anticipating (pre-heating) status binary sensor."""

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

        self._attr_unique_id = f"{ENTITY_PREFIX}_{home_id}_{module_id}_anticipating"
        self._attr_name = "Anticipating"
        self._attr_icon = "mdi:clock-fast"

        # Device info - links to parent device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module_id)},
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if thermostat is anticipating (pre-heating)."""
        module = self._get_module()
        if not module:
            return None

        return module.get("anticipating", False)

    def _get_module(self) -> dict | None:
        """Get module data from coordinator."""
        home_status = self.coordinator.data.get("home_status", {}).get("body", {}).get("home", {})
        for module in home_status.get("modules", []):
            if module.get("id") == self._module_id:
                return module
        return None


class NetatmoReachableSensor(CoordinatorEntity, BinarySensorEntity):
    """Device connectivity binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NetatmoDataUpdateCoordinator,
        module_id: str,
        module_name: str,
        module_type: str,
        home_id: str,
        relay_id: str | None,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._module_id = module_id
        self._module_type = module_type
        self._home_id = home_id

        self._attr_unique_id = f"{ENTITY_PREFIX}_{home_id}_{module_id}_reachable"
        self._attr_name = "Connectivity"

        # Device info - links to parent device (relay)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module_id)},
            name=module_name,
            manufacturer="Netatmo",
            model=DEVICE_TYPES.get(module_type, module_type),
            via_device=(DOMAIN, relay_id) if module_type != "NAPlug" and relay_id else None,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if device is reachable."""
        module = self._get_module()
        if not module:
            return None

        # NAPlug (relay) uses wifi_strength to indicate connectivity
        if self._module_type == "NAPlug":
            wifi_strength = module.get("wifi_strength")
            return wifi_strength is not None and wifi_strength > 0

        # Other modules use reachable field
        return module.get("reachable", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        module = self._get_module()
        if not module:
            return {}

        return {
            "firmware_revision": module.get("firmware_revision"),
            "module_type": DEVICE_TYPES.get(self._module_type, self._module_type),
        }

    def _get_module(self) -> dict | None:
        """Get module data from coordinator."""
        home_status = self.coordinator.data.get("home_status", {}).get("body", {}).get("home", {})
        for module in home_status.get("modules", []):
            if module.get("id") == self._module_id:
                return module
        return None
