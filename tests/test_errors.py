"""Tests for the error classes."""

from __future__ import annotations

from wireboard_api.errors import (
    PaidPlanRequiredError,
    PlanHistoryLimitExceededError,
    WireBoardApiError,
    WireBoardAuthError,
)


def test_api_error_captures_all_fields() -> None:
    err = WireBoardApiError(
        message="site not found",
        code="site_not_found",
        field_errors={"error_code": ["site_not_found"]},
        http_status=404,
        rate_limit={"limit": 120, "remaining": 117, "retry_after": None},
    )
    assert str(err) == "site not found"
    assert err.message == "site not found"
    assert err.code == "site_not_found"
    assert err.field_errors == {"error_code": ["site_not_found"]}
    assert err.http_status == 404
    assert err.rate_limit == {"limit": 120, "remaining": 117, "retry_after": None}
    assert isinstance(err, Exception)


def test_api_error_allows_null_code_for_plain_validation() -> None:
    err = WireBoardApiError(
        message="invalid",
        code=None,
        field_errors={"site_id": ["required"]},
        http_status=422,
        rate_limit=None,
    )
    assert err.code is None
    assert err.field_errors is not None
    assert err.field_errors["site_id"] == ["required"]


def test_auth_error_captures_401() -> None:
    err = WireBoardAuthError("Unauthenticated.", 401)
    assert err.http_status == 401
    assert str(err) == "Unauthenticated."


def test_auth_error_captures_403() -> None:
    err = WireBoardAuthError("Invalid ability provided.", 403)
    assert err.http_status == 403


# ─── PlanHistoryLimitExceededError ──────────────────────────────────────────


def test_plan_history_limit_is_subclass_with_locked_code_and_parsed_earliest() -> None:
    err = PlanHistoryLimitExceededError(
        message="Your plan limits historical queries to the last 30 days.",
        field_errors={
            "error_code": ["plan_history_limit_exceeded"],
            "earliest_allowed": ["2026-04-24"],
        },
        http_status=422,
        rate_limit=None,
    )
    assert isinstance(err, WireBoardApiError)
    assert isinstance(err, Exception)
    assert err.code == "plan_history_limit_exceeded"
    assert err.earliest_allowed == "2026-04-24"
    assert err.http_status == 422


def test_plan_history_limit_earliest_allowed_is_none_when_omitted() -> None:
    err = PlanHistoryLimitExceededError(
        message="plan limit",
        field_errors={"error_code": ["plan_history_limit_exceeded"]},
        http_status=422,
        rate_limit=None,
    )
    assert err.earliest_allowed is None


# ─── PaidPlanRequiredError ──────────────────────────────────────────────────


def test_paid_plan_required_is_api_error_not_auth_error() -> None:
    err = PaidPlanRequiredError(
        message="This endpoint requires a paid plan. Upgrade to access the Live API.",
        field_errors={"error_code": ["paid_plan_required"]},
        http_status=403,
        rate_limit=None,
    )
    assert isinstance(err, WireBoardApiError)
    # Critically: NOT a WireBoardAuthError, even though the HTTP status is 403.
    # Customers must distinguish "needs upgrade" from "needs re-auth".
    assert not isinstance(err, WireBoardAuthError)
    assert err.code == "paid_plan_required"
    assert err.http_status == 403
