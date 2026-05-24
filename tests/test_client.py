"""Tests for the sync WireBoardClient using pytest-httpx.

Each test reuses the ``httpx_mock`` fixture from ``pytest-httpx`` to stub
upstream responses, then asserts on either the result or the recorded
requests.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wireboard_api import (
    PaidPlanRequiredError,
    PlanHistoryLimitExceededError,
    WireBoardApiError,
    WireBoardAuthError,
    WireBoardClient,
)


def _envelope(data: Any) -> dict[str, Any]:
    return {"status": True, "data": data}


# ─── Envelope unwrap ────────────────────────────────────────────────────────


def test_returns_data_on_success(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope(
            {"email": "sam@example.com", "name": "Sam", "abilities": ["analytics:read"]}
        )
    )
    with WireBoardClient(token="t") as wb:
        a = wb.account()
    assert a["email"] == "sam@example.com"
    assert a["abilities"] == ["analytics:read"]


def test_raises_api_error_on_error_envelope(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        status_code=404,
        json={
            "status": False,
            "errors": [{"text": "site not found"}],
            "fieldErrors": {"error_code": ["site_not_found"]},
        },
    )
    with WireBoardClient(token="t") as wb, pytest.raises(WireBoardApiError) as ei:
        wb.aggregate(site_id="xK4mP2nT", from_="2026-05-01", to="2026-05-22")
    err = ei.value
    assert err.code == "site_not_found"
    assert err.http_status == 404
    assert str(err) == "site not found"


def test_raises_auth_error_on_401(httpx_mock: Any) -> None:
    httpx_mock.add_response(status_code=401, json={"message": "Unauthenticated."})
    with WireBoardClient(token="t") as wb, pytest.raises(WireBoardAuthError) as ei:
        wb.account()
    assert ei.value.http_status == 401
    assert str(ei.value) == "Unauthenticated."


def test_raises_auth_error_on_403(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        status_code=403, json={"message": "Invalid ability provided."}
    )
    with WireBoardClient(token="t") as wb, pytest.raises(WireBoardAuthError) as ei:
        wb.account()
    assert ei.value.http_status == 403


def test_raises_plan_history_limit_exceeded_on_422_with_that_code(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        status_code=422,
        json={
            "status": False,
            "errors": [
                {
                    "text": (
                        "Your plan limits historical queries to the last 30 days. "
                        "Upgrade for full history."
                    )
                }
            ],
            "fieldErrors": {
                "error_code": ["plan_history_limit_exceeded"],
                "earliest_allowed": ["2026-04-24"],
            },
        },
    )
    with WireBoardClient(token="t") as wb, pytest.raises(PlanHistoryLimitExceededError) as ei:
        wb.aggregate(site_id="xK4mP2nT", from_="2020-01-01", to="2026-05-23")
    err = ei.value
    # Subclass still matches the parent — existing handlers keep working.
    assert isinstance(err, WireBoardApiError)
    assert err.code == "plan_history_limit_exceeded"
    assert err.http_status == 422
    assert err.earliest_allowed == "2026-04-24"


def test_raises_paid_plan_required_on_403_with_that_code_not_auth_error(
    httpx_mock: Any,
) -> None:
    """A 403 carrying ``error_code: paid_plan_required`` must NOT be classified
    as :class:`WireBoardAuthError` — the token is valid; the user needs an
    upgrade prompt, not a re-login flow.
    """
    httpx_mock.add_response(
        status_code=403,
        json={
            "status": False,
            "errors": [
                {"text": "This endpoint requires a paid plan. Upgrade to access the Live API."}
            ],
            "fieldErrors": {"error_code": ["paid_plan_required"]},
        },
    )
    with WireBoardClient(token="t") as wb, pytest.raises(PaidPlanRequiredError) as ei:
        wb.live_token(sites=["xK4mP2nT"])
    err = ei.value
    assert isinstance(err, WireBoardApiError)
    # The key invariant.
    assert not isinstance(err, WireBoardAuthError)
    assert err.code == "paid_plan_required"
    assert err.http_status == 403


# ─── Headers ────────────────────────────────────────────────────────────────


def test_sends_auth_and_client_headers(httpx_mock: Any) -> None:
    httpx_mock.add_response(json=_envelope({}))
    with WireBoardClient(token="abc-xyz") as wb:
        wb.account()
    req = httpx_mock.get_requests()[0]
    assert req.headers["authorization"] == "Bearer abc-xyz"
    assert req.headers["accept"] == "application/json"
    assert req.headers["x-wireboard-client"].startswith("wireboard-api-python/")


# ─── 429 retry / rate-limit ────────────────────────────────────────────────


def test_retries_once_on_429_honoring_retry_after(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        status_code=429, json={"message": "too many"}, headers={"Retry-After": "0"}
    )
    httpx_mock.add_response(
        json=_envelope({"email": "s", "name": "S", "abilities": []})
    )
    with WireBoardClient(token="t") as wb:
        a = wb.account()
    assert a["email"] == "s"
    assert len(httpx_mock.get_requests()) == 2


def test_does_not_retry_when_disabled(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        status_code=429, json={"message": "too many"}, headers={"Retry-After": "0"}
    )
    with WireBoardClient(token="t", retry_on_429=False) as wb, pytest.raises(WireBoardApiError) as ei:
        wb.account()
    assert ei.value.http_status == 429
    assert len(httpx_mock.get_requests()) == 1


def test_rate_limit_attached_to_429_error(httpx_mock: Any) -> None:
    # Both attempts return 429 — exhaust the single retry, then raise.
    headers = {
        "Retry-After": "0",
        "X-RateLimit-Limit": "120",
        "X-RateLimit-Remaining": "0",
    }
    httpx_mock.add_response(status_code=429, json={"message": "too many"}, headers=headers)
    httpx_mock.add_response(status_code=429, json={"message": "too many"}, headers=headers)
    with WireBoardClient(token="t") as wb, pytest.raises(WireBoardApiError) as ei:
        wb.account()
    err = ei.value
    assert err.rate_limit is not None
    assert err.rate_limit["limit"] == 120
    assert err.rate_limit["remaining"] == 0
    assert err.rate_limit["retry_after"] == 0


def test_envelope_style_429_keeps_code(httpx_mock: Any) -> None:
    """``concurrent_limit_reached`` arrives wrapped in the standard envelope
    with HTTP 429. After the single retry, the SDK surfaces the typed code.
    """
    body = {
        "status": False,
        "errors": [{"text": "Too many concurrent live subscriptions."}],
        "fieldErrors": {"error_code": ["concurrent_limit_reached"]},
    }
    httpx_mock.add_response(status_code=429, json=body, headers={"Retry-After": "0"})
    httpx_mock.add_response(status_code=429, json=body, headers={"Retry-After": "0"})
    with WireBoardClient(token="t") as wb, pytest.raises(WireBoardApiError) as ei:
        wb.live_token()
    assert ei.value.code == "concurrent_limit_reached"
    assert ei.value.http_status == 429


# ─── URL/param encoding ────────────────────────────────────────────────────


def test_aggregate_encodes_params(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope(
            {"visitors": 0, "pageviews": 0, "bounce_rate": 0, "visit_duration": 0}
        )
    )
    with WireBoardClient(token="t") as wb:
        wb.aggregate(site_id="xK4mP2nT", from_="2026-05-01", to="2026-05-22")
    url = str(httpx_mock.get_requests()[0].url)
    assert "/v1/analytics/aggregate?" in url
    assert "site_id=xK4mP2nT" in url
    assert "from=2026-05-01" in url
    assert "to=2026-05-22" in url


def test_events_filter_and_group_by_serialisation(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope(
            {"rows": [], "total": 0, "group_by": ["category"], "limit": 50, "offset": 0}
        )
    )
    with WireBoardClient(token="t") as wb:
        wb.events(
            site_id="xK4mP2nT",
            from_="2026-05-01",
            to="2026-05-22",
            filter={"category": "Purchase", "props": {"plan": "pro"}},
            group_by=["category", "utm_source"],
        )
    url = httpx_mock.get_requests()[0].url
    # httpx decodes `[` `]` in the URL representation we read back.
    decoded = str(url)
    # `[` / `]` may be percent-encoded; check both forms.
    assert "filter[category]=Purchase" in decoded or "filter%5Bcategory%5D=Purchase" in decoded
    assert "filter[props.plan]=pro" in decoded or "filter%5Bprops.plan%5D=pro" in decoded
    assert "group_by=category%2Cutm_source" in decoded or "group_by=category,utm_source" in decoded


def test_date_objects_normalize_to_yyyy_mm_dd(httpx_mock: Any) -> None:
    httpx_mock.add_response(json=_envelope({"points": []}))
    with WireBoardClient(token="t") as wb:
        wb.history(site_id="xK4mP2nT", from_=date(2026, 5, 1), to=date(2026, 5, 22))
    url = str(httpx_mock.get_requests()[0].url)
    assert "from=2026-05-01" in url
    assert "to=2026-05-22" in url


# ─── live_state normalization ───────────────────────────────────────────────


def test_live_state_normalises_array_of_envelopes(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope(
            {
                "site_id": "xK4mP2nT",
                "ts": "2026-05-23T01:02:37.519Z",
                "live": [
                    {
                        "category": "visitors",
                        "ts": "2026-05-23T01:02:37.519Z",
                        "data": {"live": 5, "returning": 2},
                    },
                    {
                        "category": "top_pages",
                        "ts": "2026-05-23T01:02:37.519Z",
                        "data": [{"url": "/a", "title": "A", "count": 3}],
                    },
                ],
                "max_30d": 12,
                "max_30d_at": "2026-05-22",
            }
        )
    )
    with WireBoardClient(token="t") as wb:
        snap = wb.live_state(site_id="xK4mP2nT", categories=["visitors", "top_pages"])
    assert snap["live"] == {
        "visitors": {"live": 5, "returning": 2},
        "top_pages": [{"url": "/a", "title": "A", "count": 3}],
    }
    assert snap["max_30d"] == 12


def test_live_state_passes_map_shape_unchanged(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope(
            {
                "site_id": "xK4mP2nT",
                "ts": "2026-05-23T01:02:37.519Z",
                "live": {
                    "visitors": {"live": 6, "returning": 1},
                    "top_pages": [{"url": "/b", "title": "B", "count": 2}],
                },
                "max_30d": None,
                "max_30d_at": None,
            }
        )
    )
    with WireBoardClient(token="t") as wb:
        snap = wb.live_state(site_id="xK4mP2nT", categories=["visitors", "top_pages"])
    assert snap["live"] == {
        "visitors": {"live": 6, "returning": 1},
        "top_pages": [{"url": "/b", "title": "B", "count": 2}],
    }


def test_live_state_normalises_empty_array_to_empty_map(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope(
            {
                "site_id": "xK4mP2nT",
                "ts": "2026-05-23T01:02:37.519Z",
                "live": [],
                "max_30d": None,
                "max_30d_at": None,
            }
        )
    )
    with WireBoardClient(token="t") as wb:
        snap = wb.live_state(site_id="xK4mP2nT")
    assert snap["live"] == {}


# ─── with_meta ──────────────────────────────────────────────────────────────


def test_with_meta_returns_data_and_rate_limit(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope({"email": "s", "name": "S", "abilities": []}),
        headers={"X-RateLimit-Limit": "120", "X-RateLimit-Remaining": "117"},
    )
    with WireBoardClient(token="t") as wb:
        data, rate_limit = wb.with_meta(lambda c: c.account())
    assert data["email"] == "s"
    assert rate_limit is not None
    assert rate_limit["limit"] == 120
    assert rate_limit["remaining"] == 117


def test_with_meta_does_not_capture_outer_client_calls(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        json=_envelope({"email": "s", "name": "S", "abilities": []}),
        headers={"X-RateLimit-Remaining": "99"},
    )
    with WireBoardClient(token="t") as wb:
        def cb(c: WireBoardClient) -> Any:
            wb.account()  # outer call — should NOT be captured
            return None

        _, rate_limit = wb.with_meta(cb)
    assert rate_limit is None


# ─── Validation ─────────────────────────────────────────────────────────────


def test_invalid_date_string_raises_before_request(httpx_mock: Any) -> None:
    # No response queued: the assertion is that no request goes out.
    with WireBoardClient(token="t") as wb, pytest.raises(TypeError):
        wb.aggregate(site_id="x", from_="2026/05/01", to="2026-05-22")
    assert httpx_mock.get_requests() == []


def test_missing_token_raises() -> None:
    with pytest.raises(TypeError):
        WireBoardClient(token="")
