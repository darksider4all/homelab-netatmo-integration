"""Webhook registration with Netatmo and the poller demotion (#11)."""

from unittest.mock import AsyncMock, MagicMock

import custom_components.netatmo_custom as init_module
from custom_components.netatmo_custom import _async_register_netatmo_webhook
from custom_components.netatmo_custom.const import UPDATE_INTERVAL, WEBHOOK_RECONCILE_INTERVAL
from custom_components.netatmo_custom.coordinator import NetatmoDataUpdateCoordinator

URL = "https://ha.example.test/api/webhook/abc123"


def _api(side_effect=None):
    api = MagicMock()
    api.async_add_webhook = AsyncMock(side_effect=side_effect)
    return api


async def test_registration_sends_the_url(monkeypatch):
    """A working registration returns True and sends the public URL once."""
    monkeypatch.setattr(init_module.asyncio, "sleep", AsyncMock())
    api = _api()
    assert await _async_register_netatmo_webhook(api, URL) is True
    api.async_add_webhook.assert_awaited_once_with(URL)


async def test_registration_retries_once_then_succeeds(monkeypatch):
    """The retry exists because Netatmo answers 400 while a URL propagates."""
    monkeypatch.setattr(init_module.asyncio, "sleep", AsyncMock())
    api = _api(side_effect=[RuntimeError("WH006 invalid webhook url"), None])
    assert await _async_register_netatmo_webhook(api, URL) is True
    assert api.async_add_webhook.await_count == 2


async def test_registration_failure_is_not_fatal(monkeypatch):
    """Two failures return False so the caller keeps polling at the old interval."""
    monkeypatch.setattr(init_module.asyncio, "sleep", AsyncMock())
    api = _api(side_effect=[RuntimeError("boom"), RuntimeError("boom")])
    assert await _async_register_netatmo_webhook(api, URL) is False
    assert api.async_add_webhook.await_count == 2


def test_reconcile_polling_slows_the_base_interval():
    """Once webhooks deliver, the timer only reconciles."""
    coordinator = object.__new__(NetatmoDataUpdateCoordinator)
    coordinator._base_update_interval = UPDATE_INTERVAL
    coordinator.webhook_active = False
    coordinator.update_interval = None

    coordinator.enable_reconcile_polling()

    assert coordinator._base_update_interval == WEBHOOK_RECONCILE_INTERVAL
    assert coordinator.update_interval.total_seconds() == WEBHOOK_RECONCILE_INTERVAL
    assert WEBHOOK_RECONCILE_INTERVAL > UPDATE_INTERVAL


def test_reconcile_polling_keeps_the_fast_interval_after_an_event():
    """An event already set the fast interval; don't undo it under the refresh."""
    coordinator = object.__new__(NetatmoDataUpdateCoordinator)
    coordinator._base_update_interval = UPDATE_INTERVAL
    coordinator.webhook_active = True
    coordinator.update_interval = None
    coordinator.enable_reconcile_polling()
    assert coordinator._base_update_interval == WEBHOOK_RECONCILE_INTERVAL
    assert coordinator.update_interval is None
