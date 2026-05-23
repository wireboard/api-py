#!/usr/bin/env python3
"""Local Flask example server.

Spins up a small Flask app that wraps the installed ``wireboard_api`` SDK and
serves four browser pages so you can click through and visually verify the SDK
against your real account. Mirrors the JS SDK's ``scripts/test-examples.sh``
flow, adapted to the right architecture for Python:

    Browser  ──HTTP/JSON──▶  Flask (this script)  ──SDK──▶  api.wireboard.io

The bearer token never leaves the server. For Live data, the script keeps a
background managed/raw client per site and exposes its current state as JSON;
the browser polls every 1.5 s.

Run:
    pip install -e ".[examples]"
    WIREBOARD_TOKEN=… python scripts/serve_examples.py
        # or use scripts/serve-examples.sh for env-var + free-port handling
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import socket
import sys
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from flask import Flask, Response, abort, jsonify, request, send_from_directory
except ImportError:
    sys.stderr.write(
        "error: flask is not installed.\n"
        "       Run:  pip install -e \".[examples]\"\n"
    )
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]

from wireboard_api import (
    LiveCategory,
    LiveEnvelope,
    ManagedLiveState,
    WireBoardApiError,
    WireBoardAuthError,
    WireBoardClient,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
PORT_RANGE = range(8080, 8090)
LIVE_CATEGORIES_MANAGED: list[LiveCategory] = [
    "visitors",
    "top_pages",
    "top_countries",
    "active_sessions",
]
LIVE_CATEGORIES_RAW: list[LiveCategory] = [
    "visitors",
    "top_pages",
    "top_countries",
    "top_referrers",
    "active_sessions",
    "life_events",
]

#: How long to block waiting for a queued event before sending an SSE keepalive
#: comment. Must be < any front-proxy idle timeout; 15s is conservative.
SSE_KEEPALIVE_SECONDS = 15.0


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / ".env")


def _find_free_port(preferred: int | None) -> int:
    candidates: list[int] = []
    if preferred is not None:
        candidates.append(preferred)
    candidates.extend(p for p in PORT_RANGE if p != preferred)
    for p in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
                continue
            return p
    raise RuntimeError(f"no free port in {PORT_RANGE.start}–{PORT_RANGE.stop - 1}")


def _err_payload(err: BaseException) -> tuple[dict[str, Any], int]:
    if isinstance(err, WireBoardApiError):
        return (
            {
                "error": str(err),
                "code": err.code,
                "field_errors": err.field_errors,
                "rate_limit": err.rate_limit,
                "http_status": err.http_status,
            },
            err.http_status,
        )
    if isinstance(err, WireBoardAuthError):
        return ({"error": str(err), "http_status": err.http_status}, err.http_status)
    return ({"error": f"{type(err).__name__}: {err}"}, 500)


# ─── SSE helpers ────────────────────────────────────────────────────────────


def _sse_payload(data: Any, event: str | None = None) -> str:
    """Format an SSE message. ``data`` is JSON-serialised."""
    body = json.dumps(data, separators=(",", ":"))
    if event:
        return f"event: {event}\ndata: {body}\n\n"
    return f"data: {body}\n\n"


def _coalesce_put(q: queue.Queue[Any], item: Any) -> None:
    """Put ``item`` on ``q`` with overwrite-newest semantics: if the queue
    is full, drop the stale entry and re-try once. Used for snapshot-latest
    streams where only the most recent value matters.
    """
    try:
        q.put_nowait(item)
    except queue.Full:
        with contextlib.suppress(queue.Empty):
            q.get_nowait()
        with contextlib.suppress(queue.Full):
            q.put_nowait(item)


# ─── Managed Live registry (per site, with SSE fan-out) ─────────────────────


class _ManagedRegistry:
    """One managed ``LiveClient`` per site, started on the first subscriber
    and stopped when the last subscriber disconnects. Each Flask SSE
    handler gets its own queue, fed by the SDK's ``subscribe`` listener.
    """

    def __init__(self, wb: WireBoardClient) -> None:
        self._wb = wb
        self._lock = threading.Lock()
        self._clients: dict[str, Any] = {}
        self._subscribers: dict[str, list[queue.Queue[ManagedLiveState]]] = {}

    def stream(self, site_id: str) -> Iterator[str]:
        client, q, initial = self._subscribe(site_id)
        try:
            yield _sse_payload(initial)
            while True:
                try:
                    state = q.get(timeout=SSE_KEEPALIVE_SECONDS)
                    yield _sse_payload(state)
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            self._unsubscribe(site_id, q)

    def _subscribe(
        self, site_id: str
    ) -> tuple[Any, queue.Queue[ManagedLiveState], ManagedLiveState]:
        new_client = False
        with self._lock:
            client = self._clients.get(site_id)
            if client is None:
                client = self._wb.live(
                    site_id=site_id,
                    categories=LIVE_CATEGORIES_MANAGED,
                )
                self._clients[site_id] = client
                self._subscribers[site_id] = []
                new_client = True
            # Managed state is snapshot-latest: only the newest delivery
            # matters, so use a single-slot queue and drain-and-put on full.
            # This guarantees a slow browser never gets stuck reading a
            # stale snapshot from a backed-up FIFO.
            q: queue.Queue[ManagedLiveState] = queue.Queue(maxsize=1)
            self._subscribers[site_id].append(q)

        # client.start() blocks on snapshot fetch + JWT mint + stream open
        # and synchronously fires on_change from the SDK's worker thread —
        # so we MUST drop self._lock first, otherwise on_change deadlocks
        # against this thread when it tries to acquire the same lock.
        if new_client:
            def on_change(state: ManagedLiveState, sid: str = site_id) -> None:
                with self._lock:
                    subs = list(self._subscribers.get(sid, []))
                for queue_ in subs:
                    _coalesce_put(queue_, state)

            client.subscribe(on_change)
            client.start()

        return client, q, client.state

    def _unsubscribe(
        self, site_id: str, q: queue.Queue[ManagedLiveState]
    ) -> None:
        to_stop: Any = None
        with self._lock:
            subs = self._subscribers.get(site_id, [])
            with contextlib.suppress(ValueError):
                subs.remove(q)
            if not subs and site_id in self._clients:
                to_stop = self._clients.pop(site_id)
                self._subscribers.pop(site_id, None)
        if to_stop is not None:
            with contextlib.suppress(Exception):
                to_stop.stop()

    def stop_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
            self._subscribers.clear()
        for c in clients:
            with contextlib.suppress(Exception):
                c.stop()


# ─── Raw multi-site registry ────────────────────────────────────────────────


class _RawRegistry:
    """One ``LiveRawClient`` per distinct set of sites (keyed by sorted tuple
    of site IDs). Each Flask SSE handler gets a queue of raw envelopes.
    """

    def __init__(self, wb: WireBoardClient) -> None:
        self._wb = wb
        self._lock = threading.Lock()
        self._clients: dict[tuple[str, ...], Any] = {}
        self._subscribers: dict[tuple[str, ...], list[queue.Queue[LiveEnvelope]]] = {}

    def stream(self, sites: list[str]) -> Iterator[str]:
        key = tuple(sorted(sites))
        q = self._subscribe(key, sites)
        try:
            # Tell the browser which sites the server is actually streaming.
            yield _sse_payload({"sites": list(key)}, event="ready")
            while True:
                try:
                    env = q.get(timeout=SSE_KEEPALIVE_SECONDS)
                    yield _sse_payload(env)
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            self._unsubscribe(key, q)

    def _subscribe(
        self, key: tuple[str, ...], sites: list[str]
    ) -> queue.Queue[LiveEnvelope]:
        new_client: Any = None
        with self._lock:
            existing = self._clients.get(key)
            q: queue.Queue[LiveEnvelope] = queue.Queue(maxsize=256)
            if existing is None:
                def on_event(env: LiveEnvelope, k: tuple[str, ...] = key) -> None:
                    with self._lock:
                        subs = list(self._subscribers.get(k, []))
                    for qq in subs:
                        with contextlib.suppress(Exception):
                            qq.put_nowait(env)

                new_client = self._wb.live_raw(
                    sites=sites,
                    categories=LIVE_CATEGORIES_RAW,
                    on_event=on_event,
                )
                self._clients[key] = new_client
                self._subscribers[key] = []
            self._subscribers[key].append(q)

        # start() outside the lock — see comment in _ManagedRegistry._subscribe.
        if new_client is not None:
            new_client.start()
        return q

    def _unsubscribe(
        self, key: tuple[str, ...], q: queue.Queue[LiveEnvelope]
    ) -> None:
        to_stop: Any = None
        with self._lock:
            subs = self._subscribers.get(key, [])
            with contextlib.suppress(ValueError):
                subs.remove(q)
            if not subs and key in self._clients:
                to_stop = self._clients.pop(key)
                self._subscribers.pop(key, None)
        if to_stop is not None:
            with contextlib.suppress(Exception):
                to_stop.stop()

    def stop_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
            self._subscribers.clear()
        for c in clients:
            with contextlib.suppress(Exception):
                c.stop()


# ─── App factory ────────────────────────────────────────────────────────────


def create_app(token: str) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
    wb = WireBoardClient(token=token)
    managed_reg = _ManagedRegistry(wb)
    raw_reg = _RawRegistry(wb)

    @app.errorhandler(WireBoardApiError)
    def _api_err(err: WireBoardApiError) -> Any:
        body, status = _err_payload(err)
        return jsonify(body), status

    @app.errorhandler(WireBoardAuthError)
    def _auth_err(err: WireBoardAuthError) -> Any:
        body, status = _err_payload(err)
        return jsonify(body), status

    # ─── HTML routes ────────────────────────────────────────────────────────

    @app.route("/")
    def index() -> Any:
        return send_from_directory(STATIC_DIR, "index.html")

    @app.route("/<path:page>")
    def page(page: str) -> Any:
        # Serve any HTML file in static/ directly.
        candidate = STATIC_DIR / page
        if candidate.is_file():
            return send_from_directory(STATIC_DIR, page)
        # Try with .html appended for clean URLs.
        candidate_html = STATIC_DIR / f"{page}.html"
        if candidate_html.is_file():
            return send_from_directory(STATIC_DIR, f"{page}.html")
        abort(404)

    # ─── JSON API ───────────────────────────────────────────────────────────

    @app.route("/api/account")
    def api_account() -> Any:
        return jsonify(wb.account())

    @app.route("/api/sites")
    def api_sites() -> Any:
        return jsonify(wb.sites())

    @app.route("/api/aggregate")
    def api_aggregate() -> Any:
        return jsonify(
            wb.aggregate(
                site_id=request.args["site_id"],
                from_=request.args["from"],
                to=request.args["to"],
            )
        )

    @app.route("/api/breakdown")
    def api_breakdown() -> Any:
        return jsonify(
            wb.breakdown(
                site_id=request.args["site_id"],
                from_=request.args["from"],
                to=request.args["to"],
                dimension=request.args["dimension"],  # type: ignore[arg-type]
                limit=int(request.args["limit"]) if "limit" in request.args else None,
            )
        )

    @app.route("/api/history")
    def api_history() -> Any:
        return jsonify(
            wb.history(
                site_id=request.args["site_id"],
                from_=request.args["from"],
                to=request.args["to"],
            )
        )

    def _sse_response(stream: Iterator[str]) -> Response:
        return Response(
            stream,
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable nginx buffering if any
            },
        )

    @app.route("/api/live-stream")
    def api_live_stream() -> Any:
        site_id = request.args.get("site_id")
        if not site_id:
            return jsonify({"error": "missing ?site_id=…"}), 400
        return _sse_response(managed_reg.stream(site_id))

    @app.route("/api/multi-stream")
    def api_multi_stream() -> Any:
        sites_arg = request.args.get("sites", "")
        sites = [s for s in sites_arg.split(",") if s]
        if not sites:
            return jsonify({"error": "missing ?sites=…"}), 400
        return _sse_response(raw_reg.stream(sites))

    @app.route("/api/today")
    def api_today() -> Any:
        """Convenience for the historical page: a 7-day UTC range."""
        today = datetime.now(timezone.utc)
        return jsonify(
            {
                "from": (today - timedelta(days=7)).strftime("%Y-%m-%d"),
                "to": today.strftime("%Y-%m-%d"),
            }
        )

    @app.teardown_appcontext
    def _teardown(_exc: BaseException | None) -> None:
        # Each request: nothing to clean. Process exit handles client shutdown.
        return None

    app.managed_registry = managed_reg  # type: ignore[attr-defined]
    app.raw_registry = raw_reg  # type: ignore[attr-defined]
    app.wb = wb  # type: ignore[attr-defined]
    return app


# ─── CLI entry point ────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    _load_env()

    parser = argparse.ArgumentParser(
        prog="serve_examples.py",
        description="Serve the WireBoard SDK browser examples on localhost.",
    )
    parser.add_argument("--port", type=int, default=None, help="Preferred port (default: first free in 8080–8089)")
    parser.add_argument("--token", default=None, help="Bearer token; falls back to $WIREBOARD_TOKEN")
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("WIREBOARD_TOKEN")
    if not token:
        sys.stderr.write(
            "error: WIREBOARD_TOKEN is not set.\n"
            "       Export it, pass --token, or add it to .env at the repo root.\n"
        )
        return 1

    if not STATIC_DIR.is_dir():
        sys.stderr.write(f"error: static dir missing: {STATIC_DIR}\n")
        return 1

    try:
        port = _find_free_port(args.port)
    except RuntimeError as err:
        sys.stderr.write(f"error: {err}\n")
        return 1

    app = create_app(token)

    pages = sorted(p.name for p in STATIC_DIR.glob("*.html"))
    sys.stdout.write(
        "\n──────────────────────────────────────────────────────────────────\n"
        "✔ Ready.\n\n"
        f"  Open:  http://127.0.0.1:{port}/\n\n"
        "Pages served:\n"
    )
    for name in pages:
        sys.stdout.write(f"    http://127.0.0.1:{port}/{name}\n")
    sys.stdout.write(
        "\nPress Ctrl+C to stop.\n"
        "──────────────────────────────────────────────────────────────────\n\n"
    )
    sys.stdout.flush()

    try:
        # threaded=True so a slow Live request doesn't block the page-load
        # requests. use_reloader=False so the background LiveClient threads
        # aren't re-spawned every save.
        app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False, debug=False)
    except KeyboardInterrupt:
        pass
    finally:
        app.managed_registry.stop_all()  # type: ignore[attr-defined]
        app.raw_registry.stop_all()  # type: ignore[attr-defined]
        app.wb.close()  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    sys.exit(main())
