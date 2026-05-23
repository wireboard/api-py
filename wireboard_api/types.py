"""TypedDicts for every REST result and Live envelope shape.

These mirror the TypeScript interfaces in ``src/types.ts`` of the JS SDK
1-to-1. Field names match the wire format, so accessing
``result["visitors"]`` works as expected.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from typing_extensions import NotRequired

from ._date import DateInput
from .constants import Ability, BreakdownDimension, LiveCategory

__all__ = [
    "DateInput",
    "Account",
    "Site",
    "SitesResult",
    "AggregateResult",
    "TimeseriesPoint",
    "TimeseriesResult",
    "HistoryMetric",
    "HistoryPoint",
    "HistoryResult",
    "BreakdownRow",
    "BreakdownResult",
    "UrlRow",
    "UrlsResult",
    "EventFilterKey",
    "EventGroupByKey",
    "EventFilter",
    "EventRow",
    "EventsResult",
    "Dimensions",
    "VisitorsData",
    "TopPagesEntry",
    "TopReferrerEntry",
    "TopMediumEntry",
    "TopSourceEntry",
    "TopSearchEntry",
    "TopSocialEntry",
    "TopCountryEntry",
    "TopDeviceEntry",
    "TopBrowserEntry",
    "TopOsEntry",
    "TopLanguageEntry",
    "TopScreenEntry",
    "TimeSpentDict",
    "PagesPerSessionDict",
    "PerformanceData",
    "LifeEventsData",
    "EventsEntry",
    "GeoEntry",
    "ActiveSessionEntry",
    "LiveCategoriesData",
    "LiveStateSnapshot",
    "LiveTokenResult",
    "LiveEnvelope",
    "RateLimitInfo",
    "LiveClientStatus",
    "ManagedLiveState",
]


class Account(TypedDict):
    """Identity + ability set of the team owner whose token is in use."""

    email: str
    name: str
    abilities: list[Ability]


class Site(TypedDict):
    """A site owned by the team."""

    id: str
    domain: str
    #: Highest concurrent live visitor count over the last 30 days.
    #: ``None`` if no traffic.
    max_30d: int | None
    #: UTC timestamp of when ``max_30d`` was last reached. ``None`` if
    #: ``max_30d`` is None.
    max_30d_at: str | None


class SitesResult(TypedDict):
    sites: list[Site]


class AggregateResult(TypedDict):
    visitors: int
    pageviews: int
    #: Percentage (0–100), one decimal place.
    bounce_rate: float
    #: Average session duration in seconds.
    visit_duration: float


class TimeseriesPoint(TypedDict):
    #: Bucket start as an ISO 8601 timestamp.
    time: str
    value: float


class TimeseriesResult(TypedDict):
    points: list[TimeseriesPoint]


HistoryMetric = Literal[
    "visitors",
    "returning_visitors",
    "pageviews",
    "bounce_rate",
    "avg_duration",
]


class HistoryPoint(TypedDict):
    #: YYYY-MM-DD UTC calendar day.
    date: str
    visitors: int
    returning_visitors: int
    pageviews: int
    #: Percentage (0–100), one decimal place.
    bounce_rate: float
    #: Average session duration in seconds.
    avg_duration: float


class HistoryResult(TypedDict):
    points: list[HistoryPoint]


#: Row of a breakdown response. The dimension-specific field
#: (``country``/``url``/``medium``/...) is keyed by name, so use the
#: ``BREAKDOWN_FIELDS`` map (or just access the known key) to read it.
BreakdownRow = dict[str, Any]


class BreakdownResult(TypedDict):
    dimension: BreakdownDimension
    metric: Literal["visitors"]
    rows: list[BreakdownRow]


class UrlRow(TypedDict):
    url: str
    visitors: int
    pageviews: int
    bounce_rate: float
    avg_duration: float


class UrlsResult(TypedDict):
    rows: list[UrlRow]
    total: int
    limit: int
    offset: int


EventFilterKey = Literal[
    "category",
    "action",
    "label",
    "utm_campaign",
    "utm_source",
    "utm_medium",
    "utm_content",
    "utm_term",
]

EventGroupByKey = EventFilterKey


class EventFilter(TypedDict, total=False):
    """Exact-match filters for the events endpoint."""

    category: str
    action: str
    label: str
    utm_campaign: str
    utm_source: str
    utm_medium: str
    utm_content: str
    utm_term: str
    #: Filter by event props. Serialised as ``filter[props.<key>]=<value>``.
    props: dict[str, str]


#: Row of an events response. Keys are ``count``, ``value``, plus one key per
#: ``group_by`` field (each of type ``str | None``).
EventRow = dict[str, Any]


class EventsResult(TypedDict):
    rows: list[EventRow]
    total: int
    group_by: list[EventGroupByKey]
    limit: int
    offset: int


class _BreakdownDimensionMeta(TypedDict):
    key: BreakdownDimension
    field: str


class Dimensions(TypedDict):
    """Meta endpoint result: the lists the SDK doesn't need to hard-code."""

    breakdown_dimensions: list[_BreakdownDimensionMeta]
    event_filter_fields: list[EventFilterKey]
    event_group_by_fields: list[EventGroupByKey]
    history_metrics: list[HistoryMetric]
    max_range_days: int


# ─── Live API payload shapes (one per category) ─────────────────────────────


class VisitorsData(TypedDict):
    #: Currently active sessions.
    live: int
    #: Of the live sessions, how many have visited before.
    returning: int


class TopPagesEntry(TypedDict):
    url: str
    #: Page ``<title>`` as seen by the tracker; ``None`` until collected.
    title: str | None
    count: int


class TopReferrerEntry(TypedDict):
    url: str
    count: int


class TopMediumEntry(TypedDict):
    medium: str
    count: int


class TopSourceEntry(TypedDict):
    source: str
    count: int


class TopSearchEntry(TypedDict):
    term: str
    count: int


class TopSocialEntry(TypedDict):
    network: str
    count: int


class TopCountryEntry(TypedDict):
    country: str
    count: int


class TopDeviceEntry(TypedDict):
    device: str
    count: int


class TopBrowserEntry(TypedDict):
    browser: str
    count: int


class TopOsEntry(TypedDict):
    os: str
    count: int


class TopLanguageEntry(TypedDict):
    language: str
    count: int


class TopScreenEntry(TypedDict):
    resolution: str
    count: int


class TimeSpentData(TypedDict):
    lt_1m: int
    # "1_3m" through "10_20m" and "gt_20m" — but TypedDict requires identifier
    # keys, so we expose these via a get-by-key access rather than attribute.
    # The JS SDK exposes them as quoted property names too.


# The TimeSpent / PagesPerSession / Performance shapes contain string keys
# that aren't valid Python identifiers (``"1_3m"``, ``"6_10"`` etc), so we
# fall back to ``dict[str, int]`` aliases for those.
TimeSpentDict = dict[str, int]
PagesPerSessionDict = dict[str, int]
PerformanceDict = dict[str, int]


class PerformanceData(TypedDict):
    excellent: int
    good: int
    average: int
    below_average: int
    poor: int


class LifeEventsData(TypedDict):
    arrived: int
    navigated: int
    departed: int
    #: UTC ISO 8601 timestamp of the delivery window.
    ts: str


class EventsEntry(TypedDict):
    """A single custom-event row delivered over the Live API stream.

    Distinct from REST ``/v1/analytics/events`` rows (which are aggregated by
    ``group_by`` and don't carry per-event timestamps).
    """

    category: str
    action: str
    label: str | None
    #: Number of times this (category, action, label) fired in the delivery
    #: window.
    count: int
    #: Sum of the event's ``value`` field across the window.
    value: float
    #: UTC ISO 8601 timestamp of when this event most recently fired.
    time: str


class GeoEntry(TypedDict):
    #: Hex-aggregated centroid, not exact visitor position.
    lat: float
    lng: float
    count: int


class ActiveSessionEntry(TypedDict):
    session_id: str
    current_page: str | None
    entry_url: str | None
    country: str | None
    device: str | None
    browser: str | None
    os: str | None
    source: str | None
    #: Steps taken so far in this session. A session-end signal arrives once
    #: as ``step_count: 0`` with every metadata field set to ``None`` — treat
    #: that as "remove this session from local state."
    step_count: int
    last_activity: str | None


class LiveCategoriesData(TypedDict):
    """Merged state per category. Single-object payloads become ``T | None``."""

    visitors: VisitorsData | None
    top_pages: list[TopPagesEntry]
    top_referrers: list[TopReferrerEntry]
    top_mediums: list[TopMediumEntry]
    top_sources: list[TopSourceEntry]
    top_search: list[TopSearchEntry]
    top_social: list[TopSocialEntry]
    top_countries: list[TopCountryEntry]
    top_devices: list[TopDeviceEntry]
    top_browsers: list[TopBrowserEntry]
    top_oses: list[TopOsEntry]
    top_languages: list[TopLanguageEntry]
    top_screens: list[TopScreenEntry]
    time_spent: TimeSpentDict | None
    pages_per_session: PagesPerSessionDict | None
    performance: PerformanceData | None
    #: EPHEMERAL. Replaced on every delivery; not cumulative. ``None`` until
    #: the first delivery. Empty windows produce no delta — treat each
    #: delivery as "events that fired since the last delivery."
    life_events: LifeEventsData | None
    #: EPHEMERAL. Replaced on every delivery; not cumulative.
    events: list[EventsEntry]
    geo: list[GeoEntry]
    active_sessions: list[ActiveSessionEntry]


class LiveStateSnapshot(TypedDict):
    """Result of ``GET /v1/live/state``."""

    site_id: str
    #: UTC ISO timestamp of when the snapshot was assembled.
    ts: str
    #: Per-category state for the categories included in the request. The
    #: server omits categories with no current data, so this is a partial map.
    live: dict[str, Any]
    max_30d: int | None
    max_30d_at: str | None


class LiveTokenResult(TypedDict):
    """Result of ``GET /v1/live/token``."""

    #: SSE endpoint URL.
    hub_url: str
    #: Short-lived JWT authorising the subscription.
    token: str
    #: Opaque per-(site, category) topic identifiers; pass as ``?topic=``
    #: query params on the EventSource URL.
    topics: list[str]
    sites: list[str]
    categories: list[LiveCategory]
    #: JWT lifetime in seconds.
    expires_in: int


# Live envelope: a single typed dict with a literal ``category`` field and
# ``data`` typed loosely. Per-category narrowing is done by the caller with
# an ``if env["category"] == ...`` check.
class LiveEnvelope(TypedDict):
    site_id: str
    category: LiveCategory
    ts: str
    data: Any


class RateLimitInfo(TypedDict):
    """Rate-limit headers parsed from a response."""

    limit: int | None
    remaining: int | None
    #: Seconds. Present on 429 responses; ``None`` otherwise.
    retry_after: int | None


LiveClientStatus = Literal["idle", "connecting", "open", "closed"]


class ManagedLiveState(TypedDict):
    """The state object emitted by the managed Live client.

    A NEW object is produced on every update so equality checks
    (``prev is not next``) work as expected.
    """

    site_id: str
    ts: str
    live: LiveCategoriesData
    max_30d: int | None
    max_30d_at: str | None


# Helper unions exposed for typing convenience.
LiveData = (
    VisitorsData
    | list[TopPagesEntry]
    | list[TopReferrerEntry]
    | list[TopMediumEntry]
    | list[TopSourceEntry]
    | list[TopSearchEntry]
    | list[TopSocialEntry]
    | list[TopCountryEntry]
    | list[TopDeviceEntry]
    | list[TopBrowserEntry]
    | list[TopOsEntry]
    | list[TopLanguageEntry]
    | list[TopScreenEntry]
    | TimeSpentDict
    | PagesPerSessionDict
    | PerformanceData
    | LifeEventsData
    | list[EventsEntry]
    | list[GeoEntry]
    | list[ActiveSessionEntry]
)


# Re-export NotRequired and other public typing for downstream type stubs.
__all__ += ["NotRequired", "TimeSpentDict", "PagesPerSessionDict", "PerformanceDict", "LiveData"]
