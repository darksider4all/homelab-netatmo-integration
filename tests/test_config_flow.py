"""Tests for the Netatmo config flow entry-creation logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.config_entries import SOURCE_REAUTH
import pytest

from custom_components.netatmo_custom import config_flow as cf
from custom_components.netatmo_custom.const import OAUTH2_SCOPES


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


# --- SimpleTokenAPI (the raw token-validation client) ---


def _mock_session(response):
    """Return a mock aiohttp session whose post returns the given response.

    The production code does ``async with session.post(...) as resp``, so the
    post return value must be an async context manager, not a coroutine.
    """
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=response)
    return session


def _patch_clientsession(session):
    return patch(
        "custom_components.netatmo_custom.config_flow.aiohttp_client.async_get_clientsession",
        return_value=session,
    )


async def test_simple_token_api_fetches_homes(hass):
    """SimpleTokenAPI posts to homesdata and returns the parsed JSON body."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = AsyncMock(return_value={"status": "ok", "body": {"homes": []}})
    session = _mock_session(response)

    with _patch_clientsession(session):
        api = cf.SimpleTokenAPI(hass, {"access_token": "tok"})
        result = await api.async_get_homes_data()

    assert result == {"status": "ok", "body": {"homes": []}}
    # The bearer token is sent in the Authorization header; url is positional.
    post_kwargs = session.post.call_args.kwargs
    assert post_kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert session.post.call_args.args[0] == f"{cf.API_BASE_URL}homesdata"


async def test_simple_token_api_raises_on_http_error(hass):
    """An HTTP error from homesdata propagates as aiohttp.ClientError."""
    response = MagicMock()
    response.raise_for_status = MagicMock(side_effect=aiohttp.ClientError("boom"))
    session = _mock_session(response)

    with _patch_clientsession(session):
        api = cf.SimpleTokenAPI(hass, {"access_token": "tok"})
        with pytest.raises(aiohttp.ClientError):
            await api.async_get_homes_data()


# --- Flow metadata and reauth entry points ---


async def test_flow_domain_and_version(hass):
    """The flow advertises the domain and schema version."""
    flow = _make_flow(hass)
    assert flow.DOMAIN == "netatmo_custom"
    assert flow.VERSION == 1


async def test_logger_property(hass):
    """The flow exposes the module logger."""
    flow = _make_flow(hass)
    assert flow.logger.name == "custom_components.netatmo_custom.config_flow"


async def test_extra_authorize_data(hass):
    """The OAuth authorize URL carries the thermostat scopes."""
    flow = _make_flow(hass)
    assert flow.extra_authorize_data == {"scope": " ".join(OAUTH2_SCOPES)}


async def test_reauth_delegates_to_reauth_confirm(hass):
    """async_step_reauth shows the reauth confirm form."""
    flow = _make_flow(hass)
    result = await flow.async_step_reauth({})
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_confirm_with_input_restarts_oauth(hass):
    """Confirming reauth restarts the OAuth user step."""
    flow = _make_flow(hass)
    flow.async_step_user = AsyncMock(return_value={"type": "form", "step_id": "user"})
    result = await flow.async_step_reauth_confirm({"confirm": True})
    assert result["step_id"] == "user"
    flow.async_step_user.assert_awaited_once()


# --- Home selection step ---


def _flow_with_homes(hass):
    flow = _make_flow(hass)
    flow.homes_data = [
        {"id": "home-1", "name": "A"},
        {"id": "home-2", "name": "B"},
    ]
    flow.auth_data = {"token": {"access_token": "t"}}
    return flow


async def test_home_select_creates_entry_for_selected_home(hass):
    """Selecting a home from the list creates the entry for that home."""
    flow = _flow_with_homes(hass)
    flow.async_create_entry_for_home = AsyncMock(return_value={"type": "create_entry"})
    result = await flow.async_step_home_select({"home": "home-2"})
    assert result["type"] == "create_entry"
    flow.async_create_entry_for_home.assert_awaited_once_with({"id": "home-2", "name": "B"})


async def test_home_select_unknown_home_shows_form_again(hass):
    """An unknown selection re-renders the selection form."""
    flow = _flow_with_homes(hass)
    result = await flow.async_step_home_select({"home": "nope"})
    assert result["type"] == "form"
    assert result["step_id"] == "home_select"


async def test_home_select_no_input_shows_form(hass):
    """Calling the step without input renders the form with the home choices."""
    flow = _flow_with_homes(hass)
    result = await flow.async_step_home_select()
    assert result["type"] == "form"
    assert result["step_id"] == "home_select"
    assert "home-1" in result["data_schema"].schema["home"].container
    assert result["description_placeholders"]["count"] == "2"
