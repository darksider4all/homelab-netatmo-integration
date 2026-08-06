"""Tests for the Netatmo config flow entry-creation logic."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
from homeassistant.config_entries import SOURCE_REAUTH
import pytest

from custom_components.netatmo_custom import config_flow as cf


def _make_flow(hass):
    """Build a flow handler with HA flow primitives stubbed out."""
    flow = cf.NetatmoOAuth2FlowHandler()
    flow.hass = hass
    flow.context = {}
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    return flow


@pytest.fixture
def patch_api(monkeypatch):
    """Patch SimpleTokenAPI; return a setter for the homes payload / error."""

    def _configure(homes=None, error=None):
        api = MagicMock()
        if error is not None:
            api.async_get_homes_data = AsyncMock(side_effect=error)
        else:
            api.async_get_homes_data = AsyncMock(return_value={"body": {"homes": homes or []}})
        monkeypatch.setattr(cf, "SimpleTokenAPI", lambda hass, token: api)
        return api

    return _configure


async def test_no_homes_aborts(hass, patch_api):
    """An account with no homes aborts with no_thermostats_found."""
    patch_api(homes=[])
    flow = _make_flow(hass)
    result = await flow.async_oauth_create_entry({"token": {"access_token": "t"}})
    assert result["type"] == "abort"
    assert result["reason"] == "no_thermostats_found"


async def test_client_error_aborts_auth_failed(hass, patch_api):
    """A network error during validation aborts with auth_failed."""
    patch_api(error=aiohttp.ClientError("network"))
    flow = _make_flow(hass)
    result = await flow.async_oauth_create_entry({"token": {"access_token": "t"}})
    assert result["type"] == "abort"
    assert result["reason"] == "auth_failed"


async def test_single_home_creates_entry(hass, patch_api):
    """A single home creates the entry directly with a stable unique_id."""
    patch_api(homes=[{"id": "home-1", "name": "Test Home"}])
    flow = _make_flow(hass)
    created = {}
    flow.async_create_entry = MagicMock(
        side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
    )
    result = await flow.async_oauth_create_entry({"token": {"access_token": "t"}})
    assert result["type"] == "create_entry"
    assert "Test Home" in result["title"]
    assert result["data"]["home_id"] == "home-1"
    assert "webhook_id" in result["data"]
    flow.async_set_unique_id.assert_awaited_once_with("netatmo_custom_home-1")
    created.clear()


async def test_multiple_homes_shows_selection(hass, patch_api):
    """Multiple homes route to the home-selection form."""
    patch_api(homes=[{"id": "home-1", "name": "A"}, {"id": "home-2", "name": "B"}])
    flow = _make_flow(hass)
    result = await flow.async_oauth_create_entry({"token": {"access_token": "t"}})
    assert result["type"] == "form"
    assert result["step_id"] == "home_select"


async def test_reauth_confirm_shows_form(hass):
    """The reauth confirm step shows a form before re-running OAuth."""
    flow = _make_flow(hass)
    result = await flow.async_step_reauth_confirm()
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_updates_existing_entry(hass, patch_api):
    """On reauth, the existing entry's token is updated and reloaded."""
    patch_api(homes=[{"id": "home-1", "name": "Test Home"}])
    flow = _make_flow(hass)
    flow.context = {"source": SOURCE_REAUTH, "entry_id": "entry-1"}

    existing = MagicMock()
    existing.data = {"home_id": "home-1", "webhook_id": "wh", "token": {"access_token": "old"}}
    flow.hass.config_entries.async_get_entry = MagicMock(return_value=existing)
    flow.async_update_reload_and_abort = MagicMock(
        side_effect=lambda entry, **kwargs: {"type": "abort", **kwargs}
    )

    result = await flow.async_oauth_create_entry({"token": {"access_token": "new"}})
    assert result["type"] == "abort"
    # Existing home_id/webhook_id are preserved; token is refreshed.
    assert result["data"]["home_id"] == "home-1"
    assert result["data"]["webhook_id"] == "wh"
    assert result["data"]["token"]["access_token"] == "new"
