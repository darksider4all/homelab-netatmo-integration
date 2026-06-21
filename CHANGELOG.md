# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - Unreleased

Production-hardening release. No breaking changes — the `netatmo_custom` domain and the
`netatmo_{home_id}_{room_id}` entity unique-id scheme are unchanged, so existing entities and
automations are preserved.

### Added
- Reauthentication flow: token-refresh failures now trigger a Home Assistant reauth prompt
  (`ConfigEntryAuthFailed`) instead of failing silently.
- `system_health.py` reporting Netatmo API reachability.
- `async_remove_entry` (clean webhook teardown on removal) and an `async_migrate_entry` scaffold.
- Diagnostics now include redacted coordinator health (last update, consecutive failures, update
  interval, webhook status, staleness).
- Full test suite (`pytest-homeassistant-custom-component`) covering API retry/rate-limit/error
  paths, coordinator behaviour, config + reauth flow, webhook handling, and entity logic.
- Tooling: `ruff`, `mypy`, `pre-commit`, `py.typed`, and a CI workflow running lint + types + tests.
- `manifest.json` now declares `integration_type: "hub"`.

### Changed
- Setup failures now raise `ConfigEntryNotReady` so Home Assistant retries automatically (previously
  swallowed by a broad `except` that returned `False`).
- `hvac_action` reports `HEATING` when the boiler is firing, not only on heating-power requests.
- Climate state-change verification delays moved to named constants in `const.py`.
- The `set_schedule` service now raises clear `ServiceValidationError`/`HomeAssistantError` messages.

### Security / Privacy
- Webhook handler no longer logs request bodies, enforces a payload size cap (413 on oversized),
  and decodes safely. Signatures are verified and rejected when both header and secret are present.
- Config flow no longer logs OAuth token structure or full `homesdata` responses.
- API client no longer includes raw response bodies in raised error messages.

### Fixed
- Removed dead code and an unnecessary `deepcopy` in the webhook coordinator path.
- Hardened against partial coordinator payloads in climate setup (no more `KeyError`).

### Known gaps (Gold tier, planned)
- Entity-name translations (`translation_key`) for sensors/binary sensors.
- `repairs.py` issues (e.g. missing external URL for webhooks).

## [1.1.1] - 2025
### Fixed
- Pre-register relay devices in the device registry to resolve `via_device` warnings.

## [1.1.0] - 2025
### Added
- HMAC-SHA256 signature verification for Netatmo webhooks.

## [1.0.2] - 2024
### Changed
- Enhanced API resilience; added retry for transient Netatmo error code 13.

## [1.0.1] - 2024
### Fixed
- Correct AUTO HVAC mode transition from OFF.

## [1.0.0] - 2024
### Added
- Initial release: OAuth2 config flow, climate/sensor/binary_sensor platforms, webhook support, and
  the `set_schedule` service.
