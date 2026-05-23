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
    missing ability). These responses carry a bare ``{"message": str}`` body,
    not the standard envelope, so there is no ``code`` or ``field_errors``.

    Handle as "401 → re-auth; 403 → re-mint a token with the right abilities."
    """

    http_status: Literal[401, 403]

    def __init__(self, message: str, http_status: Literal[401, 403]) -> None:
        super().__init__(message)
        self.http_status = http_status

    @property
    def message(self) -> str:
        return str(self)
