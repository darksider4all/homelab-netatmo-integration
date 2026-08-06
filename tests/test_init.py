"""Tests for integration setup-lifecycle helpers (migrate / remove)."""

from unittest.mock import MagicMock, patch

from custom_components.netatmo_custom import (
    async_migrate_entry,
    async_remove_entry,
)


async def test_migrate_entry_current_version(hass):
    """A current-version (1) entry needs no migration."""
    entry = MagicMock(version=1)
    assert await async_migrate_entry(hass, entry) is True


async def test_migrate_entry_future_version_refused(hass):
    """A newer-than-known version is refused rather than corrupted."""
    entry = MagicMock(version=2)
    assert await async_migrate_entry(hass, entry) is False


async def test_remove_entry_unregisters_webhook(hass):
    """Removing an entry unregisters its webhook."""
    entry = MagicMock()
    entry.data = {"webhook_id": "wh-123"}
    with patch("custom_components.netatmo_custom.async_unregister_webhook") as unregister:
        await async_remove_entry(hass, entry)
    unregister.assert_called_once_with(hass, "wh-123")


async def test_remove_entry_handles_missing_webhook(hass):
    """Removing an entry without a webhook id is a no-op."""
    entry = MagicMock()
    entry.data = {}
    # Should not raise.
    await async_remove_entry(hass, entry)
