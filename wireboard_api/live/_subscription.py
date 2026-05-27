"""Async SSE subscription engine.

Handles:
    - JWT minting via a customer-supplied ``AsyncMinter`` protocol.
    - SSE connection via :mod:`httpx_sse`.
    - Pattern B zero-gap JWT rotation: open new connection while old still
      streams, close old one after a 1-second overlap once new emits its
      first ``open``.
    - ``lastEventId`` dedup across rotation, bounded to 4096 ids.
    - Hard reconnect on connection death with optional snapshot-refetch hook
      (used by the managed Live client).
    - Lifecycle: ``idle`` → ``connecting`` → ``open`` ↔ ``connecting`` (on
      reconnect) → ``closed``.

Used by both :class:`LiveRawClient` and :class:`LiveClient`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import urllib.parse
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx
from httpx_sse import aconnect_sse

from ..constants import LiveCategory
from ..errors import WireBoardApiError, WireBoardAuthError
from ..types import LiveClientStatus, LiveEnvelope, LiveStateSnapshot, LiveTokenResult

ROTATION_LEAD_SECONDS = 60
OVERLAP_SECONDS = 1.0
HARD_RECONNECT_BACKOFF_SECONDS = 0.5
ROTATION_RETRY_SECONDS = 5.0
ROTATION_MAX_RETRIES = 1
RECENT_IDS_LIMIT = 4096

# Hosts on which a non-TLS hub_url is acceptable (local dev stubs, test
# servers). Production hubs returned by the API must be https — otherwise
# the bearer JWT we attach to the SSE handshake would travel in cleartext.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class AsyncMinter(Protocol):
    """Narrow interface the subscription uses to mint JWTs and fetch
    snapshots. Implemented by :class:`AsyncWireBoardClient`.
    """

    async def live_token(
        self,
        *,
        sites: list[str] | None = ...,
        categories: list[LiveCategory] | None = ...,
    ) -> LiveTokenResult: ...

    async def live_state(
        self,
        *,
        site_id: str,
        categories: list[LiveCategory] | None = ...,
    ) -> LiveStateSnapshot: ...


@dataclass
class SubscriptionOptions:
    sites: list[str]
    categories: list[LiveCategory]
    on_event: Callable[[LiveEnvelope], None]
    on_error: Callable[[Exception], None] | None
    on_rotate: Callable[[], None] | None
    on_reconnect: Callable[[], None] | None
    before_hard_reconnect: Callable[[], Awaitable[None]] | None


def _build_stream_url(token: LiveTokenResult) -> str:
    base = token["hub_url"]
    parts = urllib.parse.urlsplit(base)
    # Reject non-TLS hubs in production. The JWT is carried in the
    # ``Authorization`` header (see ``_run_connection``), so a plaintext
    # hop would expose it to anyone on the wire. Loopback hubs are allowed
    # for local stubs / dev runs.
    if parts.scheme != "https" and (parts.hostname or "") not in _LOOPBACK_HOSTS:
        raise _BadStreamResponseError(
            f"Live hub URL must be https (got scheme {parts.scheme!r})"
        )
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    for topic in token["topics"]:
        query.append(("topic", topic))
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit(parts._replace(query=new_query))


class Subscription:
    """Async SSE subscription engine. One instance per ``LiveClient`` /
    ``LiveRawClient``.

    The owner is expected to ``start()`` once and ``stop()`` once. Calling
    ``start()`` again after ``stop()`` is a fresh restart (full mint + open).
    """

    def __init__(
        self,
        minter: AsyncMinter,
        opts: SubscriptionOptions,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._minter = minter
        self._opts = opts
        self._owns_http = http_client is None
        # SSE connection benefits from no read timeout. Customers can supply
        # their own client to override this.
        self._http: httpx.AsyncClient = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
        )

        self.status: LiveClientStatus = "idle"
        self._current_task: asyncio.Task[None] | None = None
        self._rotation_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        # asyncio holds only weak refs to bare `create_task()` results;
        # stash deferred-close tasks here to keep them alive until they
        # finish, otherwise GC mid-sleep could drop them and leave the
        # old connection open.
        self._pending_closers: set[asyncio.Task[None]] = set()

        self._start_future: asyncio.Future[None] | None = None
        self._start_settled = False
        self._has_opened_before = False
        self._generation = 0
        self._seen_ids: OrderedDict[str, bool] = OrderedDict()
        self._rotation_retries = 0
        self._stopped = False

    def _is_closed(self) -> bool:
        """Closed predicate used in place of ``self.status == 'closed'``.

        A method call breaks mypy's overly-aggressive literal narrowing —
        the status attribute mutates across await points, so static
        narrowing from earlier branches is unsound.
        """
        return self.status == "closed"

    # ─── Public API ────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.status == "open":
            return
        if self.status == "connecting" and self._start_future is not None:
            await self._start_future
            return

        self._generation += 1
        self.status = "connecting"
        self._stopped = False
        self._start_settled = False
        # We're inside an `async def`, so we're guaranteed a running loop.
        # `get_event_loop()` emits DeprecationWarning in 3.12+ and is slated
        # for removal; `get_running_loop()` is the supported call.
        loop = asyncio.get_running_loop()
        self._start_future = loop.create_future()

        try:
            await self._mint_and_open(is_rotation=False)
        except Exception as err:
            self._reject_start(err)
            self.status = "closed"
            raise

        # `_start_future` is resolved by `_on_open` when the SSE connection
        # successfully fires its first open event.
        await self._start_future

    async def stop(self) -> None:
        if self._is_closed():
            return
        self._generation += 1
        was_pending = self.status == "connecting"
        self.status = "closed"
        self._stopped = True

        self._cancel_task("_rotation_task")
        self._cancel_task("_reconnect_task")
        self._cancel_task("_current_task")
        self._current_task = None
        # Cancel any pending overlap-closers so they don't try to cancel
        # already-gone tasks after a fresh restart.
        for closer in list(self._pending_closers):
            if not closer.done():
                closer.cancel()
        self._pending_closers.clear()

        self._has_opened_before = False
        if was_pending:
            self._reject_start(asyncio.CancelledError("subscription stopped"))

        if self._owns_http:
            with contextlib.suppress(Exception):
                await self._http.aclose()

    # ─── Internal: lifecycle ────────────────────────────────────────────────

    def _cancel_task(self, attr: str) -> None:
        task: asyncio.Task[Any] | None = getattr(self, attr, None)
        if task is not None and not task.done():
            task.cancel()
        setattr(self, attr, None)

    def _resolve_start(self) -> None:
        if self._start_settled:
            return
        self._start_settled = True
        if self._start_future is not None and not self._start_future.done():
            self._start_future.set_result(None)

    def _reject_start(self, err: BaseException) -> None:
        if self._start_settled:
            return
        self._start_settled = True
        if self._start_future is not None and not self._start_future.done():
            self._start_future.set_exception(err)

    def _spawn_closer(self, task: asyncio.Task[Any], delay: float) -> None:
        """Schedule ``task`` to be cancelled after ``delay`` seconds. The
        cancellation task is retained on ``self`` so GC can't collect it
        while it's sleeping.
        """
        closer = asyncio.create_task(_close_after(task, delay))
        self._pending_closers.add(closer)
        closer.add_done_callback(self._pending_closers.discard)

    def _emit_error(self, err: BaseException) -> None:
        if self._opts.on_error is None:
            return
        try:
            exc = err if isinstance(err, Exception) else Exception(str(err))
            self._opts.on_error(exc)
        except Exception:
            # Listener errors must not break the subscription.
            pass

    def _safe_call(self, cb: Callable[[], None] | None) -> None:
        if cb is None:
            return
        with contextlib.suppress(Exception):
            cb()

    # ─── Internal: mint + open ─────────────────────────────────────────────

    async def _mint_and_open(self, *, is_rotation: bool) -> None:
        if self._is_closed():
            return
        token = await self._minter.live_token(
            sites=self._opts.sites,
            categories=self._opts.categories,
        )
        if self._is_closed():
            return
        own_gen = self._generation
        task = asyncio.create_task(self._run_connection(token, is_rotation, own_gen))
        if not is_rotation:
            # On a non-rotation open the new task IS the (eventual) current
            # connection. Hold the ref so `stop()` can cancel it cleanly.
            self._cancel_task("_current_task")
            self._current_task = task

    async def _run_connection(
        self,
        token: LiveTokenResult,
        is_rotation: bool,
        own_gen: int,
    ) -> None:
        url = _build_stream_url(token)
        # The JWT is sent in the Authorization header — never in the URL.
        # Query-string credentials end up in proxy logs, error reporters
        # (which often capture request URLs), and any traceback that
        # interpolates the URL.
        headers = {"Authorization": f"Bearer {token['token']}"}
        promoted = False
        own_task = asyncio.current_task()

        try:
            async with aconnect_sse(self._http, "GET", url, headers=headers) as event_source:
                if own_gen != self._generation or self._is_closed():
                    return
                # ``aconnect_sse`` enters the context manager regardless of
                # the HTTP status — a 4xx with a JSON body still gets a
                # response object back. Guard explicitly so we don't promote
                # (and fire ``on_rotate`` / resolve ``start_future``) until
                # we've seen a real 200 + text/event-stream handshake.
                response = event_source.response
                if response.status_code != 200:
                    raise _BadStreamResponseError(
                        f"SSE stream rejected: HTTP {response.status_code}"
                    )
                # Connection is open — promote.
                promoted = True
                self._handle_open(token, is_rotation, own_task)

                async for sse in event_source.aiter_sse():
                    if own_gen != self._generation or self._is_closed():
                        break
                    self._handle_message(sse.id, sse.data)
        except asyncio.CancelledError:
            return
        except Exception as err:
            if own_gen != self._generation or self._is_closed():
                return
            self._emit_error(err)
            self._handle_disconnect(promoted, is_rotation, own_task)
            return

        # Graceful end of iteration (server closed the stream). Treat like a
        # disconnect so we hard-reconnect.
        if own_gen != self._generation or self._is_closed():
            return
        self._handle_disconnect(promoted, is_rotation, own_task)

    # ─── Internal: SSE event handling ───────────────────────────────────────

    def _handle_open(
        self,
        token: LiveTokenResult,
        is_rotation: bool,
        own_task: asyncio.Task[Any] | None,
    ) -> None:
        if self._is_closed():
            return
        self._rotation_retries = 0

        # Promote ourselves to the current connection. If another task held
        # that slot, schedule its close after the overlap window so any
        # in-flight events on the old wire arrive before we drop it. This
        # must run regardless of ``is_rotation`` — under a race where a
        # hard-reconnect's new connection arrives while a pending rotation
        # is also coming up, the second opener would otherwise overwrite
        # `_current_task` without cancelling the loser, leaving an orphan
        # SSE connection open forever.
        old_task = self._current_task
        self._current_task = own_task
        self.status = "open"
        if old_task is not None and old_task is not own_task:
            self._spawn_closer(old_task, OVERLAP_SECONDS)

        if is_rotation:
            self._safe_call(self._opts.on_rotate)
        elif self._has_opened_before:
            self._safe_call(self._opts.on_reconnect)
        else:
            self._resolve_start()
        self._has_opened_before = True

        self._schedule_rotation(token["expires_in"])

    def _handle_message(self, event_id: str | None, raw_data: str) -> None:
        if event_id:
            if event_id in self._seen_ids:
                return
            self._record_seen_id(event_id)

        try:
            payload = json.loads(raw_data)
        except Exception as err:
            self._emit_error(err)
            return

        try:
            self._opts.on_event(cast(LiveEnvelope, payload))
        except Exception as err:
            self._emit_error(err)

    def _handle_disconnect(
        self,
        promoted: bool,
        is_rotation: bool,
        own_task: asyncio.Task[Any] | None,
    ) -> None:
        if self._is_closed():
            return

        if not promoted:
            # Connection never opened.
            if (
                is_rotation
                and self._current_task is not None
                and self._current_task is not own_task
                and not self._current_task.done()
            ):
                # Old connection is still alive — keep using it and retry the
                # rotation. The old JWT will expire on its own if we can't
                # recover before then; at that point the old will error and
                # we'll hard-reconnect.
                self._emit_error(
                    Exception(
                        "JWT rotation failed to open new connection; old still active"
                    )
                )
                self._schedule_rotation_retry()
                return
            # Initial connect or rotation with no fallback.
            self._hard_reconnect()
            return

        if self._current_task is not None and self._current_task is not own_task:
            # A successor has replaced this task. Let this one die quietly.
            return

        # The current connection died.
        self._hard_reconnect()

    def _record_seen_id(self, event_id: str) -> None:
        self._seen_ids[event_id] = True
        while len(self._seen_ids) > RECENT_IDS_LIMIT:
            self._seen_ids.popitem(last=False)

    # ─── Internal: rotation ────────────────────────────────────────────────

    def _schedule_rotation(self, expires_in_seconds: int) -> None:
        self._cancel_task("_rotation_task")
        lead = max(0.0, float(expires_in_seconds) - ROTATION_LEAD_SECONDS)
        self._rotation_task = asyncio.create_task(self._rotation_after(lead))

    async def _rotation_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._is_closed():
            return
        try:
            await self._mint_and_open(is_rotation=True)
        except Exception as err:
            self._emit_error(err)
            if self._is_closed():
                return
            if self._current_task is not None and not self._current_task.done():
                self._schedule_rotation_retry()
            else:
                self._hard_reconnect()

    def _schedule_rotation_retry(self) -> None:
        if self._is_closed():
            return
        if self._rotation_retries >= ROTATION_MAX_RETRIES:
            self._hard_reconnect()
            return
        self._rotation_retries += 1
        self._cancel_task("_rotation_task")
        self._rotation_task = asyncio.create_task(
            self._rotation_after(ROTATION_RETRY_SECONDS)
        )

    # ─── Internal: hard reconnect ──────────────────────────────────────────

    def _hard_reconnect(self) -> None:
        if self._is_closed():
            return
        self._cancel_task("_rotation_task")
        self._cancel_task("_current_task")
        self._current_task = None
        self.status = "connecting"
        self._cancel_task("_reconnect_task")
        self._reconnect_task = asyncio.create_task(self._do_hard_reconnect())

    async def _do_hard_reconnect(self) -> None:
        try:
            await asyncio.sleep(HARD_RECONNECT_BACKOFF_SECONDS)
        except asyncio.CancelledError:
            return
        if self._is_closed():
            return
        try:
            if self._opts.before_hard_reconnect is not None:
                await self._opts.before_hard_reconnect()
            if self._is_closed():
                return
            await self._mint_and_open(is_rotation=False)
        except asyncio.CancelledError:
            return
        except (WireBoardApiError, WireBoardAuthError, Exception) as err:
            self._emit_error(err)
            self.status = "closed"
            self._reject_start(err)


class _BadStreamResponseError(Exception):
    """Raised when ``/v1/live/stream`` returns a non-200 status. Treated
    as a connection failure by the engine; the existing failure paths
    (``_handle_disconnect`` rotation-retry vs. hard-reconnect) apply.
    """


async def _close_after(task: asyncio.Task[Any], delay: float) -> None:
    """Cancel ``task`` after ``delay`` seconds, swallowing any errors."""
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    if not task.done():
        task.cancel()
