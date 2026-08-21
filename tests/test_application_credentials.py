"""Tests for the application credentials platform."""

from custom_components.netatmo_custom.application_credentials import (
    async_get_authorization_server,
)
from custom_components.netatmo_custom.const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN


async def test_authorization_server_urls(hass):
    """The authorization server exposes the Netatmo OAuth2 endpoints."""
    server = await async_get_authorization_server(hass)
    assert server.authorize_url == OAUTH2_AUTHORIZE
    assert server.token_url == OAUTH2_TOKEN
