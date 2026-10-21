"""Climate platform for Netatmo Custom integration."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import (
    PRESET_AWAY,
    PRESET_HOME,
    PRESET_NONE,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import NetatmoAPI
from .const import (
    DOMAIN,
    ENTITY_PREFIX,
    MANUAL_SETPOINT_FALLBACK_MINUTES,
    MANUAL_SETPOINT_MAX_MINUTES,
    MAX_CONSECUTIVE_FAILURES,
    MAX_TEMP,
    MIN_TEMP,
    OPTIMISTIC_TEMP_HOLD_SECONDS,
    PRESET_FROST_GUARD,
    SETPOINT_GUARD_POLL_SECONDS,
    SETPOINT_GUARD_WINDOW_SECONDS,
    TEMP_STEP,
    VERIFY_MAX_RETRIES,
    VERIFY_PROPAGATION_DELAY,
    VERIFY_RETRY_BASE_DELAY,
    VERIFY_SETTLE_DELAY,
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
    coordinator: NetatmoDataUpdateCoordinator = entry.runtime_data.coordinator
    home_id: str = entry.runtime_data.home_id

    # Get home data (defensive: a partial payload should add zero entities, not crash)
    homes_data = (coordinator.data or {}).get("homes_data", {}).get("body", {}).get("homes", [])
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

    # Find the NAPlug relay module ID
    relay_module_id = None
    for m in modules:
        if m.get("type") == "NAPlug":
            relay_module_id = m["id"]
            break

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
                NetatmoThermostat(
                    coordinator, room, home_id, home_name, thermostat_module, relay_module_id
                )
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
}


class NetatmoThermostat(CoordinatorEntity, ClimateEntity):
    """Netatmo thermostat climate entity."""

    PARALLEL_UPDATES = 0
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
        relay_module_id: str | None = None,
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
        # Last setpoint applied by the schedule; kept so the governing schedule can
        # still be identified after a manual override has taken the room out of
        # schedule mode.
        self._last_schedule_setpoint: float | None = None
        self._module = module
        self._relay_module_id = relay_module_id
        self._optimistic_preset: str | None = None  # For immediate UI updates
        # Setpoint written by the user but not yet confirmed by the cloud. Kept
        # for a short window so an immediate cloud cancellation cannot snap the
        # UI (and Google's state report) back to the schedule value.
        self._optimistic_temperature: float | None = None
        self._optimistic_temperature_until: float = 0.0
        # Incremented on every user setpoint write; a guard task from an older
        # write exits as soon as it notices a newer one.
        self._setpoint_generation: int = 0
        self._setpoint_guard_task: asyncio.Task | None = None

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
            via_device=(DOMAIN, relay_module_id)
            if module_type != "NAPlug" and relay_module_id
            else None,
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
        """Return target temperature.

        A value just written by the user wins for a short window, so a cloud
        report that still carries the schedule setpoint cannot make the UI (or a
        Google state query) bounce back to it.
        """
        if (
            self._optimistic_temperature is not None
            and time.time() < self._optimistic_temperature_until
        ):
            return self._optimistic_temperature
        status = self._get_room_status()
        return status.get("therm_setpoint_temperature") if status else None

    def _set_optimistic_temperature(self, temperature: float) -> None:
        """Show a just-written setpoint immediately, before the cloud confirms it."""
        self._optimistic_temperature = temperature
        self._optimistic_temperature_until = time.time() + OPTIMISTIC_TEMP_HOLD_SECONDS
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()

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

        # Check if currently heating.
        # Netatmo returns heating_power_request as a percentage (0-100); >0 means
        # the valve is open / heat is requested.
        heating_power = status.get("heating_power_request", 0)

        # Also check the home's boiler status (a thermostat with the boiler firing).
        boiler_status = False
        home_status = (
            (self.coordinator.data or {}).get("home_status", {}).get("body", {}).get("home", {})
        )
        for module in home_status.get("modules", []):
            if module.get("type") in ("NATherm1", "OTH", "OTM") and (
                module.get("boiler_status") is True
            ):
                boiler_status = True
                break

        if heating_power > 0 or boiler_status:
            return HVACAction.HEATING

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
            if status.get("therm_setpoint_end_time"):
                attrs["netatmo_setpoint_end_time"] = dt_util.as_local(
                    datetime.fromtimestamp(status["therm_setpoint_end_time"], dt_util.UTC)
                ).isoformat()
            attrs["anticipating"] = status.get("anticipating", False)
            attrs["open_window"] = status.get("open_window", False)

        # Add coordinator health info
        if self.coordinator.data:
            attrs["data_stale"] = self.coordinator.data.get("stale", False)
            attrs["last_update_successful"] = self.coordinator.data.get("update_successful", True)
            if self.coordinator.data.get("last_error"):
                attrs["last_error"] = self.coordinator.data.get("last_error")

        attrs["consecutive_failures"] = self.coordinator.consecutive_failures

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Consider unavailable if too many consecutive failures
        if self.coordinator.consecutive_failures > MAX_CONSECUTIVE_FAILURES:
            return False
        return super().available

    async def _async_call_api_with_verification(
        self,
        api_call: Callable[[], Awaitable[Any]],
        verification_func: Callable[[], bool],
        description: str,
        max_retries: int = VERIFY_MAX_RETRIES,
    ) -> bool:
        """Call API and verify the change was applied.

        Args:
            api_call: Async function to call the API
            verification_func: Sync function that returns True if change was applied
            description: Description of the action for logging
            max_retries: Maximum retry attempts

        Returns:
            True if change was verified, False otherwise
        """
        for attempt in range(max_retries + 1):
            try:
                await api_call()
                # Wait for state to propagate (Netatmo can be slow to apply setpoints)
                await asyncio.sleep(VERIFY_PROPAGATION_DELAY)
                await self.coordinator.async_request_refresh()
                await asyncio.sleep(VERIFY_SETTLE_DELAY)

                if verification_func():
                    if attempt > 0:
                        _LOGGER.info("%s succeeded after %d attempts", description, attempt + 1)
                    return True
                _LOGGER.warning(
                    "%s not verified after attempt %d/%d",
                    description,
                    attempt + 1,
                    max_retries + 1,
                )
            except Exception as err:
                _LOGGER.warning("%s failed (attempt %d): %s", description, attempt + 1, err)

            if attempt < max_retries:
                # Increasing delay between retries
                delay = VERIFY_RETRY_BASE_DELAY * (attempt + 1)
                _LOGGER.info("Retrying %s in %ds...", description, delay)
                await asyncio.sleep(delay)

        _LOGGER.error(f"{description} failed after {max_retries + 1} attempts")
        return False

    def _active_schedules(self) -> tuple[list[dict[str, Any]], str | None]:
        """Return the schedules governing this room's setpoints, plus the home timezone.

        The homesdata payload does not always carry the active program id, so when
        it is missing we infer it from the setpoint currently applied by the
        schedule: any schedule containing a zone with that exact room target is
        treated as a candidate (the earliest upcoming boundary wins, which errs
        towards a shorter override rather than a longer one).
        """
        homes = ((self.coordinator.data or {}).get("homes_data") or {}).get("body", {}).get(
            "homes"
        ) or []
        home = next((h for h in homes if h.get("id") == self._home_id), None)
        if not home:
            return [], None

        schedules = home.get("schedules") or []
        timezone = home.get("timezone")

        program_id = home.get("therm_program") or home.get("schedule_id")
        if program_id:
            active = [s for s in schedules if s.get("id") == program_id]
            if active:
                return active, timezone
            return schedules, timezone

        status = self._get_room_status() or {}
        if status.get("therm_setpoint_mode") == "schedule":
            target = status.get("therm_setpoint_temperature")
            if target is not None:
                self._last_schedule_setpoint = target
        else:
            # Room is under a manual override: fall back to the last scheduled
            # setpoint so the same schedule is chosen as on the first request.
            target = self._last_schedule_setpoint

        if target is not None:
            matched = [
                sched
                for sched in schedules
                if any(
                    abs((entry.get("temp") or -999) - target) < 0.01
                    for zone in sched.get("zones") or []
                    for entry in zone.get("rooms_temp") or []
                    if entry.get("room_id") == self._room_id
                )
            ]
            if matched:
                return matched, timezone

        return schedules, timezone

    def _handle_coordinator_update(self) -> None:
        """Track the schedule setpoint across coordinator refreshes."""
        status = self._get_room_status() or {}
        if status.get("therm_setpoint_mode") == "schedule":
            setpoint = status.get("therm_setpoint_temperature")
            if setpoint is not None:
                self._last_schedule_setpoint = setpoint

        # Drop the optimistic value as soon as the cloud agrees, or when its
        # window lapses; never mask a genuine state indefinitely.
        if self._optimistic_temperature is not None:
            cloud_temp = status.get("therm_setpoint_temperature")
            agreed = (
                status.get("therm_setpoint_mode") == "manual"
                and cloud_temp is not None
                and abs(cloud_temp - self._optimistic_temperature) < TEMP_STEP
            )
            if agreed or time.time() >= self._optimistic_temperature_until:
                self._optimistic_temperature = None
                self._optimistic_temperature_until = 0.0

        super()._handle_coordinator_update()

    def _next_schedule_boundary(self, now_ts: int) -> int | None:
        """Return the unix timestamp of the next schedule change, if any."""
        schedules, timezone = self._active_schedules()

        offsets: list[int] = []
        for sched in schedules:
            for entry in sched.get("timetable") or []:
                offset = entry.get("m_offset")
                if isinstance(offset, int):
                    offsets.append(offset)
        if not offsets:
            return None

        tz = dt_util.get_time_zone(timezone) if timezone else None
        if tz is None:
            tz = dt_util.DEFAULT_TIME_ZONE

        now_local = datetime.fromtimestamp(now_ts, tz)
        week_start = (now_local - timedelta(days=now_local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        now_offset = int((now_local - week_start).total_seconds() // 60)

        upcoming: list[int] = []
        for offset in offsets:
            for week in (0, 1):
                candidate = offset + week * 10080
                if candidate > now_offset:
                    upcoming.append(candidate)
                    break
        if not upcoming:
            return None
        return int((week_start + timedelta(minutes=min(upcoming))).timestamp())

    def _manual_setpoint_minutes(self) -> int:
        """Return the home's configured manual-setpoint duration.

        This is the "cooldown" set in the Netatmo app
        (`therm_setpoint_default_duration`, 90 minutes on this home).
        """
        homes = ((self.coordinator.data or {}).get("homes_data") or {}).get("body", {}).get(
            "homes"
        ) or []
        home = next((h for h in homes if h.get("id") == self._home_id), None)
        value = (home or {}).get("therm_setpoint_default_duration")
        if isinstance(value, int | float) and value > 0:
            return int(min(max(value, 5), MANUAL_SETPOINT_MAX_MINUTES))
        return MANUAL_SETPOINT_FALLBACK_MINUTES

    def _manual_setpoint_endtime(self) -> int:
        """Return an explicit endtime for a manual setpoint.

        Without an endtime Netatmo applies the home's default duration anyway and
        then returns the room to the schedule; sending it explicitly makes the
        behaviour deterministic and identical to the Netatmo app. A schedule
        boundary inside the window shortens it, never extends it.
        """
        now_ts = int(time.time())
        duration = self._manual_setpoint_minutes() * 60
        endtime = now_ts + duration
        boundary = self._next_schedule_boundary(now_ts)
        # A boundary less than 5 minutes away is useless as an override window.
        if boundary is not None and 300 <= boundary - now_ts < duration:
            return boundary
        return endtime

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return

        api: NetatmoAPI = self.coordinator.api
        endtime = self._manual_setpoint_endtime()
        _LOGGER.debug(
            "Setting manual setpoint %.1f until %s",
            temp,
            dt_util.as_local(datetime.fromtimestamp(endtime, dt_util.UTC)),
        )

        self._setpoint_generation += 1
        generation = self._setpoint_generation
        self._set_optimistic_temperature(temp)

        async def api_call():
            await api.async_set_room_thermpoint(
                self._home_id, self._room_id, mode="manual", temp=temp, endtime=endtime
            )

        def verify() -> bool:
            # Read the raw cloud value, never the optimistic one: verification
            # has to prove the cloud accepted the write, not that the UI shows it.
            status = self._get_room_status() or {}
            current_temp = status.get("therm_setpoint_temperature")
            # Use TEMP_STEP as tolerance since that's the smallest increment
            return current_temp is not None and abs(current_temp - temp) < TEMP_STEP

        success = await self._async_call_api_with_verification(
            api_call, verify, f"Set temperature to {temp}"
        )

        if not success:
            # Force one more refresh attempt
            await self.coordinator.async_request_refresh()
            return

        self._async_start_setpoint_guard(temp, endtime, generation)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        api: NetatmoAPI = self.coordinator.api

        heat_target: float | None = None
        heat_endtime: int | None = None
        generation: int | None = None
        if hvac_mode == HVACMode.HEAT:
            heat_target = self.target_temperature or 19.0
            heat_endtime = self._manual_setpoint_endtime()
            self._setpoint_generation += 1
            generation = self._setpoint_generation
            self._set_optimistic_temperature(heat_target)

        async def api_call():
            if hvac_mode == HVACMode.OFF:
                await api.async_set_room_thermpoint(self._home_id, self._room_id, mode="off")
            elif hvac_mode == HVACMode.HEAT:
                await api.async_set_room_thermpoint(
                    self._home_id,
                    self._room_id,
                    mode="manual",
                    temp=heat_target,
                    endtime=heat_endtime,
                )
            elif hvac_mode == HVACMode.AUTO:
                await api.async_set_room_thermpoint(self._home_id, self._room_id, mode="home")

        def verify() -> bool:
            return self.hvac_mode == hvac_mode

        success = await self._async_call_api_with_verification(
            api_call, verify, f"Set HVAC mode to {hvac_mode}"
        )

        if (
            success
            and heat_target is not None
            and heat_endtime is not None
            and generation is not None
        ):
            self._async_start_setpoint_guard(heat_target, heat_endtime, generation)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        api: NetatmoAPI = self.coordinator.api

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

        # Set optimistic state for immediate UI feedback
        self._optimistic_preset = preset_mode
        self.async_write_ha_state()

        async def api_call():
            await api.async_set_therm_mode(self._home_id, mode=netatmo_mode)

        def verify() -> bool:
            # Check actual state (not optimistic)
            room_status = self._get_room_status()
            if not room_status:
                return False
            actual_mode = room_status.get("therm_setpoint_mode")
            if preset_mode == PRESET_FROST_GUARD:
                return actual_mode in ("hg", "frost guard")
            elif preset_mode in (PRESET_HOME, PRESET_NONE):
                return actual_mode == "schedule"
            elif preset_mode == PRESET_AWAY:
                return actual_mode == "away"
            return False

        try:
            success = await self._async_call_api_with_verification(
                api_call, verify, f"Set preset to {preset_mode}"
            )
            if not success:
                _LOGGER.error(f"Failed to verify preset change to {preset_mode}")
        finally:
            # Clear optimistic state regardless of outcome
            self._optimistic_preset = None
            self.async_write_ha_state()

    def _async_start_setpoint_guard(
        self, temperature: float, endtime: int, generation: int
    ) -> None:
        """Schedule the bounded post-write guard for this setpoint."""
        if self._setpoint_guard_task is not None and not self._setpoint_guard_task.done():
            self._setpoint_guard_task.cancel()

        coro = self._async_guard_setpoint(temperature, endtime, generation)
        hass = getattr(self, "hass", None)
        if hass is None:
            coro.close()
            return
        self._setpoint_guard_task = hass.async_create_task(coro)

    async def _async_guard_setpoint(
        self, temperature: float, endtime: int, generation: int
    ) -> None:
        """Re-assert a manual setpoint once if the cloud cancels it immediately.

        Netatmo has been seen to accept setroomthermpoint, report the room back
        in "schedule" mode ~10 s later and stop the boiler. Verification only
        checks the write itself, so the cancellation stayed visible until the
        next user action. This watches the short window after a write and
        re-sends the setpoint exactly once; a newer write supersedes it.
        """
        started = time.monotonic()
        deadline = started + SETPOINT_GUARD_WINDOW_SECONDS
        try:
            while time.monotonic() < deadline:
                await asyncio.sleep(SETPOINT_GUARD_POLL_SECONDS)
                if generation != self._setpoint_generation:
                    return
                status = self._get_room_status() or {}
                if status.get("therm_setpoint_mode") != "schedule":
                    return

                _LOGGER.warning(
                    "Netatmo cancelled the manual setpoint (%.1f °C) %.0f s after "
                    "accepting it; re-asserting once",
                    temperature,
                    time.monotonic() - started,
                )
                await self.coordinator.api.async_set_room_thermpoint(
                    self._home_id,
                    self._room_id,
                    mode="manual",
                    temp=temperature,
                    endtime=endtime,
                )
                await self.coordinator.async_request_refresh()
                self._set_optimistic_temperature(temperature)
                return
        except asyncio.CancelledError:
            raise
        except Exception as err:  # a guard must never break the entity
            _LOGGER.warning("Setpoint guard failed: %s", err)
        finally:
            if self._setpoint_guard_task is asyncio.current_task():
                self._setpoint_guard_task = None

    async def async_will_remove_from_hass(self) -> None:
        """Cancel a pending setpoint guard when the entity is removed."""
        if self._setpoint_guard_task is not None and not self._setpoint_guard_task.done():
            self._setpoint_guard_task.cancel()
            self._setpoint_guard_task = None
        await super().async_will_remove_from_hass()

    def _get_room_status(self) -> dict | None:
        """Get room status from coordinator data."""
        return _get_room_status(self.coordinator.data, self._room_id)
