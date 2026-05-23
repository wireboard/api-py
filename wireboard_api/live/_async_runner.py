"""Background-thread asyncio event loop used by the sync Live wrappers.

The sync :class:`LiveClient` / :class:`LiveRawClient` are thin shims over
their async counterparts: they boot a worker thread running a dedicated
asyncio event loop, and proxy ``start()`` / ``stop()`` onto that loop via
``run_coroutine_threadsafe``. Callbacks fire on the worker thread — the same
constraint the JS SDK already imposes (callbacks fire on the EventSource's
thread).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import Any, TypeVar

T = TypeVar("T")


class AsyncRunner:
    """One worker thread + one asyncio event loop, started on demand."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("AsyncRunner: loop not started")
        return self._loop

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="wireboard-live-loop",
            daemon=True,
        )
        self._thread.start()
        # Wait until the loop is bound on the worker thread before allowing
        # any caller to submit work.
        self._ready.wait()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                # Cancel any remaining tasks and let them settle.
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def submit(self, coro: Awaitable[T]) -> asyncio.Future[T] | Any:
        """Schedule ``coro`` on the loop and return a ``concurrent.futures``
        future for blocking on. Caller must :meth:`start` first.
        """
        if self._loop is None or not self.is_running():
            raise RuntimeError("AsyncRunner: not running")
        return asyncio.run_coroutine_threadsafe(_coroify(coro), self._loop)

    def run(self, coro: Awaitable[T]) -> T:
        """Block until ``coro`` completes; raise its exception if any."""
        future = self.submit(coro)
        return future.result()

    def shutdown(self, timeout: float | None = 5.0) -> None:
        if self._loop is None or self._thread is None:
            return
        loop = self._loop
        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=timeout)
        self._thread = None
        self._loop = None


async def _coroify(awaitable: Awaitable[T]) -> T:
    """Some methods are already coroutines; others are awaitables. Either
    way, awaiting them in a thin coroutine guarantees we hand a coroutine to
    ``run_coroutine_threadsafe`` (which only accepts coroutines).
    """
    return await awaitable
