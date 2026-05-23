"""Per-category merge logic.

Pure functions. Snapshot replacement, top-N drop merging (``count == 0``
removes the entry), and active-session drop merging (``step_count == 0``
removes the session).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, cast

from ..types import (
    ActiveSessionEntry,
    GeoEntry,
    LiveCategoriesData,
    LiveEnvelope,
    LiveStateSnapshot,
    ManagedLiveState,
)


def empty_categories_data() -> LiveCategoriesData:
    return LiveCategoriesData(
        visitors=None,
        top_pages=[],
        top_referrers=[],
        top_mediums=[],
        top_sources=[],
        top_search=[],
        top_social=[],
        top_countries=[],
        top_devices=[],
        top_browsers=[],
        top_oses=[],
        top_languages=[],
        top_screens=[],
        time_spent=None,
        pages_per_session=None,
        performance=None,
        life_events=None,
        events=[],
        geo=[],
        active_sessions=[],
    )


def empty_state(site_id: str) -> ManagedLiveState:
    return ManagedLiveState(
        site_id=site_id,
        ts="1970-01-01T00:00:00.000Z",
        live=empty_categories_data(),
        max_30d=None,
        max_30d_at=None,
    )


def from_snapshot(snapshot: LiveStateSnapshot) -> ManagedLiveState:
    base: dict[str, Any] = cast("dict[str, Any]", empty_categories_data())
    snap_live: Any = snapshot.get("live") or {}
    # The spec documents `live` as `{ category: data, ... }`, but the live
    # production API may return `live` as a list of envelope-shaped objects
    # (`[{category, ts, data}, ...]`). ``live_state()`` normalises at the
    # boundary, but be defensive here too.
    if isinstance(snap_live, list):
        for envelope in snap_live:
            if not isinstance(envelope, dict):
                continue
            cat = envelope.get("category")
            if cat is None:
                continue
            base[cat] = envelope.get("data")
    elif isinstance(snap_live, dict):
        for key, value in snap_live.items():
            base[key] = value
    return ManagedLiveState(
        site_id=snapshot["site_id"],
        ts=snapshot["ts"],
        live=cast("LiveCategoriesData", base),
        max_30d=snapshot.get("max_30d"),
        max_30d_at=snapshot.get("max_30d_at"),
    )


def _merge_top_n(
    prev: Iterable[dict[str, Any]],
    delta: Iterable[dict[str, Any]],
    key_of: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in prev:
        out[key_of(item)] = item
    for item in delta:
        k = key_of(item)
        if item.get("count") == 0:
            out.pop(k, None)
        else:
            out[k] = item
    return sorted(out.values(), key=lambda e: e.get("count", 0), reverse=True)


def _merge_sessions(
    prev: Iterable[ActiveSessionEntry],
    delta: Iterable[ActiveSessionEntry],
) -> list[ActiveSessionEntry]:
    out: dict[str, ActiveSessionEntry] = {}
    for s in prev:
        out[s["session_id"]] = s
    for s in delta:
        if s.get("step_count") == 0:
            out.pop(s["session_id"], None)
        else:
            out[s["session_id"]] = s
    return list(out.values())


def _geo_key(g: GeoEntry) -> str:
    return f"{g['lat']},{g['lng']}"


# Category → (key extractor) for top-N categories.
_TOP_N_KEY: dict[str, Callable[[dict[str, Any]], str]] = {
    "top_pages": lambda r: r["url"],
    "top_referrers": lambda r: r["url"],
    "top_mediums": lambda r: r["medium"],
    "top_sources": lambda r: r["source"],
    "top_search": lambda r: r["term"],
    "top_social": lambda r: r["network"],
    "top_countries": lambda r: r["country"],
    "top_devices": lambda r: r["device"],
    "top_browsers": lambda r: r["browser"],
    "top_oses": lambda r: r["os"],
    "top_languages": lambda r: r["language"],
    "top_screens": lambda r: r["resolution"],
    "geo": lambda r: f"{r['lat']},{r['lng']}",
}

# Categories that fully replace state on each delivery.
_REPLACE_CATEGORIES = {
    "visitors",
    "time_spent",
    "pages_per_session",
    "performance",
    "life_events",
    "events",
}


def apply_event(state: ManagedLiveState, env: LiveEnvelope) -> ManagedLiveState:
    """Apply one envelope to a state object, returning a new state.

    The previous state is left untouched. Sub-objects are reused where
    unchanged so identity comparisons (``prev is not next``) work as a
    cheap change check across the whole state.
    """
    category = env["category"]
    data = env["data"]
    # Use a plain dict for mutation; TypedDict members are heterogeneously
    # typed, which makes per-key assignment a type-checker fight even though
    # the runtime contract is sound. Cast back at the boundary.
    live: dict[str, Any] = dict(state["live"])
    prev_live: dict[str, Any] = cast("dict[str, Any]", state["live"])

    if category in _REPLACE_CATEGORIES:
        live[category] = data
    elif category in _TOP_N_KEY:
        key_of = _TOP_N_KEY[category]
        prev_list = prev_live.get(category, []) or []
        live[category] = _merge_top_n(prev_list, data, key_of)
    elif category == "active_sessions":
        prev_sessions = prev_live.get("active_sessions", []) or []
        live["active_sessions"] = _merge_sessions(prev_sessions, data)
    else:
        # Unknown category — leave state untouched. The server may add
        # categories in the future; the SDK is forward-compatible.
        return state

    return ManagedLiveState(
        site_id=state["site_id"],
        ts=env["ts"],
        live=cast("LiveCategoriesData", live),
        max_30d=state["max_30d"],
        max_30d_at=state["max_30d_at"],
    )
