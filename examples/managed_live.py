"""Managed Live mode (sync) — single site, SDK owns the state.

Opens a managed Live subscription for the first site in your account.
Prints "now" and top 3 pages every time the state changes. The SDK handles
the snapshot, drop signals, and JWT rotation; this script just prints.

Run:  WIREBOARD_TOKEN=... python examples/managed_live.py
"""

from __future__ import annotations

import os
import sys
import time

from wireboard_api import ManagedLiveState, WireBoardClient


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


def main() -> None:
    token = os.environ.get("WIREBOARD_TOKEN")
    if not token:
        raise SystemExit("WIREBOARD_TOKEN env var is required.")

    with WireBoardClient(token=token) as wb:
        sites = wb.sites()["sites"]
        if not sites:
            raise SystemExit("no sites in this account")
        site = sites[0]
        print(f"Subscribing to {site['id']} ({site['domain']})")

        with wb.live(
            site_id=site["id"],
            categories=["visitors", "top_pages"],
            on_change=render,
            on_error=lambda e: print(f"\nerror: {e}"),
        ) as live:
            print("Listening for 60s — Ctrl+C to stop early.")
            try:
                time.sleep(60)
            except KeyboardInterrupt:
                pass
        print()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"\nFatal: {err}", file=sys.stderr)
        sys.exit(1)
