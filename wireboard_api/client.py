"""Synchronous WireBoard API client."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

import httpx

from ._date import DateInput
from ._normalize import normalize_live_state_snapshot
from ._transport import Transport, TransportOptions
from .async_client import AsyncWireBoardClient
from .constants import DEFAULT_BASE_URL, BreakdownDimension, LiveCategory
from .live.managed import LiveClient
from .live.raw import LiveRawClient
from .types import (
    Account,
    AggregateResult,
    BreakdownResult,
    Dimensions,
    EventFilter,
    EventGroupByKey,
    EventsResult,
    HistoryResult,
    LiveEnvelope,
    LiveStateSnapshot,
    LiveTokenResult,
    ManagedLiveState,
    RateLimitInfo,
    SitesResult,
    TimeseriesResult,
    UrlsResult,
)


class WireBoardClient:
    """Synchronous WireBoard API client.

    Holds a bearer token in memory and exposes one method per REST endpoint,
    plus factories for the Live (SSE) clients. Methods return the unwrapped
    ``data`` payload from the API envelope and raise
    :class:`WireBoardApiError` or :class:`WireBoardAuthError` on failure.

    Example::

        with WireBoardClient(token=token) as wb:
            sites = wb.sites()
            site = sites["sites"][0]
            summary = wb.aggregate(
                site_id=site["id"], from_="2026-05-01", to="2026-05-22",
            )
    """

    def __init__(
        self,
        *,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        retry_on_429: bool = True,
        timeout: float | None = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not isinstance(token, str) or not token:
            raise TypeError("WireBoardClient: `token` is required.")
        self._opts = TransportOptions(
            token=token,
            base_url=base_url,
            retry_on_429=retry_on_429,
            timeout=timeout,
            client=client,
        )
        self._transport = Transport(self._opts)

    @property
    def transport(self) -> Transport:
        return self._transport

    def __enter__(self) -> WireBoardClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client (if owned by this instance)."""
        self._transport.close()

    # ─── REST ──────────────────────────────────────────────────────────────

    def account(self) -> Account:
        """``GET /v1/account`` — team-owner identity and the abilities of
        this token.
        """
        return cast("Account", self._transport.get("/v1/account"))

    def sites(self) -> SitesResult:
        """``GET /v1/sites`` — every site owned by the team."""
        return cast("SitesResult", self._transport.get("/v1/sites"))

    def aggregate(
        self,
        *,
        site_id: str,
        from_: DateInput,
        to: DateInput,
    ) -> AggregateResult:
        """``GET /v1/analytics/aggregate`` — period totals."""
        return cast(
            "AggregateResult",
            self._transport.get(
                "/v1/analytics/aggregate",
                {"site_id": site_id, "from": from_, "to": to},
            ),
        )

    def timeseries(
        self,
        *,
        site_id: str,
        from_: DateInput,
        to: DateInput,
        metric: str,
        interval: str,
    ) -> TimeseriesResult:
        """``GET /v1/analytics/timeseries`` — one metric bucketed over time."""
        return cast(
            "TimeseriesResult",
            self._transport.get(
                "/v1/analytics/timeseries",
                {
                    "site_id": site_id,
                    "from": from_,
                    "to": to,
                    "metric": metric,
                    "interval": interval,
                },
            ),
        )

    def history(
        self,
        *,
        site_id: str,
        from_: DateInput,
        to: DateInput,
    ) -> HistoryResult:
        """``GET /v1/analytics/history`` — visitors / returning / pageviews
        / bounce / duration per UTC day.
        """
        return cast(
            "HistoryResult",
            self._transport.get(
                "/v1/analytics/history",
                {"site_id": site_id, "from": from_, "to": to},
            ),
        )

    def breakdown(
        self,
        *,
        site_id: str,
        from_: DateInput,
        to: DateInput,
        dimension: BreakdownDimension,
        limit: int | None = None,
    ) -> BreakdownResult:
        """``GET /v1/analytics/breakdown`` — top-N rows by one dimension."""
        return cast(
            "BreakdownResult",
            self._transport.get(
                "/v1/analytics/breakdown",
                {
                    "site_id": site_id,
                    "from": from_,
                    "to": to,
                    "dimension": dimension,
                    "limit": limit,
                },
            ),
        )

    def urls(
        self,
        *,
        site_id: str,
        from_: DateInput,
        to: DateInput,
        prefix: str | None = None,
        contains: str | None = None,
        exact: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> UrlsResult:
        """``GET /v1/analytics/urls`` — per-URL rich metrics."""
        return cast(
            "UrlsResult",
            self._transport.get(
                "/v1/analytics/urls",
                {
                    "site_id": site_id,
                    "from": from_,
                    "to": to,
                    "prefix": prefix,
                    "contains": contains,
                    "exact": exact,
                    "limit": limit,
                    "offset": offset,
                },
            ),
        )

    def events(
        self,
        *,
        site_id: str,
        from_: DateInput,
        to: DateInput,
        group_by: Sequence[EventGroupByKey] | None = None,
        filter: EventFilter | None = None,  # noqa: A002 — mirrors API param name
        limit: int | None = None,
        offset: int | None = None,
    ) -> EventsResult:
        """``GET /v1/analytics/events`` — custom events report."""
        return cast(
            "EventsResult",
            self._transport.get(
                "/v1/analytics/events",
                {
                    "site_id": site_id,
                    "from": from_,
                    "to": to,
                    "group_by": list(group_by) if group_by is not None else None,
                    "filter": filter,
                    "limit": limit,
                    "offset": offset,
                },
            ),
        )

    def dimensions(self) -> Dimensions:
        """``GET /v1/analytics/dimensions`` — meta endpoint."""
        return cast("Dimensions", self._transport.get("/v1/analytics/dimensions"))

    # ─── Live (low-level) ──────────────────────────────────────────────────

    def live_state(
        self,
        *,
        site_id: str,
        categories: list[LiveCategory] | None = None,
    ) -> LiveStateSnapshot:
        """``GET /v1/live/state`` — current per-category snapshot.

        Normalises the server's array-of-envelopes shape to the
        spec-documented ``{ category: data, ... }`` map at the SDK boundary.
        """
        raw = self._transport.get(
            "/v1/live/state",
            {"site_id": site_id, "categories": categories},
        )
        return cast("LiveStateSnapshot", normalize_live_state_snapshot(raw))

    def live_token(
        self,
        *,
        sites: list[str] | None = None,
        categories: list[LiveCategory] | None = None,
    ) -> LiveTokenResult:
        """``GET /v1/live/token`` — mint a short-lived subscriber JWT."""
        return cast(
            "LiveTokenResult",
            self._transport.get(
                "/v1/live/token",
                {"sites": sites, "categories": categories},
            ),
        )

    # ─── Live (factories) ──────────────────────────────────────────────────

    def live(
        self,
        *,
        site_id: str,
        categories: list[LiveCategory] | None = None,
        on_change: Callable[[ManagedLiveState], None] | None = None,
        on_event: Callable[[LiveEnvelope], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_rotate: Callable[[], None] | None = None,
        on_reconnect: Callable[[], None] | None = None,
    ) -> LiveClient:
        """Create a managed Live client for a single site. Synchronous
        facade — internally runs an async SSE engine on a worker thread.
        Callbacks fire on that thread.
        """
        # The Live engine is async-first; build a minter from a fresh async
        # client configured with the same options. Hand ownership to the
        # LiveClient so it aclose()s the httpx pool when stopped.
        async_minter = AsyncWireBoardClient(
            token=self._opts.token,
            base_url=self._opts.base_url,
            retry_on_429=self._opts.retry_on_429,
            timeout=self._opts.timeout,
        )
        return LiveClient(
            async_minter,
            site_id=site_id,
            categories=categories,
            on_change=on_change,
            on_event=on_event,
            on_error=on_error,
            on_rotate=on_rotate,
            on_reconnect=on_reconnect,
            owned_minter=async_minter,
        )

    def live_raw(
        self,
        *,
        sites: str | list[str],
        on_event: Callable[[LiveEnvelope], None],
        categories: list[LiveCategory] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_rotate: Callable[[], None] | None = None,
        on_reconnect: Callable[[], None] | None = None,
    ) -> LiveRawClient:
        """Create a raw Live client. Synchronous facade."""
        async_minter = AsyncWireBoardClient(
            token=self._opts.token,
            base_url=self._opts.base_url,
            retry_on_429=self._opts.retry_on_429,
            timeout=self._opts.timeout,
        )
        return LiveRawClient(
            async_minter,
            sites=sites,
            categories=categories,
            on_event=on_event,
            on_error=on_error,
            on_rotate=on_rotate,
            on_reconnect=on_reconnect,
            owned_minter=async_minter,
        )

    # ─── Instrumentation ───────────────────────────────────────────────────

    def with_meta(
        self,
        fn: Callable[[WireBoardClient], Any],
    ) -> tuple[Any, RateLimitInfo | None]:
        """Run ``fn`` against an instrumented client and return its result
        plus the rate-limit headers from the last response observed inside it.

        Example::

            data, rate_limit = wb.with_meta(
                lambda c: c.aggregate(site_id=site_id, from_=f, to=t),
            )
        """
        captured: list[RateLimitInfo] = []
        child = WireBoardClient(
            token=self._opts.token,
            base_url=self._opts.base_url,
            retry_on_429=self._opts.retry_on_429,
            timeout=self._opts.timeout,
            client=self._opts.client if isinstance(self._opts.client, httpx.Client) else None,
        )

        def hook(info: RateLimitInfo) -> None:
            captured.append(info)

        child._transport.set_response_hook(hook)
        try:
            data = fn(child)
        finally:
            child._transport.set_response_hook(None)
            child._opts._owns_client = False
        return data, captured[-1] if captured else None
