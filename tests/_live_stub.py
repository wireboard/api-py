"""Rich runtime-controllable stub server for Live-SSE integration tests.

Mirrors the JS reference SDK's ``tests/_stub/sse-server.ts``. Each open
``/v1/live/stream`` is tracked as a ``Connection`` with an ``open`` flag and
a writer lock; tests can call :meth:`LiveStubServer.send_all`, ``.kill_all()``,
or ``.fail_next_stream = True`` to drive specific rotation / hard-reconnect /
dedup scenarios.

The simpler :mod:`_stub_server` is kept for the existing scripted-event
tests that don't need this level of control.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


@dataclass
class Connection:
    id: int
    topics: list[str]
    authorization: str
    handler: Any  # the BaseHTTPRequestHandler instance
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    open: bool = True


class LiveStubServer:
    """In-process HTTP server with mintable JWTs, mutable snapshot, and
    per-connection SSE control. Use as a context manager.
    """

    def __init__(self) -> None:
        # The handler reads these via the shared instance bound below.
        self.connections: list[Connection] = []
        self.snapshot: dict[str, Any] = {
            "live": {},
            "max_30d": None,
            "max_30d_at": None,
        }
        self.token_expires_in: int = 900
        self.fail_next_stream: bool = False
        self._token_count = 0
        self._snapshot_count = 0
        self._next_conn_id = 1
        self._next_token_id = 1
        self._lock = threading.Lock()

        handler_cls = type("BoundHandler", (_LiveStubHandler,), {"stub": self})
        # Bind to a random free port.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="live-stub-server",
            daemon=True,
        )

    # ─── lifecycle ─────────────────────────────────────────────────────────

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> LiveStubServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self.kill_all()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    # ─── inspection ────────────────────────────────────────────────────────

    def token_count(self) -> int:
        with self._lock:
            return self._token_count

    def snapshot_count(self) -> int:
        with self._lock:
            return self._snapshot_count

    def open_connections(self) -> list[Connection]:
        with self._lock:
            return [c for c in self.connections if c.open]

    def wait_for_connections(self, n: int, timeout: float = 3.0) -> None:
        """Block until at least ``n`` connections are simultaneously open."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.open_connections()) >= n:
                return
            time.sleep(0.02)
        raise TimeoutError(
            f"timeout: have {len(self.open_connections())} open connections, want {n}"
        )

    # ─── driving the stream ────────────────────────────────────────────────

    def send_all(self, envelope: dict[str, Any], event_id: str | None = None) -> None:
        """Write one SSE data event to every currently-open connection."""
        line = ""
        if event_id is not None:
            line += f"id: {event_id}\n"
        line += f"data: {json.dumps(envelope)}\n\n"
        encoded = line.encode("utf-8")
        for c in self.open_connections():
            with c.write_lock:
                if not c.open:
                    continue
                try:
                    c.handler.wfile.write(encoded)
                    c.handler.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
                    c.open = False

    def kill_all(self) -> None:
        """Forcibly close every currently-open connection."""
        for c in self.open_connections():
            with c.write_lock:
                c.open = False
                # Best-effort tear-down: handler/socket may already be dead.
                with contextlib.suppress(Exception):
                    c.handler.wfile.close()
                with contextlib.suppress(Exception):
                    c.handler.connection.close()

    # ─── used by the handler ───────────────────────────────────────────────

    def _alloc_conn(self, handler: Any, topics: list[str], authorization: str) -> Connection:
        with self._lock:
            cid = self._next_conn_id
            self._next_conn_id += 1
            conn = Connection(
                id=cid,
                topics=topics,
                authorization=authorization,
                handler=handler,
            )
            self.connections.append(conn)
            return conn

    def _bump_token(self) -> int:
        with self._lock:
            self._token_count += 1
            self._next_token_id += 1
            return self._next_token_id

    def _bump_snapshot(self) -> None:
        with self._lock:
            self._snapshot_count += 1


class _LiveStubHandler(BaseHTTPRequestHandler):
    stub: LiveStubServer  # injected via subclass

    def log_message(self, *args: Any) -> None:
        return

    def _send_json(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — stdlib API
        parts = urlparse(self.path)
        path = parts.path
        query = parse_qs(parts.query, keep_blank_values=True)
        auth = self.headers.get("Authorization", "")

        if path == "/v1/live/token":
            self.stub._bump_token()
            if not auth.startswith("Bearer "):
                self._send_json(b'{"message":"Unauthenticated."}', status=401)
                return
            sites = query.get("sites", ["xK4mP2nT"])[0].split(",")
            categories = query.get("categories", [""])[0].split(",")
            categories = [c for c in categories if c]
            host = self.headers.get("Host", "127.0.0.1")
            hub = f"http://{host}/v1/live/stream"
            topics = [
                f"https://wireboard.io/sites/{s}/live/{c}"
                for s in sites
                for c in categories
            ]
            body = json.dumps(
                {
                    "status": True,
                    "data": {
                        "hub_url": hub,
                        "token": f"jwt-{self.stub._next_token_id}",
                        "topics": topics,
                        "sites": sites,
                        "categories": categories,
                        "expires_in": self.stub.token_expires_in,
                    },
                }
            ).encode()
            self._send_json(body)
            return

        if path == "/v1/live/state":
            self.stub._bump_snapshot()
            if not auth.startswith("Bearer "):
                self._send_json(b'{"message":"Unauthenticated."}', status=401)
                return
            site_id = query.get("site_id", ["xK4mP2nT"])[0]
            ts = "2026-01-01T00:00:00.000Z"
            # Mirror the production server: `live` is an array of envelopes,
            # not a map. The SDK normalises this at the client boundary.
            live_array = [
                {"category": cat, "ts": ts, "data": data}
                for cat, data in self.stub.snapshot["live"].items()
            ]
            body = json.dumps(
                {
                    "status": True,
                    "data": {
                        "site_id": site_id,
                        "ts": ts,
                        "live": live_array,
                        "max_30d": self.stub.snapshot["max_30d"],
                        "max_30d_at": self.stub.snapshot["max_30d_at"],
                    },
                }
            ).encode()
            self._send_json(body)
            return

        if path == "/v1/live/stream":
            if self.stub.fail_next_stream:
                self.stub.fail_next_stream = False
                self._send_json(
                    b'{"status":false,"errors":[{"text":"simulated failure"}]}',
                    status=404,
                )
                return
            topics = query.get("topic", [])
            # The SDK sends the JWT in the Authorization header (not the
            # URL); fall back to the legacy query-string form for any future
            # test that wants to assert the old behavior is gone.
            authorization = (
                auth[len("Bearer ") :] if auth.startswith("Bearer ")
                else query.get("authorization", [""])[0]
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            conn = self.stub._alloc_conn(self, topics, authorization)
            # Hold the request thread here while the connection is open so
            # the handler doesn't return (which would close the socket).
            # Tests drive writes via stub.send_all() and tear down via
            # kill_all().
            while conn.open:
                time.sleep(0.05)
            return

        self._send_json(
            b'{"status":false,"errors":[{"text":"route not found"}],'
            b'"fieldErrors":{"error_code":["route_not_found"]}}',
            status=404,
        )
