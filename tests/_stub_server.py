"""A minimal stub HTTP server for Live SSE integration tests.

Serves three endpoints on a localhost port:
    - ``/v1/live/token``  — returns a JWT envelope pointing at our /stream
    - ``/v1/live/state``  — returns a configurable snapshot
    - ``/v1/live/stream`` — streams a configurable script of SSE events

Each instance owns its own scripted state. The test fixture creates one
server per test to keep state isolated.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class StubScript:
    snapshot: dict[str, Any] = field(
        default_factory=lambda: {
            "site_id": "site-1",
            "ts": "2026-01-01T00:00:00Z",
            "live": {},
            "max_30d": None,
            "max_30d_at": None,
        }
    )
    expires_in: int = 900
    # Sequence of (delay_seconds, raw_data_string, optional_event_id).
    events: list[tuple[float, str, str | None]] = field(default_factory=list)
    # Hold the stream open after sending all events for this many seconds
    # (so the client doesn't see an immediate EOF and reconnect).
    hold_seconds: float = 60.0
    # Number of /stream connections served (test-readable).
    stream_connections: int = 0
    # Number of /v1/live/token requests served.
    token_mints: int = 0


def envelope(data: Any) -> bytes:
    return json.dumps({"status": True, "data": data}).encode()


class _StubHandler(BaseHTTPRequestHandler):
    script: StubScript  # injected via subclass

    def log_message(self, *args: Any) -> None:  # silence default stderr log
        return

    def _send_json(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-RateLimit-Limit", "120")
        self.send_header("X-RateLimit-Remaining", "119")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — stdlib API
        path = self.path.split("?", 1)[0]
        if path == "/v1/live/token":
            self.script.token_mints += 1
            host = self.headers.get("Host", "127.0.0.1")
            body = envelope(
                {
                    "hub_url": f"http://{host}/v1/live/stream",
                    "token": "stub-jwt-token",
                    "topics": ["topic-1"],
                    "sites": ["site-1"],
                    "categories": ["visitors", "top_pages"],
                    "expires_in": self.script.expires_in,
                }
            )
            self._send_json(body)
            return
        if path == "/v1/live/state":
            self._send_json(envelope(self.script.snapshot))
            return
        if path == "/v1/live/stream":
            self._handle_stream()
            return
        self._send_json(b'{"status":false,"errors":[{"text":"not found"}]}', status=404)

    def _handle_stream(self) -> None:
        self.script.stream_connections += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            for delay, data, event_id in self.script.events:
                if delay > 0:
                    time.sleep(delay)
                payload = ""
                if event_id is not None:
                    payload += f"id: {event_id}\n"
                payload += f"data: {data}\n\n"
                try:
                    self.wfile.write(payload.encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
            # Hold the connection open so the client doesn't see EOF and
            # trigger a hard-reconnect during the test's observation window.
            deadline = time.monotonic() + self.script.hold_seconds
            while time.monotonic() < deadline:
                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                time.sleep(0.5)
        except Exception:
            return


class StubServer:
    """One HTTP server bound to a free localhost port. Use as a context
    manager; the server runs on a background thread for the duration.
    """

    def __init__(self, script: StubScript) -> None:
        self.script = script
        handler_cls = type("BoundHandler", (_StubHandler,), {"script": script})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> StubServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
