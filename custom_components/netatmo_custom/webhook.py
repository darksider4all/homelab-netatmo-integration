"""Webhook handler for Netatmo Custom integration."""
import logging

from aiohttp import web
from homeassistant.components.webhook import async_register, async_unregister
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import get_url, NoURLAvailableError

from .const import DOMAIN
from .coordinator import NetatmoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_webhook(
    hass: HomeAssistant, webhook_id: str, coordinator: NetatmoDataUpdateCoordinator
) -> str:
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
            # Get webhook signature header (Netatmo sends X-Netatmo-Secret)
            signature = request.headers.get("X-Netatmo-Secret")

            # Get request body
            body = await request.text()

            # TODO: Verify signature using HMAC SHA256 with client secret
            # For now, just log the signature
            if signature:
                _LOGGER.debug(f"Webhook signature: {signature}")

            # Parse webhook data
            try:
                data = await request.json()
            except Exception:
                # If JSON parsing fails, log raw body
                _LOGGER.warning(f"Failed to parse webhook JSON. Body: {body}")
                data = {"raw_body": body}

            _LOGGER.info(f"Webhook received: {data.get('event_type', 'unknown')}")

            # Update coordinator immediately
            await coordinator.async_handle_webhook(data)

            # Respond with 200 OK (Netatmo requires response within 14 seconds)
            return web.Response(status=200, text="OK")

        except Exception as err:
            _LOGGER.error(f"Webhook error: {err}", exc_info=True)
            # Still return 200 to avoid being banned by Netatmo
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
