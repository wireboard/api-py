"""Raw Live client (async). Multi-site, customer owns the state."""

from __future__ import annotations

from collections.abc import Callable

from ..constants import LIVE_CATEGORIES, LiveCategory
from ..types import LiveClientStatus, LiveEnvelope
from ._subscription import AsyncMinter, Subscription, SubscriptionOptions


class AsyncLiveRawClient:
    """Low-level Live client. Delivers each raw SSE envelope to ``on_event``;
    merge logic is the customer's responsibility.

    Use this for multi-site subscriptions, custom state shapes, or when you
    want full control over how drop signals are applied. For single-site
    managed state, use :class:`AsyncLiveClient` instead.
    """

    def __init__(
        self,
        minter: AsyncMinter,
        *,
        sites: str | list[str],
        categories: list[LiveCategory] | None = None,
        on_event: Callable[[LiveEnvelope], None],
        on_error: Callable[[Exception], None] | None = None,
        on_rotate: Callable[[], None] | None = None,
        on_reconnect: Callable[[], None] | None = None,
    ) -> None:
        site_list: list[str] = [sites] if isinstance(sites, str) else list(sites)
        if len(site_list) == 0:
            raise TypeError("AsyncLiveRawClient: at least one site is required.")
        cats: list[LiveCategory] = (
            list(categories) if categories is not None else list(LIVE_CATEGORIES)
        )

        self._sub = Subscription(
            minter,
            SubscriptionOptions(
                sites=site_list,
                categories=cats,
                on_event=on_event,
                on_error=on_error,
                on_rotate=on_rotate,
                on_reconnect=on_reconnect,
                before_hard_reconnect=None,
            ),
        )

    @property
    def status(self) -> LiveClientStatus:
        """Current connection status.

        Lifecycle: ``'idle'`` → ``'connecting'`` → ``'open'`` ↔
        ``'connecting'`` (on reconnect) → ``'closed'`` (after ``stop()``).
        """
        return self._sub.status

    async def start(self) -> None:
        """Mint a JWT and open the SSE connection."""
        await self._sub.start()

    async def stop(self) -> None:
        """Close the connection. Safe to call multiple times."""
        await self._sub.stop()
