"""Managed Live mode (async).

Same as ``managed_live.py`` but using the async client. Useful inside a
larger asyncio app (FastAPI, Starlette, aiohttp).

Run:  WIREBOARD_TOKEN=... python examples/managed_live_async.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from wireboard_api import AsyncWireBoardClient, ManagedLiveState


def render(state: ManagedLiveState) -> None:
    v = state["live"]["visitors"]
    pages = state["live"]["top_pages"][:3]
    now = v["live"] if v else 0
    returning = v["returning"] if v else 0
    print(
        f"\rnow: {now:>3}  returning: {returning:>3}  top: "
        + " | ".join(f"{p['url']} ({p['count']})" for p in pages),
        end="",
        flush=True,
    )


async def main() -> None:
    token = os.environ.get("WIREBOARD_TOKEN")
    if not token:
        raise SystemExit("WIREBOARD_TOKEN env var is required.")

    async with AsyncWireBoardClient(token=token) as wb:
        sites = (await wb.sites())["sites"]
        if not sites:
            raise SystemExit("no sites in this account")
        site = sites[0]
        print(f"Subscribing to {site['id']} ({site['domain']})")

        live = wb.live(
            site_id=site["id"],
            categories=["visitors", "top_pages"],
            on_change=render,
            on_error=lambda e: print(f"\nerror: {e}"),
        )
        await live.start()
        try:
            print("Listening for 60s — Ctrl+C to stop early.")
            await asyncio.sleep(60)
        finally:
            await live.stop()
        print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as err:
        print(f"\nFatal: {err}", file=sys.stderr)
        sys.exit(1)
