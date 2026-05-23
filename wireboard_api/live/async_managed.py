"""Managed Live client (async). Single site, SDK owns the state."""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from ..constants import LIVE_CATEGORIES, LiveCategory
from ..types import LiveClientStatus, LiveEnvelope, ManagedLiveState
from ._merge import apply_event, empty_state, from_snapshot
from ._subscription import AsyncMinter, Subscription, SubscriptionOptions


class AsyncLiveClient:
    """Managed Live client. Maintains merged state per category internally;
    customers read state via :meth:`subscribe` or the :attr:`state` property
    and never see drop signals directly.

    Single-site only. For multi-site, instantiate one ``AsyncLiveClient``
    per site or use :class:`AsyncLiveRawClient`.

    The SDK handles snapshot refetch on (re)connect, drop-signal merging
    per category, zero-gap JWT rotation, and lifecycle.

    Example::

        live = wb.live(site_id=site_id, categories=["visitors", "top_pages"])
        live.subscribe(lambda state: print(state["live"]["visitors"]))
        await live.start()
        # ... later
        await live.stop()
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
    ) -> None:
        if not site_id:
            raise TypeError("AsyncLiveClient: `site_id` is required.")
        self._minter = minter
        self._site_id = site_id
        self._categories: list[LiveCategory] = (
            list(categories) if categories is not None else list(LIVE_CATEGORIES)
        )
        self._on_event_hook = on_event
        self._state: ManagedLiveState = empty_state(self._site_id)
        self._listeners: list[Callable[[ManagedLiveState], None]] = []
        if on_change is not None:
            self._listeners.append(on_change)

        self._sub = Subscription(
            minter,
            SubscriptionOptions(
                sites=[self._site_id],
                categories=self._categories,
                on_event=self._apply_envelope,
                on_error=on_error,
                on_rotate=on_rotate,
                on_reconnect=on_reconnect,
                before_hard_reconnect=self._refetch_snapshot,
            ),
        )

    @property
    def state(self) -> ManagedLiveState:
        """Current merged state.

        A NEW object reference is produced on every update — ``prev is not
        next`` is a sound change check. Sub-objects are reused when unchanged.
        """
        return self._state

    @property
    def status(self) -> LiveClientStatus:
        """Current connection status."""
        return self._sub.status

    async def start(self) -> None:
        """Fetch the initial snapshot, mint a JWT, and open the stream."""
        await self._refetch_snapshot()
        await self._sub.start()

    async def stop(self) -> None:
        """Close the stream. Safe to call multiple times."""
        await self._sub.stop()

    def subscribe(
        self, listener: Callable[[ManagedLiveState], None]
    ) -> Callable[[], None]:
        """Listen for state updates. Returns an ``unsubscribe`` callable."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(listener)

        return unsubscribe

    async def _refetch_snapshot(self) -> None:
        snapshot = await self._minter.live_state(
            site_id=self._site_id,
            categories=self._categories,
        )
        self._state = from_snapshot(snapshot)
        self._notify()

    def _apply_envelope(self, env: LiveEnvelope) -> None:
        if env.get("site_id") != self._site_id:
            return
        if self._on_event_hook is not None:
            # Instrumentation listener errors must not break the subscription.
            with contextlib.suppress(Exception):
                self._on_event_hook(env)
        self._state = apply_event(self._state, env)
        self._notify()

    def _notify(self) -> None:
        snapshot = self._state
        for listener in list(self._listeners):
            # Listener errors must not break the subscription.
            with contextlib.suppress(Exception):
                listener(snapshot)
