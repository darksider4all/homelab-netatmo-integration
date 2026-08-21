# Netatmo Custom Thermostat

![Logo](custom_components/netatmo_custom/logo.png)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

Custom Home Assistant integration for Netatmo Thermostats with enhanced local polling and webhook support. This integration is designed to replace or work alongside the native Netatmo integration to provide more granular control and faster updates for climate devices.

## Features

- **Fast Updates**: Uses webhooks for near-instant status updates from Netatmo.
- **Detailed Control**: Full support for heating modes including Schedule, Manual, Max, Off, and Frost Guard.
- **Schedule Management**: Dedicated service to switch between Netatmo schedules.
- **Sensors**: Battery levels, wifi signal strength, and firmware information.
- **Resilient**: Automatic token refresh with reauth flow, request retry/backoff, rate-limiting, and graceful degradation to cached data during outages.

## Compatibility

- **Home Assistant**: 2024.1.0 or later.
- **Devices**: Smart Thermostat (NATherm1), Smart Radiator Valve (NRV), Relay (NAPlug), OpenTherm (OTH) and Modulating (OTM) thermostats.
- **No external Python dependencies** — only Home Assistant core libraries are used.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant.
2. Click on "Integrations" -> "Custom repositories" (via the 3-dot menu).
3. Add `https://github.com/darksider4all/homelab-netatmo-integration` as an **Integration**.
4. Click "Install".
5. Restart Home Assistant.
6. Go to Settings -> Devices & Services -> Add Integration -> Search for "Homelab Climate" (or Netatmo Custom).

### Manual Installation

1. Download the latest release.
2. Copy the contents of the repository into your Home Assistant `custom_components/netatmo_custom` directory.
   - Note: You should copy all the internal files (except `.git`, `.github`) into `custom_components/netatmo_custom`.
3. Restart Home Assistant.

## Configuration

1. You need a Netatmo Developer account and an App.
2. Get your Client ID and Client Secret from [dev.netatmo.com](https://dev.netatmo.com/).
3. Add the integration in Home Assistant. It will ask for your credentials or use Home Assistant Cloud linking if configured.
4. **Important**: For webhooks to work, your Home Assistant instance must be accessible from the internet (e.g., via Nabu Casa or a reverse proxy).

### Webhooks

Upon initialization, the integration will register a webhook with Netatmo.
Check the logs for the webhook URL to verify it's correct:
`Settings -> System -> Logs`

## Services

### `netatmo_custom.set_schedule`

Switch the home's heating schedule to a specific named schedule from your Netatmo account.

**Parameters:**
- `entity_id`: The climate entity (e.g., `climate.living_room`)
- `schedule_name`: The exact name of the schedule in your Netatmo app (case-sensitive).

## Triggers and conditions

**Triggers.** This integration does not register any device or event triggers of its
own. To react to Netatmo events in automations, use the standard entity-based triggers
that Home Assistant provides — for example a state trigger on a climate entity
(`climate.living_room`), a sensor entity (`sensor.living_room_battery`), or a binary
sensor entity (`binary_sensor.living_room_boiler`).

**Conditions.** This integration does not register any custom conditions. Use the
built-in Home Assistant conditions (state, numeric state, time, etc.) in your
automations as usual.

## Troubleshooting

- **Webhooks not firing / no fast updates**: Webhooks require an external URL. Set one under
  `Settings → System → Network → Home Assistant URL` (or use Home Assistant Cloud). Without it the
  integration still works via polling, just less promptly.
- **"Reauthentication needed" notification**: Netatmo periodically invalidates tokens. The integration
  raises a reauth flow automatically — open it and re-link your account; your devices, entities, and
  automations are preserved.
- **Entities show as unavailable**: This happens only after several consecutive update failures (a
  sustained API/network outage). The integration serves cached data first and recovers automatically.
- **Diagnostics**: Download diagnostics from the integration's device page for a redacted snapshot of
  coordinator health (last update, failures, interval, webhook status). Tokens and IDs are redacted.

## Removing the integration

1. In Home Assistant, go to **Settings → Devices & Services**.
2. Find the **Homelab Climate** entry in the integrations list.
3. Open the entry, click the three-dot menu (top right), and select **Delete**.
4. The integration unloads its platforms, removes its entities and devices, and
   unregisters its local webhook handler. Deleting the entry does **not** revoke the
   Netatmo app itself — if you also want to stop the app from accessing your Netatmo
   account, remove or disable it under **dev.netatmo.com → your app**.
5. (Optional) To remove the component files entirely, delete the
   `custom_components/netatmo_custom` directory from your Home Assistant
   configuration and restart Home Assistant.

## Development

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, linting,
type-checking, and running the test suite. CI runs `ruff`, `mypy`, `pytest`, `hassfest`, and HACS
validation on every push.

### Quality scale

This integration targets the Home Assistant **Silver** quality tier: config + reauth flow, unique IDs,
device info, diagnostics with redaction, automatic retry/recovery, and a test suite. Remaining
Gold-tier items (entity-name translations and `repairs.py` issues) are tracked in
[CHANGELOG.md](CHANGELOG.md).

## License

MIT License. See [LICENSE](LICENSE) file for details.
