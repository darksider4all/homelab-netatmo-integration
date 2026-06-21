"""Tests for the Netatmo webhook handler."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.netatmo_custom.const import MAX_WEBHOOK_BODY_BYTES
from custom_components.netatmo_custom.webhook import async_setup_webhook

WEBHOOK_ID = "test-webhook-id"
SECRET = "client-secret"


class FakeRequest:
    """Minimal stand-in for an aiohttp web.Request."""

    def __init__(self, body: bytes = b"", headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    async def read(self) -> bytes:
        return self._body


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
async def handler(hass):
    """Register a webhook and return (handler, coordinator)."""
    coordinator = MagicMock()
    coordinator.async_handle_webhook = AsyncMock()
    await async_setup_webhook(hass, WEBHOOK_ID, coordinator, client_secret=SECRET)
    registered = hass.data["webhook"][WEBHOOK_ID]["handler"]
    return registered, coordinator


async def test_valid_signature_accepted(hass, handler):
    """A correctly signed payload is processed and returns 200."""
    fn, coordinator = handler
    body = json.dumps({"push_type": "therm-mode"}).encode()
    request = FakeRequest(body, {"X-Netatmo-Secret": _sign(body)})
    response = await fn(hass, WEBHOOK_ID, request)
    assert response.status == 200
    coordinator.async_handle_webhook.assert_awaited_once()


async def test_bad_signature_rejected(hass, handler):
    """A bad signature returns 403 and is not processed."""
    fn, coordinator = handler
    body = json.dumps({"push_type": "therm-mode"}).encode()
    request = FakeRequest(body, {"X-Netatmo-Secret": "deadbeef"})
    response = await fn(hass, WEBHOOK_ID, request)
    assert response.status == 403
    coordinator.async_handle_webhook.assert_not_awaited()


async def test_oversized_payload_rejected(hass, handler):
    """An oversized payload returns 413."""
    fn, coordinator = handler
    body = b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)
    request = FakeRequest(body, {"X-Netatmo-Secret": _sign(body)})
    response = await fn(hass, WEBHOOK_ID, request)
    assert response.status == 413
    coordinator.async_handle_webhook.assert_not_awaited()


async def test_malformed_json_still_returns_200(hass, handler):
    """Malformed JSON is handled gracefully (200, empty data)."""
    fn, coordinator = handler
    body = b"<<<not json>>>"
    request = FakeRequest(body, {"X-Netatmo-Secret": _sign(body)})
    response = await fn(hass, WEBHOOK_ID, request)
    assert response.status == 200
    coordinator.async_handle_webhook.assert_awaited_once()


async def test_unsigned_accepted_when_no_secret(hass):
    """With no client secret, unsigned requests are accepted (lenient mode)."""
    coordinator = MagicMock()
    coordinator.async_handle_webhook = AsyncMock()
    await async_setup_webhook(hass, "no-secret-id", coordinator, client_secret=None)
    fn = hass.data["webhook"]["no-secret-id"]["handler"]
    body = json.dumps({"push_type": "x"}).encode()
    response = await fn(hass, "no-secret-id", FakeRequest(body))
    assert response.status == 200
    coordinator.async_handle_webhook.assert_awaited_once()
