"""Error classes raised by the SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .types import RateLimitInfo


class WireBoardApiError(Exception):
    """Raised when the WireBoard API returns an envelope error (``status: false``),
    a non-envelope 429 (rate-limit cap), or any non-401/403 HTTP failure.

    Branch on :attr:`code` for known stable identifiers (``"site_not_found"``,
    ``"unknown_categories"``, ``"concurrent_limit_reached"``, ...). For plain
    validation errors (``field_errors`` present without ``error_code``), branch
    on ``http_status == 422`` and inspect :attr:`field_errors`.

    Bare-body auth failures (401/403) raise :class:`WireBoardAuthError`
    instead — they do not carry the envelope.
    """

    #: Stable machine-readable code from ``field_errors["error_code"][0]`` when
    #: present. Examples: ``"site_not_found"``, ``"unknown_categories"``,
    #: ``"unknown_filter"``, ``"unknown_group_by"``,
    #: ``"concurrent_limit_reached"``, ``"route_not_found"``. ``None`` for
    #: plain validation errors and bare-body 429s.
    code: str | None

    #: Per-field validation messages and the ``error_code`` map.
    field_errors: dict[str, list[str]] | None

    #: HTTP status code of the failing response.
    http_status: int

    #: Rate-limit headers parsed from the failing response, when present.
    rate_limit: RateLimitInfo | None

    def __init__(
        self,
        *,
        message: str,
        code: str | None,
        field_errors: dict[str, list[str]] | None,
        http_status: int,
        rate_limit: RateLimitInfo | None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field_errors = field_errors
        self.http_status = http_status
        self.rate_limit = rate_limit

    @property
    def message(self) -> str:
        """The human-readable error message (same as ``str(err)``)."""
        return str(self)


class WireBoardAuthError(Exception):
    """Raised when the API returns 401 (unauthenticated) or 403 (forbidden /
    missing ability) for an *authentication* reason — i.e. the token itself
    is invalid, expired, or lacks the required ability. These responses
    carry a bare ``{"message": str}`` body, so there is no ``code`` or
    ``field_errors``.

    Handle as "401 → re-auth; 403 → re-mint a token with the right abilities."

    NOTE: a 403 that comes from a *plan limit* (not an auth issue) raises
    :class:`PaidPlanRequiredError` instead — the user's auth is fine, they
    just need a paid plan.
    """

    http_status: Literal[401, 403]

    def __init__(self, message: str, http_status: Literal[401, 403]) -> None:
        super().__init__(message)
        self.http_status = http_status

    @property
    def message(self) -> str:
        return str(self)


class PlanHistoryLimitExceededError(WireBoardApiError):
    """Raised when a free-plan caller requests historical analytics with a
    ``from_`` date older than 30 days ago (UTC). Applies to every
    ``/v1/analytics/*`` endpoint (``aggregate``, ``timeseries``, ``history``,
    ``breakdown``, ``urls``, ``events``). HTTP 422.

    Inspect :attr:`earliest_allowed` for the earliest ``from_`` date the
    server would accept; re-issue with that date, or surface an upgrade
    prompt to the user.

    Subclass of :class:`WireBoardApiError`, so ``isinstance(err,
    WireBoardApiError)`` still matches; catch the more specific class first
    when both apply.
    """

    def __init__(
        self,
        *,
        message: str,
        field_errors: dict[str, list[str]] | None,
        http_status: int,
        rate_limit: RateLimitInfo | None,
    ) -> None:
        super().__init__(
            message=message,
            code="plan_history_limit_exceeded",
            field_errors=field_errors,
            http_status=http_status,
            rate_limit=rate_limit,
        )

    @property
    def earliest_allowed(self) -> str | None:
        """Earliest ``from_`` date the server would accept for this caller,
        formatted ``YYYY-MM-DD``. ``None`` if the server didn't include it
        (shouldn't happen in practice; the contract guarantees the field).
        """
        if self.field_errors is None:
            return None
        values = self.field_errors.get("earliest_allowed")
        if not values:
            return None
        return values[0]


class PaidPlanRequiredError(WireBoardApiError):
    """Raised when a free-plan caller hits an endpoint that requires a paid
    plan. Currently applies to the entire Live API (``/v1/live/token``,
    ``/v1/live/state``). HTTP 403.

    The user's authentication is fine — they need to upgrade. Don't push
    them through a re-login flow; surface an upgrade prompt
    (``/account/billing`` or your equivalent).

    Subclass of :class:`WireBoardApiError`; NOT a :class:`WireBoardAuthError`,
    because this is a business-logic refusal, not an auth refusal.
    """

    def __init__(
        self,
        *,
        message: str,
        field_errors: dict[str, list[str]] | None,
        http_status: int,
        rate_limit: RateLimitInfo | None,
    ) -> None:
        super().__init__(
            message=message,
            code="paid_plan_required",
            field_errors=field_errors,
            http_status=http_status,
            rate_limit=rate_limit,
        )
