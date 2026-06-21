# Contributing

Thanks for your interest in improving the Homelab Climate (Netatmo Custom) integration!

## Development setup

This project targets **Python 3.12+** and Home Assistant **2024.1.0+**.

```bash
# Create a virtual environment (uv recommended; venv works too)
uv venv --python 3.12 .venv
source .venv/bin/activate

# Install dev & test dependencies
pip install -r requirements-test.txt
```

> Note: Home Assistant's test stack pulls in `acme`/`hass_nabucasa`, which require `josepy<2`.
> This is already pinned in `requirements-test.txt`.

## Quality checks

All of these run in CI on every push/PR. Run them locally before opening a PR:

```bash
ruff check custom_components tests      # lint
ruff format --check custom_components tests   # formatting
mypy custom_components/netatmo_custom   # type checking
pytest                                  # tests + coverage
```

Or install the git hooks to run them automatically:

```bash
pre-commit install
pre-commit run --all-files
```

## Tests

Tests use [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component).
Add or update tests under `tests/` for any behavioural change. Mock all network/OAuth calls — tests
must not hit the live Netatmo API.

## Guidelines

- **Do not change** the `netatmo_custom` domain or the `netatmo_{home_id}_{room_id}` entity
  `unique_id` scheme — doing so orphans existing users' entities and automations.
- Use lazy `%`-style logging (`_LOGGER.debug("x=%s", x)`), never f-strings in log calls.
- Never log tokens, secrets, full request/response bodies, or PII. Add new sensitive keys to
  `TO_REDACT` in `diagnostics.py`.
- Keep `requirements` in `manifest.json` empty unless a dependency is truly necessary.

## Releasing

1. Update `CHANGELOG.md` (move items out of *Unreleased*).
2. Bump `version` in `custom_components/netatmo_custom/manifest.json` and `pyproject.toml`.
3. Tag the release as `vX.Y.Z` and push the tag.
