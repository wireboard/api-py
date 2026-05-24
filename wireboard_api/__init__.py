"""Official Python SDK for the WireBoard REST and Live (SSE) APIs.

Quickstart::

    from wireboard_api import WireBoardClient

    wb = WireBoardClient(token="your_token")
    sites = wb.sites()
    site = sites["sites"][0]
    summary = wb.aggregate(
        site_id=site["id"], from_="2026-05-01", to="2026-05-22",
    )

See the README for the full surface, async usage, and Live API details.
"""

from ._version import VERSION
from .async_client import AsyncWireBoardClient
from .client import WireBoardClient
from .constants import (
    BREAKDOWN_FIELDS,
    DEFAULT_BASE_URL,
    LIMITS,
    LIVE_CATEGORIES,
    Ability,
    BreakdownDimension,
    LiveCategory,
)
from .errors import (
    PaidPlanRequiredError,
    PlanHistoryLimitExceededError,
    WireBoardApiError,
    WireBoardAuthError,
)
from .live.async_managed import AsyncLiveClient
from .live.async_raw import AsyncLiveRawClient
from .live.managed import LiveClient
from .live.raw import LiveRawClient
from .types import (
    Account,
    ActiveSessionEntry,
    AggregateResult,
    BreakdownResult,
    Dimensions,
    EventFilter,
    EventFilterKey,
    EventGroupByKey,
    EventsEntry,
    EventsResult,
    GeoEntry,
    HistoryMetric,
    HistoryPoint,
    HistoryResult,
    LifeEventsData,
    LiveCategoriesData,
    LiveClientStatus,
    LiveEnvelope,
    LiveStateSnapshot,
    LiveTokenResult,
    ManagedLiveState,
    PagesPerSessionDict,
    PerformanceData,
    RateLimitInfo,
    Site,
    SitesResult,
    TimeseriesPoint,
    TimeseriesResult,
    TimeSpentDict,
    TopBrowserEntry,
    TopCountryEntry,
    TopDeviceEntry,
    TopLanguageEntry,
    TopMediumEntry,
    TopOsEntry,
    TopPagesEntry,
    TopReferrerEntry,
    TopScreenEntry,
    TopSearchEntry,
    TopSocialEntry,
    TopSourceEntry,
    UrlRow,
    UrlsResult,
    VisitorsData,
)

__version__ = VERSION

__all__ = [
    "VERSION",
    "__version__",
    # Clients
    "WireBoardClient",
    "AsyncWireBoardClient",
    "LiveClient",
    "AsyncLiveClient",
    "LiveRawClient",
    "AsyncLiveRawClient",
    # Errors
    "WireBoardApiError",
    "WireBoardAuthError",
    "PaidPlanRequiredError",
    "PlanHistoryLimitExceededError",
    # Constants
    "DEFAULT_BASE_URL",
    "LIVE_CATEGORIES",
    "BREAKDOWN_FIELDS",
    "LIMITS",
    "Ability",
    "LiveCategory",
    "BreakdownDimension",
    # Types
    "Account",
    "Site",
    "SitesResult",
    "AggregateResult",
    "TimeseriesPoint",
    "TimeseriesResult",
    "HistoryMetric",
    "HistoryPoint",
    "HistoryResult",
    "BreakdownResult",
    "UrlRow",
    "UrlsResult",
    "EventFilterKey",
    "EventGroupByKey",
    "EventFilter",
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
