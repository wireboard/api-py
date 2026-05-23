"""Tests for the Live-state merge logic."""

from __future__ import annotations

from typing import cast

from wireboard_api.live._merge import apply_event, empty_state, from_snapshot
from wireboard_api.types import LiveEnvelope, LiveStateSnapshot, ManagedLiveState

SITE = "xK4mP2nT"


def fresh() -> ManagedLiveState:
    return empty_state(SITE)


# ─── emptyState ─────────────────────────────────────────────────────────────


def test_empty_state_returns_fully_populated_empty_state() -> None:
    s = empty_state(SITE)
    assert s["site_id"] == SITE
    assert s["live"]["visitors"] is None
    assert s["live"]["top_pages"] == []
    assert s["live"]["active_sessions"] == []
    assert s["live"]["events"] == []
    assert s["live"]["life_events"] is None


# ─── fromSnapshot ───────────────────────────────────────────────────────────


def test_from_snapshot_fills_missing_categories_from_map() -> None:
    snap = cast(
        LiveStateSnapshot,
        {
            "site_id": SITE,
            "ts": "2026-05-22T13:00:00.000Z",
            "live": {
                "visitors": {"live": 5, "returning": 2},
                "top_pages": [{"url": "https://example.com/", "title": "Home", "count": 5}],
            },
            "max_30d": 127,
            "max_30d_at": "2026-04-15T11:32:00Z",
        },
    )
    state = from_snapshot(snap)
    assert state["live"]["visitors"] == {"live": 5, "returning": 2}
    assert len(state["live"]["top_pages"]) == 1
    assert state["live"]["top_countries"] == []
    assert state["max_30d"] == 127


def test_from_snapshot_handles_array_of_envelopes() -> None:
    """The production server returns `live` as an array of envelopes; the
    SDK accepts it defensively even though `live_state()` normalises at the
    boundary.
    """
    snap = cast(
        LiveStateSnapshot,
        {
            "site_id": SITE,
            "ts": "2026-05-22T13:00:00.000Z",
            "live": [
                {"category": "visitors", "ts": "t", "data": {"live": 3, "returning": 1}},
                {"category": "top_pages", "ts": "t", "data": [{"url": "/a", "title": "A", "count": 2}]},
            ],
            "max_30d": None,
            "max_30d_at": None,
        },
    )
    state = from_snapshot(snap)
    assert state["live"]["visitors"] == {"live": 3, "returning": 1}
    assert state["live"]["top_pages"] == [{"url": "/a", "title": "A", "count": 2}]


# ─── applyEvent — visitors ──────────────────────────────────────────────────


def test_apply_event_visitors_replaces_data() -> None:
    s0 = fresh()
    env: LiveEnvelope = {
        "site_id": SITE,
        "category": "visitors",
        "ts": "2026-05-22T13:00:00.000Z",
        "data": {"live": 7, "returning": 1},
    }
    s1 = apply_event(s0, env)
    assert s1["live"]["visitors"] == {"live": 7, "returning": 1}
    assert s1 is not s0
    assert s1["live"] is not s0["live"]


# ─── applyEvent — top_pages drop semantics ──────────────────────────────────


def test_apply_event_top_pages_upserts_and_removes_by_url() -> None:
    s = fresh()
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "top_pages",
            "ts": "t1",
            "data": [
                {"url": "https://example.com/a", "title": "A", "count": 3},
                {"url": "https://example.com/b", "title": "B", "count": 2},
            ],
        },
    )
    assert len(s["live"]["top_pages"]) == 2
    assert s["live"]["top_pages"][0]["url"] == "https://example.com/a"

    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "top_pages",
            "ts": "t2",
            "data": [
                {"url": "https://example.com/a", "title": "A", "count": 0},  # drop
                {"url": "https://example.com/c", "title": "C", "count": 5},  # insert
            ],
        },
    )
    assert [p["url"] for p in s["live"]["top_pages"]] == [
        "https://example.com/c",
        "https://example.com/b",
    ]


# ─── applyEvent — mixed live + drop in same delta ──────────────────────────


def test_apply_event_processes_mixed_live_and_drop() -> None:
    s = fresh()
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "top_countries",
            "ts": "t1",
            "data": [
                {"country": "US", "count": 5},
                {"country": "DE", "count": 3},
                {"country": "IT", "count": 1},
            ],
        },
    )
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "top_countries",
            "ts": "t2",
            "data": [
                {"country": "IT", "count": 0},  # drop
                {"country": "US", "count": 6},  # upsert
                {"country": "FR", "count": 2},  # insert
            ],
        },
    )
    assert [r["country"] for r in s["live"]["top_countries"]] == ["US", "DE", "FR"]


# ─── applyEvent — active_sessions ─────────────────────────────────────────


def test_apply_event_active_sessions_drop_by_step_count_zero() -> None:
    s = fresh()
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "active_sessions",
            "ts": "t1",
            "data": [
                {
                    "session_id": "abc",
                    "current_page": "/x",
                    "entry_url": "/x",
                    "country": "CH",
                    "device": "desktop",
                    "browser": "Chrome",
                    "os": "Linux",
                    "source": "organic",
                    "step_count": 3,
                    "last_activity": "t1",
                }
            ],
        },
    )
    assert len(s["live"]["active_sessions"]) == 1

    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "active_sessions",
            "ts": "t2",
            "data": [
                {
                    "session_id": "abc",
                    "current_page": None,
                    "entry_url": None,
                    "country": None,
                    "device": None,
                    "browser": None,
                    "os": None,
                    "source": None,
                    "step_count": 0,
                    "last_activity": None,
                }
            ],
        },
    )
    assert len(s["live"]["active_sessions"]) == 0


# ─── applyEvent — geo composite key ────────────────────────────────────────


def test_apply_event_geo_keys_on_lat_lng() -> None:
    s = fresh()
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "geo",
            "ts": "t1",
            "data": [
                {"lat": 45.1, "lng": 10.3, "count": 2},
                {"lat": 43.4, "lng": 11.4, "count": 1},
            ],
        },
    )
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "geo",
            "ts": "t2",
            "data": [{"lat": 45.1, "lng": 10.3, "count": 0}],
        },
    )
    assert len(s["live"]["geo"]) == 1
    assert s["live"]["geo"][0]["lat"] == 43.4


# ─── applyEvent — ephemeral categories ──────────────────────────────────────


def test_apply_event_life_events_replaces_outright() -> None:
    s = fresh()
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "life_events",
            "ts": "t1",
            "data": {"arrived": 3, "navigated": 0, "departed": 0, "ts": "t1"},
        },
    )
    assert s["live"]["life_events"] == {
        "arrived": 3,
        "navigated": 0,
        "departed": 0,
        "ts": "t1",
    }
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "life_events",
            "ts": "t2",
            "data": {"arrived": 0, "navigated": 1, "departed": 2, "ts": "t2"},
        },
    )
    le = s["live"]["life_events"]
    assert le is not None
    assert le["arrived"] == 0
    assert le["navigated"] == 1


def test_apply_event_events_replaces_outright() -> None:
    s = fresh()
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "events",
            "ts": "t1",
            "data": [
                {
                    "category": "Purchase",
                    "action": "Completed",
                    "label": "pro",
                    "count": 1,
                    "value": 99,
                    "time": "2026-05-22T18:55:56Z",
                }
            ],
        },
    )
    assert len(s["live"]["events"]) == 1
    assert s["live"]["events"][0]["time"] == "2026-05-22T18:55:56Z"
    s = apply_event(
        s,
        {"site_id": SITE, "category": "events", "ts": "t2", "data": []},
    )
    assert len(s["live"]["events"]) == 0


# ─── applyEvent — reference stability ──────────────────────────────────────


def test_apply_event_produces_new_state_object() -> None:
    s0 = fresh()
    s1 = apply_event(
        s0,
        {
            "site_id": SITE,
            "category": "visitors",
            "ts": "t1",
            "data": {"live": 1, "returning": 0},
        },
    )
    assert s1 is not s0
    assert s1["live"] is not s0["live"]


def test_apply_event_reuses_untouched_sub_objects() -> None:
    s = fresh()
    s = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "top_pages",
            "ts": "t1",
            "data": [{"url": "https://x.com/", "title": None, "count": 1}],
        },
    )
    top_pages_ref = s["live"]["top_pages"]
    s2 = apply_event(
        s,
        {
            "site_id": SITE,
            "category": "visitors",
            "ts": "t2",
            "data": {"live": 1, "returning": 0},
        },
    )
    assert s2["live"]["top_pages"] is top_pages_ref
