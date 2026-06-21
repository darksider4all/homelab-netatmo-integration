"""Webhook handler for Netatmo Custom integration."""

import hashlib
import hmac
import json
import logging

from aiohttp import web
from homeassistant.components.webhook import async_register, async_unregister
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN, MAX_WEBHOOK_BODY_BYTES
from .coordinator import NetatmoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    coordinator: NetatmoDataUpdateCoordinator,
    client_secret: str | None = None,
) -> str | None:
    """Register webhook handler.

    Args:
        hass: Home Assistant instance
        webhook_id: Unique webhook ID
        coordinator: Data update coordinator

    Returns:
        Full webhook URL for registration with Netatmo
    """

    async def webhook_handler(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        """Handle incoming webhook from Netatmo.

        Args:
            hass: Home Assistant instance
            webhook_id: Webhook ID
            request: HTTP request

        Returns:
            HTTP response
        """
        try:
            # Read the body and reject oversized payloads early (DoS guard).
            body_bytes = await request.read()
            if len(body_bytes) > MAX_WEBHOOK_BODY_BYTES:
                _LOGGER.warning("Rejecting oversized webhook payload (%d bytes)", len(body_bytes))
                return web.Response(status=413, text="Payload too large")

            # Verify signature using HMAC SHA256 over the raw body, when both the
            # X-Netatmo-Secret header and a client secret are available. We do NOT
            # reject unsigned requests (they only trigger an authenticated API
            # refresh, never state injection) but we do reject bad signatures.
            signature = request.headers.get("X-Netatmo-Secret")
            if signature and client_secret:
                expected_signature = hmac.new(
                    client_secret.encode("utf-8"),
                    body_bytes,
                    hashlib.sha256,
                ).hexdigest()
                if not hmac.compare_digest(expected_signature, signature):
                    _LOGGER.warning("Invalid webhook signature received")
                    return web.Response(status=403, text="Invalid signature")
            elif not client_secret:
                _LOGGER.debug("No client secret available; skipping signature check")
            else:
                _LOGGER.debug("Webhook request missing signature header")

            # Parse the body without ever logging its contents.
            try:
                data = json.loads(body_bytes.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                _LOGGER.warning("Failed to parse webhook JSON (%d bytes)", len(body_bytes))
                data = {}

            _LOGGER.debug("Webhook received: %s", data.get("push_type", "unknown"))

            # Trigger an authoritative refresh from the API.
            await coordinator.async_handle_webhook(data)

            # Respond 200 OK (Netatmo requires a response within 14 seconds).
            return web.Response(status=200, text="OK")

        except Exception:
            # Still return 200 to avoid being throttled/banned by Netatmo.
            _LOGGER.exception("Unexpected error handling Netatmo webhook")
            return web.Response(status=200, text="Error processed")

    # Register webhook with Home Assistant
    async_register(
        hass,
        DOMAIN,
        "Netatmo Webhook",
        webhook_id,
        webhook_handler,
    )

    # Return webhook URL for registration with Netatmo
    try:
        external_url = get_url(hass, allow_internal=False, prefer_external=True)
    except NoURLAvailableError:
        _LOGGER.warning(
            "No external URL available in Home Assistant. "
            "Configure an external URL in Settings > System > Network "
            "for webhooks to work."
        )
        return None

    webhook_url = f"{external_url}/api/webhook/{webhook_id}"
    return webhook_url


def async_unregister_webhook(hass: HomeAssistant, webhook_id: str) -> None:
    """Unregister webhook handler.

    Args:
        hass: Home Assistant instance
        webhook_id: Webhook ID to unregister
    """
    async_unregister(hass, webhook_id)
    _LOGGER.info(f"Unregistered webhook: {webhook_id}")
