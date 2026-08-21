"""Tests for the Netatmo API client (retry, rate-limit, error handling)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.netatmo_custom import api as api_module
from custom_components.netatmo_custom.api import (
    NetatmoAPI,
    NetatmoAPIError,
    NetatmoAuthError,
    NetatmoRateLimitError,
)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make asyncio.sleep instant so retry/backoff tests are fast."""
    monkeypatch.setattr(api_module.asyncio, "sleep", AsyncMock())


@pytest.fixture
def api(mock_oauth_session, monkeypatch) -> NetatmoAPI:
    """Return a NetatmoAPI with a stubbed aiohttp session."""
    monkeypatch.setattr(
        api_module.aiohttp_client, "async_get_clientsession", lambda hass: MagicMock()
    )
    return NetatmoAPI(MagicMock(), mock_oauth_session)


def _ok_body(body: dict | None = None) -> str:
    return json.dumps({"status": "ok", "body": body or {}})


async def test_successful_request(api, monkeypatch):
    """A 200/ok response is returned as a dict."""
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(200, _ok_body({"x": 1}), {})))
    result = await api.async_request("POST", "homesdata")
    assert result["status"] == "ok"
    assert result["body"] == {"x": 1}
    assert api.consecutive_failures == 0


async def test_401_raises_auth_error(api, monkeypatch):
    """A 401 raises NetatmoAuthError and is not retried."""
    do_request = AsyncMock(return_value=(401, "unauthorized", {}))
    monkeypatch.setattr(api, "_do_request", do_request)
    with pytest.raises(NetatmoAuthError):
        await api.async_request("POST", "homesdata")
    assert do_request.call_count == 1
    assert api.consecutive_failures == 1


async def test_403_non_transient_raises_auth_error(api, monkeypatch):
    """A non-transient 403 raises NetatmoAuthError."""
    monkeypatch.setattr(
        api,
        "_do_request",
        AsyncMock(return_value=(403, json.dumps({"error": {"code": 2}}), {})),
    )
    with pytest.raises(NetatmoAuthError):
        await api.async_request("POST", "homesdata")


async def test_403_transient_code_retries_then_succeeds(api, monkeypatch):
    """A transient 403 error code is retried and can then succeed."""
    responses = [
        (403, json.dumps({"error": {"code": 10}}), {}),
        (200, _ok_body(), {}),
    ]
    monkeypatch.setattr(api, "_do_request", AsyncMock(side_effect=responses))
    result = await api.async_request("POST", "homesdata")
    assert result["status"] == "ok"


async def test_429_retries_then_succeeds(api, monkeypatch):
    """A 429 honours Retry-After then succeeds on retry."""
    responses = [
        (429, "", {"Retry-After": "1"}),
        (200, _ok_body(), {}),
    ]
    monkeypatch.setattr(api, "_do_request", AsyncMock(side_effect=responses))
    result = await api.async_request("POST", "homesdata")
    assert result["status"] == "ok"


async def test_429_exhausts_retries(api, monkeypatch):
    """A persistent 429 raises NetatmoRateLimitError after retries."""
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(429, "", {"Retry-After": "1"})))
    with pytest.raises(NetatmoRateLimitError):
        await api.async_request("POST", "homesdata")


async def test_500_retries_then_succeeds(api, monkeypatch):
    """A 5xx error is retried and can then succeed."""
    responses = [(500, "boom", {}), (200, _ok_body(), {})]
    monkeypatch.setattr(api, "_do_request", AsyncMock(side_effect=responses))
    result = await api.async_request("POST", "homesdata")
    assert result["status"] == "ok"


async def test_500_exhausts_retries(api, monkeypatch):
    """A persistent 5xx raises NetatmoAPIError after MAX_RETRIES."""
    do_request = AsyncMock(return_value=(500, "boom", {}))
    monkeypatch.setattr(api, "_do_request", do_request)
    with pytest.raises(NetatmoAPIError):
        await api.async_request("POST", "homesdata")
    assert do_request.call_count == api_module.MAX_RETRIES + 1


async def test_status_not_ok_non_transient(api, monkeypatch):
    """A 200 with status!=ok and a non-transient code raises."""
    body = json.dumps({"status": "error", "error": {"code": 99, "message": "nope"}})
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(200, body, {})))
    with pytest.raises(NetatmoAPIError):
        await api.async_request("POST", "homesdata")


async def test_invalid_json_raises(api, monkeypatch):
    """An unparseable 200 body raises NetatmoAPIError."""
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(200, "<html>", {})))
    with pytest.raises(NetatmoAPIError):
        await api.async_request("POST", "homesdata")


async def test_token_failure_raises_auth_error(api, monkeypatch):
    """A token refresh failure surfaces as NetatmoAuthError."""
    api._oauth_session.async_ensure_token_valid = AsyncMock(side_effect=RuntimeError("no net"))
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(200, _ok_body(), {})))
    with pytest.raises(NetatmoAuthError):
        await api.async_request("POST", "homesdata")


async def test_set_therm_mode_builds_schedule_payload(api, monkeypatch):
    """async_set_therm_mode forwards mode and schedule_id to the request."""
    do_request = AsyncMock(return_value=(200, _ok_body(), {}))
    monkeypatch.setattr(api, "_do_request", do_request)
    await api.async_set_therm_mode("home-1", mode="schedule", schedule_id="sched-9")
    # data kwarg is passed through to _do_request
    _, kwargs = do_request.call_args
    assert kwargs["data"]["home_id"] == "home-1"
    assert kwargs["data"]["mode"] == "schedule"
    assert kwargs["data"]["schedule_id"] == "sched-9"


async def test_get_schedules_filters_by_home(api, monkeypatch):
    """async_get_schedules returns the schedules of the matching home."""
    body = {
        "homes": [
            {"id": "home-1", "schedules": [{"id": "s1", "name": "Default"}]},
            {"id": "home-2", "schedules": [{"id": "s2", "name": "Other"}]},
        ]
    }
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(200, _ok_body(body), {})))
    schedules = await api.async_get_schedules("home-1")
    assert schedules == [{"id": "s1", "name": "Default"}]


async def test_rate_limit_waits_when_window_full(api, monkeypatch):
    """_check_rate_limit sleeps once the request window is saturated."""
    sleep = AsyncMock()
    monkeypatch.setattr(api_module.asyncio, "sleep", sleep)
    now = api_module.time.time()
    api._request_timestamps = [now] * api_module.RATE_LIMIT_MAX_REQUESTS
    await api._check_rate_limit()
    assert sleep.await_count == 1


# --- Raw HTTP layer ---


async def test_do_request_executes_http(api, monkeypatch):
    """_do_request performs the raw HTTP call and returns status/text/headers."""
    response = MagicMock()
    response.status = 200
    response.text = AsyncMock(return_value=_ok_body({"x": 1}))
    response.headers = {"Content-Type": "application/json"}
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.request = MagicMock(return_value=response)
    monkeypatch.setattr(api, "_session", session)

    status, text, headers = await api._do_request(
        "POST",
        "homesdata",
        {"Authorization": "Bearer t"},
        api_module.aiohttp.ClientTimeout(total=5),
    )

    assert status == 200
    assert '"status": "ok"' in text
    assert headers["Content-Type"] == "application/json"
    call_kwargs = session.request.call_args.kwargs
    assert call_kwargs["headers"] == {"Authorization": "Bearer t"}


# --- Remaining error branches ---


async def test_403_unparseable_body_raises_auth_error(api, monkeypatch):
    """A 403 with a non-JSON body is treated as non-transient."""
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(403, "<html>", {})))
    with pytest.raises(NetatmoAuthError):
        await api.async_request("POST", "homesdata")


async def test_400_client_error_raises(api, monkeypatch):
    """A generic 4xx raises NetatmoAPIError."""
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(400, "bad", {})))
    with pytest.raises(NetatmoAPIError, match="Client error 400"):
        await api.async_request("POST", "homesdata")


async def test_transient_body_code_retries(api, monkeypatch):
    """A transient error code in the response body is retried then succeeds."""
    responses = [
        (200, json.dumps({"status": "error", "error": {"code": 13, "message": "setpoint"}}), {}),
        (200, _ok_body(), {}),
    ]
    monkeypatch.setattr(api, "_do_request", AsyncMock(side_effect=responses))
    result = await api.async_request("POST", "homesdata")
    assert result["status"] == "ok"


async def test_timeout_retries_then_succeeds(api, monkeypatch):
    """A TimeoutError is retried and can then succeed."""
    responses = [TimeoutError(), (200, _ok_body(), {})]
    monkeypatch.setattr(api, "_do_request", AsyncMock(side_effect=responses))
    result = await api.async_request("POST", "homesdata")
    assert result["status"] == "ok"


async def test_timeout_exhausts_retries(api, monkeypatch):
    """A persistent timeout raises NetatmoTimeoutError."""
    monkeypatch.setattr(api, "_do_request", AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(api_module.NetatmoTimeoutError):
        await api.async_request("POST", "homesdata")


async def test_client_error_exhausts_retries(api, monkeypatch):
    """A persistent connection error raises NetatmoAPIError after retries."""
    monkeypatch.setattr(
        api, "_do_request", AsyncMock(side_effect=api_module.aiohttp.ClientError("conn"))
    )
    with pytest.raises(NetatmoAPIError, match="API request failed"):
        await api.async_request("POST", "homesdata")


async def test_reset_failure_count(api):
    """reset_failure_count clears the consecutive failure counter."""
    api._consecutive_failures = 3
    api.reset_failure_count()
    assert api.consecutive_failures == 0


# --- Endpoint payload builders ---


async def test_get_home_status_passes_home_id(api, monkeypatch):
    """async_get_home_status forwards the home id in the request body."""
    do_request = AsyncMock(return_value=(200, _ok_body(), {}))
    monkeypatch.setattr(api, "_do_request", do_request)
    await api.async_get_home_status("home-1")
    _, kwargs = do_request.call_args
    assert kwargs["data"] == {"home_id": "home-1"}


async def test_set_room_thermpoint_payload(api, monkeypatch):
    """async_set_room_thermpoint builds the full payload with temp/endtime."""
    do_request = AsyncMock(return_value=(200, _ok_body(), {}))
    monkeypatch.setattr(api, "_do_request", do_request)
    await api.async_set_room_thermpoint("home-1", "room-1", mode="manual", temp=21.0, endtime=12345)
    _, kwargs = do_request.call_args
    assert kwargs["data"] == {
        "home_id": "home-1",
        "room_id": "room-1",
        "mode": "manual",
        "temp": 21.0,
        "endtime": 12345,
    }


async def test_set_room_thermpoint_omits_optionals(api, monkeypatch):
    """async_set_room_thermpoint omits temp/endtime when not provided."""
    do_request = AsyncMock(return_value=(200, _ok_body(), {}))
    monkeypatch.setattr(api, "_do_request", do_request)
    await api.async_set_room_thermpoint("home-1", "room-1", mode="off")
    _, kwargs = do_request.call_args
    assert kwargs["data"] == {"home_id": "home-1", "room_id": "room-1", "mode": "off"}


async def test_set_therm_mode_endtime_payload(api, monkeypatch):
    """async_set_therm_mode forwards endtime when provided."""
    do_request = AsyncMock(return_value=(200, _ok_body(), {}))
    monkeypatch.setattr(api, "_do_request", do_request)
    await api.async_set_therm_mode("home-1", mode="away", endtime=999)
    _, kwargs = do_request.call_args
    assert kwargs["data"] == {"home_id": "home-1", "mode": "away", "endtime": 999}


async def test_get_schedules_unknown_home_returns_empty(api, monkeypatch):
    """async_get_schedules returns [] when the home is not in homesdata."""
    body = {"homes": [{"id": "home-2", "schedules": [{"id": "s2"}]}]}
    monkeypatch.setattr(api, "_do_request", AsyncMock(return_value=(200, _ok_body(body), {})))
    assert await api.async_get_schedules("home-1") == []
