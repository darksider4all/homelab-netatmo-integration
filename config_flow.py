"""Config flow for Netatmo Custom integration."""
import logging
import secrets

from homeassistant.helpers import config_entry_oauth2_flow, aiohttp_client

from .const import API_BASE_URL, CONF_WEBHOOK_ID, DOMAIN, OAUTH2_SCOPES

_LOGGER = logging.getLogger(__name__)


class SimpleTokenAPI:
    """Simple API client for initial token validation during config flow."""

    def __init__(self, hass, token: dict):
        """Initialize with a token dict."""
        self._token = token
        self._session = aiohttp_client.async_get_clientsession(hass)

    async def async_get_homes_data(self) -> dict:
        """Fetch homes data to validate the token."""
        import json

        headers = {"Authorization": f"Bearer {self._token['access_token']}"}
        url = f"{API_BASE_URL}homesdata"

        async with self._session.post(url, headers=headers) as resp:
            resp.raise_for_status()
            return json.loads(await resp.text())


class NetatmoOAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow to handle Netatmo OAuth2 authentication."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict:
        """Extra data to append to the authorization URL."""
        return {"scope": " ".join(OAUTH2_SCOPES)}

    async def async_oauth_create_entry(self, data: dict) -> dict:
        """Create an entry for the flow after OAuth completion."""
        _LOGGER.debug(f"OAuth data received, token keys: {data.get('token', {}).keys()}")

        # For initial validation, use a simple API client with the fresh token
        # (OAuth2Session requires a config entry which doesn't exist yet)
        api = SimpleTokenAPI(self.hass, data["token"])

        try:
            # Validate token by fetching homes data
            _LOGGER.debug("Fetching homes data to validate token...")
            homes_data = await api.async_get_homes_data()
            _LOGGER.debug(f"Homes data response: {homes_data}")

            homes = homes_data.get("body", {}).get("homes", [])

            if not homes:
                _LOGGER.error("No homes found in Netatmo account")
                return self.async_abort(reason="no_thermostats_found")

            # Homes found - proceed to selection
            _LOGGER.info(f"Found {len(homes)} homes in Netatmo account")

        except Exception as err:
            _LOGGER.error(f"Authentication failed: {err}", exc_info=True)
            return self.async_abort(reason="auth_failed")

        except Exception as err:
            _LOGGER.error(f"Authentication failed: {err}", exc_info=True)
            return self.async_abort(reason="auth_failed")

        # Store data for next step
        self.homes_data = homes
        self.auth_data = data
        
        # If only one home, proceed immediately
        if len(homes) == 1:
            return await self.async_create_entry_for_home(homes[0])
            
        # Multiple homes found, show selection step
        return await self.async_step_home_select()

    async def async_step_home_select(self, user_input: dict | None = None) -> dict:
        """Handle home selection step."""
        if user_input:
            home_id = user_input["home"]
            # Find selected home object
            selected_home = next((h for h in self.homes_data if h["id"] == home_id), None)
            if selected_home:
                return await self.async_create_entry_for_home(selected_home)
        
        # Prepare options
        options = {
            home["id"]: f"{home.get('name', 'Unknown')} ({home['id']})" 
            for home in self.homes_data
        }
        
        import voluptuous as vol
        
        return self.async_show_form(
            step_id="home_select",
            data_schema=vol.Schema({
                vol.Required("home"): vol.In(options)
            }),
            description_placeholders={
                "count": str(len(self.homes_data))
            }
        )

    async def async_create_entry_for_home(self, home: dict) -> dict:
        """Create the config entry for a specific home."""
        home_id = home["id"]
        home_name = home.get("name", "Netatmo Home")
        
        # Generate webhook ID for this config entry
        webhook_id = secrets.token_hex(32)
        
        # Create final data dict
        data = {
            **self.auth_data,
            CONF_WEBHOOK_ID: webhook_id
        }
        
        # Set unique ID based on home ID
        await self.async_set_unique_id(f"{DOMAIN}_{home_id}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Homelab Climate - {home_name}",
            data=data,
        )
