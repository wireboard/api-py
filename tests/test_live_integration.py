"""End-to-end integration tests for the Live clients against a local stub
SSE server.

These tests don't use ``pytest-httpx`` — they run a real HTTP server in a
background thread and let the SDK make real HTTP and SSE connections. This
exercises the streaming path (which is hard to mock at the httpx layer).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import pytest

from wireboard_api import AsyncWireBoardClient, LiveEnvelope, ManagedLiveState, WireBoardClient

from ._stub_server import StubScript, StubServer

# ─── helpers ────────────────────────────────────────────────────────────────


def _wait_until(predicate: Any, timeout: float = 5.0, interval: float = 0.05) -> bool:
    """Spin until ``predicate()`` is truthy or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _make_script(events: list[dict[str, Any]]) -> StubScript:
    """Schedule a list of envelope dicts as SSE events with no delay between
    them.
    """
    return StubScript(
        snapshot={
            "site_id": "site-1",
            "ts": "2026-01-01T00:00:00Z",
            "live": {},
            "max_30d": None,
            "max_30d_at": None,
        },
        events=[(0.0, json.dumps(env), None) for env in events],
    )


# ─── sync managed Live ──────────────────────────────────────────────────────


def test_managed_live_snapshot_then_event_merges_into_state() -> None:
    script = StubScript(
        snapshot={
            "site_id": "site-1",
            "ts": "2026-01-01T00:00:00Z",
            "live": {"visitors": {"live": 3, "returning": 1}},
            "max_30d": 50,
            "max_30d_at": "2026-01-01T00:00:00Z",
        },
        events=[
            (
                0.0,
                json.dumps(
                    {
                        "site_id": "site-1",
                        "category": "top_pages",
                        "ts": "2026-01-01T00:00:01Z",
                        "data": [
                            {"url": "/home", "title": "Home", "count": 4},
                            {"url": "/about", "title": "About", "count": 1},
                        ],
                    }
                ),
                "1",
            )
        ],
    )
    states: list[ManagedLiveState] = []

    with StubServer(script) as server:
        wb = WireBoardClient(token="t", base_url=server.base_url)
        live = wb.live(
            site_id="site-1",
            categories=["visitors", "top_pages"],
            on_change=states.append,
        )
        try:
            live.start()
            assert _wait_until(lambda: len(states) >= 2), f"only got {len(states)} state(s)"

            # Final state: snapshot's visitors merged with the streamed
            # top_pages event.
            final = live.state
            assert final["live"]["visitors"] == {"live": 3, "returning": 1}
            urls = [p["url"] for p in final["live"]["top_pages"]]
            assert urls == ["/home", "/about"]  # sorted by count desc
            assert final["max_30d"] == 50
        finally:
            live.stop()
            wb.close()


def test_managed_live_top_n_drop_removes_entry() -> None:
    script = _make_script(
        [
            {
                "site_id": "site-1",
                "category": "top_pages",
                "ts": "t1",
                "data": [
                    {"url": "/a", "title": "A", "count": 3},
                    {"url": "/b", "title": "B", "count": 2},
                ],
            },
            {
                "site_id": "site-1",
                "category": "top_pages",
                "ts": "t2",
                "data": [{"url": "/a", "title": "A", "count": 0}],
            },
        ]
    )

    with StubServer(script) as server:
        wb = WireBoardClient(token="t", base_url=server.base_url)
        live = wb.live(site_id="site-1", categories=["top_pages"])
        try:
            live.start()
            assert _wait_until(
                lambda: [p["url"] for p in live.state["live"]["top_pages"]] == ["/b"],
                timeout=3.0,
            ), f"top_pages = {live.state['live']['top_pages']}"
        finally:
            live.stop()
            wb.close()


def test_managed_live_stop_is_idempotent() -> None:
    script = _make_script([])
    with StubServer(script) as server:
        wb = WireBoardClient(token="t", base_url=server.base_url)
        live = wb.live(site_id="site-1", categories=["visitors"])
        try:
            live.start()
            live.stop()
            live.stop()  # second call must not raise
        finally:
            wb.close()


def test_managed_live_context_manager() -> None:
    script = _make_script([])
    with StubServer(script) as server:
        wb = WireBoardClient(token="t", base_url=server.base_url)
        live = wb.live(site_id="site-1", categories=["visitors"])
        with live:
            assert live.status == "open"
        assert live.status == "closed"
        wb.close()


# ─── raw mode multi-site ────────────────────────────────────────────────────


def test_raw_live_routes_envelopes_with_site_id() -> None:
    script = _make_script(
        [
            {
                "site_id": "site-1",
                "category": "visitors",
                "ts": "t1",
                "data": {"live": 1, "returning": 0},
            },
            {
                "site_id": "site-2",
                "category": "visitors",
                "ts": "t2",
                "data": {"live": 5, "returning": 2},
            },
        ]
    )
    seen: list[LiveEnvelope] = []
    done = threading.Event()

    def on_event(env: LiveEnvelope) -> None:
        seen.append(env)
        if len(seen) >= 2:
            done.set()

    with StubServer(script) as server:
        wb = WireBoardClient(token="t", base_url=server.base_url)
        raw = wb.live_raw(sites=["site-1", "site-2"], on_event=on_event)
        try:
            raw.start()
            assert done.wait(timeout=3.0), f"only got {len(seen)} event(s)"
            sites = sorted(e["site_id"] for e in seen)
            assert sites == ["site-1", "site-2"]
        finally:
            raw.stop()
            wb.close()


# ─── async managed Live ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_managed_live_basic_flow() -> None:
    script = _make_script(
        [
            {
                "site_id": "site-1",
                "category": "visitors",
                "ts": "t1",
                "data": {"live": 9, "returning": 4},
            }
        ]
    )
    states: list[ManagedLiveState] = []
    with StubServer(script) as server:
        async with AsyncWireBoardClient(token="t", base_url=server.base_url) as wb:
            live = wb.live(
                site_id="site-1",
                categories=["visitors"],
                on_change=states.append,
            )
            await live.start()
            # Wait for the stream event to be delivered.
            for _ in range(50):
                if any(s["live"]["visitors"] == {"live": 9, "returning": 4} for s in states):
                    break
                await asyncio.sleep(0.05)
            await live.stop()
    final_visitors = [s["live"]["visitors"] for s in states]
    assert {"live": 9, "returning": 4} in final_visitors


# ─── token + snapshot are called ────────────────────────────────────────────


def test_managed_live_mints_token_and_fetches_snapshot() -> None:
    script = _make_script([])
    with StubServer(script) as server:
        wb = WireBoardClient(token="t", base_url=server.base_url)
        live = wb.live(site_id="site-1", categories=["visitors"])
        try:
            live.start()
            assert script.token_mints >= 1
            assert script.stream_connections >= 1
        finally:
            live.stop()
            wb.close()
