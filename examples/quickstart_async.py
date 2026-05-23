"""Quickstart — async.

Same as ``quickstart.py``, using the async client. Works under asyncio,
Trio (via anyio), or any other async runtime that httpx supports.

Run:  WIREBOARD_TOKEN=... python examples/quickstart_async.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from wireboard_api import AsyncWireBoardClient


async def main() -> None:
    token = os.environ.get("WIREBOARD_TOKEN")
    if not token:
        raise SystemExit("WIREBOARD_TOKEN env var is required.")

    async with AsyncWireBoardClient(token=token) as wb:
        account = await wb.account()
        print(f"Hello {account['name']} ({account['email']})")
        print(f"Abilities: {', '.join(account['abilities'])}")

        sites = (await wb.sites())["sites"]
        print(f"\nYou own {len(sites)} site(s):")
        for s in sites[:5]:
            print(f"  {s['id']:<10} {s['domain']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as err:
        print(f"\nFatal: {err}", file=sys.stderr)
        sys.exit(1)
