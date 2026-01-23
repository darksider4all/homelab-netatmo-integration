# Netatmo Custom Thermostat

![Logo](logo.png)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

Custom Home Assistant integration for Netatmo Thermostats with enhanced local polling and webhook support. This integration is designed to replace or work alongside the native Netatmo integration to provide more granular control and faster updates for climate devices.

## Features

- **Fast Updates**: Uses webhooks for near-instant status updates from Netatmo.
- **Detailed Control**: Full support for heating modes including Schedule, Manual, Max, Off, and Frost Guard.
- **Schedule Management**: Dedicated service to switch between Netatmo schedules.
- **Sensors**: Battery levels, wifi signal strength, and firmware information.

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
   - Note: Since this repository uses `content_in_root`, you should copy all files (except `.git`, `.github`) into `custom_components/netatmo_custom`.
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

## Contributing

Issues and Pull Requests are welcome!

## License

MIT License. See [LICENSE](LICENSE) file for details.
