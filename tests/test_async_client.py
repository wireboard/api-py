"""Tests for AsyncWireBoardClient. Same coverage as test_client.py but async.

Only the paths that differ in interesting ways from the sync client are
re-tested in full; pure data-flow tests are minimal smoke checks since the
underlying transport / serialize / errors code is shared.
"""

from __future__ import annotations

from typing import Any

import pytest

from wireboard_api import AsyncWireBoardClient, WireBoardApiError, WireBoardAuthError


def _envelope(data: Any) -> dict[str, Any]:
    return {"status": True, "data": data}


@pytest.mark.asyncio
async def test_async_account_returns_data(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope({"email": "sam@example.com", "name": "Sam", "abilities": []})
    )
    async with AsyncWireBoardClient(token="t") as wb:
        a = await wb.account()
    assert a["email"] == "sam@example.com"


@pytest.mark.asyncio
async def test_async_raises_auth_error_on_401(httpx_mock: Any) -> None:
    httpx_mock.add_response(status_code=401, json={"message": "Unauthenticated."})
    async with AsyncWireBoardClient(token="t") as wb:
        with pytest.raises(WireBoardAuthError) as ei:
            await wb.account()
    assert ei.value.http_status == 401


@pytest.mark.asyncio
async def test_async_raises_api_error_with_code(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        status_code=404,
        json={
            "status": False,
            "errors": [{"text": "site not found"}],
            "fieldErrors": {"error_code": ["site_not_found"]},
        },
    )
    async with AsyncWireBoardClient(token="t") as wb:
        with pytest.raises(WireBoardApiError) as ei:
            await wb.aggregate(site_id="x", from_="2026-05-01", to="2026-05-22")
    assert ei.value.code == "site_not_found"


@pytest.mark.asyncio
async def test_async_retries_once_on_429(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        status_code=429, json={"message": "too many"}, headers={"Retry-After": "0"}
    )
    httpx_mock.add_response(
        json=_envelope({"email": "s", "name": "S", "abilities": []})
    )
    async with AsyncWireBoardClient(token="t") as wb:
        a = await wb.account()
    assert a["email"] == "s"
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_async_live_state_normalises_array_shape(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope(
            {
                "site_id": "x",
                "ts": "t",
                "live": [
                    {
                        "category": "visitors",
                        "ts": "t",
                        "data": {"live": 1, "returning": 0},
                    }
                ],
                "max_30d": None,
                "max_30d_at": None,
            }
        )
    )
    async with AsyncWireBoardClient(token="t") as wb:
        snap = await wb.live_state(site_id="x")
    assert snap["live"] == {"visitors": {"live": 1, "returning": 0}}


@pytest.mark.asyncio
async def test_async_with_meta_returns_data_and_rate_limit(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope({"email": "s", "name": "S", "abilities": []}),
        headers={"X-RateLimit-Limit": "120", "X-RateLimit-Remaining": "117"},
    )
    async with AsyncWireBoardClient(token="t") as wb:
        data, rate_limit = await wb.with_meta(lambda c: c.account())
    assert data["email"] == "s"
    assert rate_limit is not None
    assert rate_limit["limit"] == 120
    assert rate_limit["remaining"] == 117


def test_async_missing_token_raises() -> None:
    with pytest.raises(TypeError):
        AsyncWireBoardClient(token="")
