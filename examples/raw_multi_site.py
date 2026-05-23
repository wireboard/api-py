"""Raw Live mode across multiple sites.

Opens one SSE connection that streams events for up to 3 of your sites.
Each envelope carries ``site_id``, so you can route it to per-site state
in your own store. Use raw mode when you have your own reactive layer or
when a single managed (single-site) client doesn't fit.

Run:  WIREBOARD_TOKEN=... python examples/raw_multi_site.py
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter

from wireboard_api import LiveEnvelope, WireBoardClient


def main() -> None:
    token = os.environ.get("WIREBOARD_TOKEN")
    if not token:
        raise SystemExit("WIREBOARD_TOKEN env var is required.")

    with WireBoardClient(token=token) as wb:
        sites = wb.sites()["sites"]
        site_ids = [s["id"] for s in sites[:3]]
        if not site_ids:
            raise SystemExit("no sites in this account")
        print(f"Subscribing to {len(site_ids)} site(s): {', '.join(site_ids)}")

        per_site_counts: Counter[str] = Counter()
        per_site_latest: dict[str, str] = {}

        def on_event(env: LiveEnvelope) -> None:
            per_site_counts[env["site_id"]] += 1
            per_site_latest[env["site_id"]] = env["category"]

        with wb.live_raw(
            sites=site_ids,
            categories=["visitors", "top_pages", "active_sessions"],
            on_event=on_event,
            on_error=lambda e: print(f"raw error: {e}", file=sys.stderr),
        ):
            print("Listening for 30s...")
            time.sleep(30)

        print("\nPer-site activity:")
        for sid in site_ids:
            n = per_site_counts.get(sid, 0)
            latest = per_site_latest.get(sid, "—")
            print(f"  {sid:<10} {str(n):>4} envelope(s)  latest: {latest}")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"\nFatal: {err}", file=sys.stderr)
        sys.exit(1)
