"""Rotation + hard-reconnect integration tests.

Mirror the JS SDK's ``tests/live-managed.integration.test.ts`` cases for the
parts of the subscription engine that are hardest to verify without a real
runtime: JWT rotation timing, snapshot refetch on hard reconnect,
``on_reconnect`` only firing on hard reconnect, rotation keeping the old
connection alive when the new one fails to open, and ``lastEventId`` dedup
across overlapping connections during rotation.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from wireboard_api import LiveEnvelope, ManagedLiveState, WireBoardClient

from ._live_stub import LiveStubServer

SITE = "xK4mP2nT"


def _wait_until(predicate: Any, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ─── hard reconnect ─────────────────────────────────────────────────────────


def test_hard_reconnect_refetches_snapshot_and_replaces_state() -> None:
    with LiveStubServer() as stub:
        stub.snapshot["live"] = {"visitors": {"live": 5, "returning": 2}}
        wb = WireBoardClient(token="t", base_url=stub.url)
        live = wb.live(site_id=SITE, categories=["visitors"])
        try:
            live.start()
            stub.wait_for_connections(1)
            assert stub.snapshot_count() == 1

            # Server-side state changes; client should re-pull on reconnect.
            stub.snapshot["live"] = {"visitors": {"live": 99, "returning": 11}}
            stub.kill_all()

            # 500ms hard-reconnect backoff + JWT mint + new SSE open.
            assert _wait_until(
                lambda: stub.snapshot_count() >= 2 and len(stub.open_connections()) >= 1,
                timeout=4.0,
            ), f"snapshots={stub.snapshot_count()} open={len(stub.open_connections())}"
            assert _wait_until(
                lambda: (live.state["live"]["visitors"] or {}).get("live") == 99,
                timeout=2.0,
            ), f"state.visitors = {live.state['live']['visitors']}"
        finally:
            live.stop()
            wb.close()


def test_on_reconnect_fires_on_hard_reconnect_but_not_initial() -> None:
    reconnects = [0]
    with LiveStubServer() as stub:
        wb = WireBoardClient(token="t", base_url=stub.url)
        live = wb.live(
            site_id=SITE,
            categories=["visitors"],
            on_reconnect=lambda: reconnects.__setitem__(0, reconnects[0] + 1),
        )
        try:
            live.start()
            stub.wait_for_connections(1)
            # Initial open must NOT count as a reconnect.
            assert reconnects[0] == 0

            stub.kill_all()
            assert _wait_until(
                lambda: reconnects[0] == 1 and len(stub.open_connections()) >= 1,
                timeout=4.0,
            ), f"reconnects={reconnects[0]} open={len(stub.open_connections())}"

            stub.kill_all()
            assert _wait_until(
                lambda: reconnects[0] == 2 and len(stub.open_connections()) >= 1,
                timeout=4.0,
            ), f"reconnects={reconnects[0]} open={len(stub.open_connections())}"
        finally:
            live.stop()
            wb.close()


# ─── rotation ──────────────────────────────────────────────────────────────


@pytest.mark.slow
def test_rotation_keeps_old_connection_alive_when_new_one_fails() -> None:
    """Initial JWT lives 65s → rotation lead clamps to (65-60)=5s. Within
    that window we arm ``fail_next_stream`` so the rotation's new connection
    gets a 404. The SDK must keep the old connection up and surface an error
    rather than tearing everything down.
    """
    errors: list[Exception] = []
    rotate_count = [0]
    with LiveStubServer() as stub:
        stub.token_expires_in = 65
        wb = WireBoardClient(token="t", base_url=stub.url)
        live = wb.live(
            site_id=SITE,
            categories=["visitors"],
            on_error=errors.append,
            on_rotate=lambda: rotate_count.__setitem__(0, rotate_count[0] + 1),
        )
        try:
            live.start()
            stub.wait_for_connections(1)
            initial_conn = stub.open_connections()[0]
            initial_token_count = stub.token_count()

            # Arm: the next /stream request (the rotation) returns 404.
            stub.fail_next_stream = True

            # Wait past the 5s rotation lead.
            time.sleep(6.0)

            assert rotate_count[0] == 0, (
                f"no successful rotation expected; got {rotate_count[0]}"
            )
            assert any("rotation" in str(e).lower() for e in errors), (
                f"expected a rotation error; got {[str(e) for e in errors]}"
            )
            assert initial_conn.open, "old connection must be preserved"
            assert stub.token_count() > initial_token_count, (
                "rotation mint must have happened"
            )
            assert not stub.fail_next_stream, (
                "fail_next_stream should have been consumed"
            )
        finally:
            live.stop()
            wb.close()


def test_rotation_dedups_events_via_last_event_id() -> None:
    """``token_expires_in = 2`` → rotation lead is (2-60) clamped to 0 →
    rotation fires immediately. We let two connections briefly overlap and
    send the same envelope (same ``id``) to both. Customer should see it
    once.
    """
    visitor_seen: list[int] = []

    def on_change(s: ManagedLiveState) -> None:
        v = s["live"]["visitors"]
        if v is not None:
            visitor_seen.append(v["live"])

    with LiveStubServer() as stub:
        stub.token_expires_in = 2  # forces immediate rotation
        wb = WireBoardClient(token="t", base_url=stub.url)
        live = wb.live(
            site_id=SITE,
            categories=["visitors"],
            on_change=on_change,
        )
        try:
            live.start()
            # Give the rotation time to fire and the new connection to
            # come up alongside the old.
            stub.wait_for_connections(2, timeout=3.0)

            stub.send_all(
                {
                    "site_id": SITE,
                    "category": "visitors",
                    "ts": "t1",
                    "data": {"live": 42, "returning": 0},
                },
                event_id="shared-id",
            )
            time.sleep(0.3)

            forty_twos = sum(1 for v in visitor_seen if v == 42)
            assert forty_twos == 1, (
                f"expected exactly one 42 (dedup'd); saw {visitor_seen}"
            )
        finally:
            live.stop()
            wb.close()


# ─── malformed payloads ────────────────────────────────────────────────────


def test_malformed_envelope_reports_error_without_breaking_subscription() -> None:
    errors: list[Exception] = []
    with LiveStubServer() as stub:
        wb = WireBoardClient(token="t", base_url=stub.url)
        live = wb.live(
            site_id=SITE,
            categories=["visitors"],
            on_error=errors.append,
        )
        try:
            live.start()
            stub.wait_for_connections(1)

            # Write a malformed data line directly via the stub's send_all
            # protocol — JSON parse failure should surface via on_error
            # without ending the iteration.
            for c in stub.open_connections():
                with c.write_lock:
                    try:
                        c.handler.wfile.write(b"data: not-json\n\n")
                        c.handler.wfile.flush()
                    except Exception:  # noqa: BLE001
                        pass
            assert _wait_until(lambda: len(errors) >= 1, timeout=2.0)

            # Subscription is still alive: a well-formed envelope merges.
            stub.send_all(
                {
                    "site_id": SITE,
                    "category": "visitors",
                    "ts": "t2",
                    "data": {"live": 3, "returning": 0},
                },
                event_id="after-bad",
            )
            assert _wait_until(
                lambda: (live.state["live"]["visitors"] or {}).get("live") == 3,
                timeout=2.0,
            ), f"state.visitors = {live.state['live']['visitors']}"
        finally:
            live.stop()
            wb.close()


# ─── raw multi-site stays alive across a kill ──────────────────────────────


def test_raw_client_hard_reconnects_after_connection_drop() -> None:
    """Raw mode has no snapshot refetch but should still hard-reconnect."""
    events: list[LiveEnvelope] = []
    with LiveStubServer() as stub:
        wb = WireBoardClient(token="t", base_url=stub.url)
        raw = wb.live_raw(
            sites=[SITE],
            on_event=events.append,
        )
        try:
            raw.start()
            stub.wait_for_connections(1)
            assert stub.token_count() == 1

            stub.kill_all()
            # Expect a fresh JWT mint + new connection.
            assert _wait_until(
                lambda: stub.token_count() >= 2 and len(stub.open_connections()) >= 1,
                timeout=4.0,
            ), f"tokens={stub.token_count()} open={len(stub.open_connections())}"

            stub.send_all(
                {
                    "site_id": SITE,
                    "category": "visitors",
                    "ts": "t1",
                    "data": {"live": 7, "returning": 1},
                },
                event_id="after-reconnect",
            )
            assert _wait_until(lambda: len(events) >= 1, timeout=2.0)
            assert events[-1]["data"] == {"live": 7, "returning": 1}
        finally:
            raw.stop()
            wb.close()
