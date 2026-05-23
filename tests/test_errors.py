"""Tests for the error classes."""

from __future__ import annotations

from wireboard_api.errors import WireBoardApiError, WireBoardAuthError


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
