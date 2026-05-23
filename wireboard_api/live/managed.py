"""Managed Live client (sync). Wraps :class:`AsyncLiveClient` and runs it
on a background asyncio event loop thread.
"""

from __future__ import annotations

from collections.abc import Callable

from ..constants import LiveCategory
from ..types import LiveClientStatus, LiveEnvelope, ManagedLiveState
from ._async_runner import AsyncRunner
from ._subscription import AsyncMinter
from .async_managed import AsyncLiveClient


class LiveClient:
    """Managed Live client. Synchronous facade — internally runs an async
    SSE engine on a dedicated background thread.

    Callbacks (``on_change``, ``on_event``, ``on_error``, ``on_rotate``,
    ``on_reconnect``) fire on the background thread; use threading primitives
    if you need cross-thread coordination.

    Lifecycle: construct → ``start()`` (blocks until snapshot loaded + stream
    open) → ... → ``stop()`` (blocks until closed). Safe to use as a context
    manager.

    Example::

        live = wb.live(site_id=site.id, categories=["visitors", "top_pages"])
        live.subscribe(lambda s: print("now:", s["live"]["visitors"]))
        live.start()
        try:
            time.sleep(60)
        finally:
            live.stop()
    """

    def __init__(
        self,
        minter: AsyncMinter,
        *,
        site_id: str,
        categories: list[LiveCategory] | None = None,
        on_change: Callable[[ManagedLiveState], None] | None = None,
        on_event: Callable[[LiveEnvelope], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_rotate: Callable[[], None] | None = None,
        on_reconnect: Callable[[], None] | None = None,
        owned_minter: object | None = None,
    ) -> None:
        self._runner = AsyncRunner()
        # If the sync ``WireBoardClient`` constructed an AsyncWireBoardClient
        # for us, we own it and must aclose it on stop — otherwise its httpx
        # connection pool leaks for the lifetime of the process.
        self._owned_minter = owned_minter
        self._async = AsyncLiveClient(
            minter,
            site_id=site_id,
            categories=categories,
            on_change=on_change,
            on_event=on_event,
            on_error=on_error,
            on_rotate=on_rotate,
            on_reconnect=on_reconnect,
        )

    @property
    def state(self) -> ManagedLiveState:
        """Current merged state. Reading from the calling thread is safe;
        the value is an immutable-by-convention snapshot replaced atomically
        on every update.
        """
        return self._async.state

    @property
    def status(self) -> LiveClientStatus:
        return self._async.status

    def start(self) -> None:
        """Fetch the snapshot, mint a JWT, and open the stream. Blocks until
        the stream is open (or the initial connect fails)."""
        self._runner.start()
        self._runner.run(self._async.start())

    def stop(self) -> None:
        """Close the stream and shut down the worker thread. Idempotent."""
        if self._runner.is_running():
            try:
                self._runner.run(self._async.stop())
                if self._owned_minter is not None:
                    aclose = getattr(self._owned_minter, "aclose", None)
                    if aclose is not None:
                        self._runner.run(aclose())
            finally:
                self._runner.shutdown()

    def subscribe(
        self, listener: Callable[[ManagedLiveState], None]
    ) -> Callable[[], None]:
        """Listen for state updates. Returns an ``unsubscribe`` callable."""
        return self._async.subscribe(listener)

    def __enter__(self) -> LiveClient:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
