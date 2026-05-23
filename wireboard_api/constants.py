"""Public constants and category/dimension enums."""

from __future__ import annotations

from typing import Literal

#: Default API base URL.
DEFAULT_BASE_URL = "https://api.wireboard.io"

#: The 20 Live API categories, in their canonical order.
#:
#: Use this when you want to subscribe to "everything" without hard-coding the
#: list. The :data:`LiveCategory` type alias is derived from this tuple, so the
#: SDK guarantees the two stay in sync.
LIVE_CATEGORIES: tuple[
    Literal["visitors"],
    Literal["top_pages"],
    Literal["top_referrers"],
    Literal["top_mediums"],
    Literal["top_sources"],
    Literal["top_search"],
    Literal["top_social"],
    Literal["top_countries"],
    Literal["top_devices"],
    Literal["top_browsers"],
    Literal["top_oses"],
    Literal["top_languages"],
    Literal["top_screens"],
    Literal["time_spent"],
    Literal["pages_per_session"],
    Literal["performance"],
    Literal["life_events"],
    Literal["events"],
    Literal["geo"],
    Literal["active_sessions"],
] = (
    "visitors",
    "top_pages",
    "top_referrers",
    "top_mediums",
    "top_sources",
    "top_search",
    "top_social",
    "top_countries",
    "top_devices",
    "top_browsers",
    "top_oses",
    "top_languages",
    "top_screens",
    "time_spent",
    "pages_per_session",
    "performance",
    "life_events",
    "events",
    "geo",
    "active_sessions",
)

LiveCategory = Literal[
    "visitors",
    "top_pages",
    "top_referrers",
    "top_mediums",
    "top_sources",
    "top_search",
    "top_social",
    "top_countries",
    "top_devices",
    "top_browsers",
    "top_oses",
    "top_languages",
    "top_screens",
    "time_spent",
    "pages_per_session",
    "performance",
    "life_events",
    "events",
    "geo",
    "active_sessions",
]

#: Maps a breakdown dimension key to the field name returned per row.
#:
#: ``ref_url`` / ``entry_url`` / ``exit_url`` all return rows with a ``url`` field;
#: ``ref_medium`` returns ``medium``; etc.
BREAKDOWN_FIELDS: dict[str, str] = {
    "country": "country",
    "device": "device",
    "browser": "browser",
    "os": "os",
    "language": "language",
    "url": "url",
    "ref_url": "url",
    "ref_medium": "medium",
    "ref_source": "source",
    "ref_search": "term",
    "ref_social": "network",
    "entry_url": "url",
    "exit_url": "url",
}

BreakdownDimension = Literal[
    "country",
    "device",
    "browser",
    "os",
    "language",
    "url",
    "ref_url",
    "ref_medium",
    "ref_source",
    "ref_search",
    "ref_social",
    "entry_url",
    "exit_url",
]

#: Abilities a token can carry.
Ability = Literal["analytics:read", "live:read"]

#: Server-side limits exposed as a typed constant so customer code does not
#: need magic numbers. These mirror the API's documented caps; the API itself
#: is the source of truth and may tighten further.
LIMITS: dict[str, object] = {
    "breakdown": {"default": 50, "max": 500},
    "urls": {"default": 50, "max": 500, "offset_max": 10_000},
    "events": {"default": 50, "max": 1_000, "offset_max": 10_000},
    "range_days": 366,
    "rate_per_minute": {"default": 120, "live_token": 120},
    "live": {
        "concurrent_subscriptions": 10,
        "jwt_lifetime_seconds": 900,
    },
    "tokens_per_team": 10,
}
