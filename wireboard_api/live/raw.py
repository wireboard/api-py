"""Raw Live client (sync). Wraps :class:`AsyncLiveRawClient`."""

from __future__ import annotations

from collections.abc import Callable

from ..constants import LiveCategory
from ..types import LiveClientStatus, LiveEnvelope
from ._async_runner import AsyncRunner
from ._subscription import AsyncMinter
from .async_raw import AsyncLiveRawClient


class LiveRawClient:
    """Synchronous facade for the raw Live client. Multi-site, customer-owned
    state. See :class:`AsyncLiveRawClient` for the underlying contract.

    Callbacks fire on the background thread.
    """

    def __init__(
        self,
        minter: AsyncMinter,
        *,
        sites: str | list[str],
        on_event: Callable[[LiveEnvelope], None],
        categories: list[LiveCategory] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_rotate: Callable[[], None] | None = None,
        on_reconnect: Callable[[], None] | None = None,
        owned_minter: object | None = None,
    ) -> None:
        self._runner = AsyncRunner()
        # See note on owned_minter in LiveClient.__init__.
        self._owned_minter = owned_minter
        self._async = AsyncLiveRawClient(
            minter,
            sites=sites,
            categories=categories,
            on_event=on_event,
            on_error=on_error,
            on_rotate=on_rotate,
            on_reconnect=on_reconnect,
        )

    @property
    def status(self) -> LiveClientStatus:
        return self._async.status

    def start(self) -> None:
        self._runner.start()
        self._runner.run(self._async.start())

    def stop(self) -> None:
        if self._runner.is_running():
            try:
                self._runner.run(self._async.stop())
                if self._owned_minter is not None:
                    aclose = getattr(self._owned_minter, "aclose", None)
                    if aclose is not None:
                        self._runner.run(aclose())
            finally:
                self._runner.shutdown()

    def __enter__(self) -> LiveRawClient:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
