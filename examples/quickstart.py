"""Quickstart — sync.

Proves the SDK installs, authenticates, and reads your account. ~20 lines.

Run:  WIREBOARD_TOKEN=... python examples/quickstart.py
"""

from __future__ import annotations

import os
import sys

from wireboard_api import WireBoardClient


def main() -> None:
    token = os.environ.get("WIREBOARD_TOKEN")
    if not token:
        raise SystemExit("WIREBOARD_TOKEN env var is required.")

    with WireBoardClient(token=token) as wb:
        account = wb.account()
        print(f"Hello {account['name']} ({account['email']})")
        print(f"Abilities: {', '.join(account['abilities'])}")

        sites = wb.sites()["sites"]
        print(f"\nYou own {len(sites)} site(s):")
        for s in sites[:5]:
            print(f"  {s['id']:<10} {s['domain']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"\nFatal: {err}", file=sys.stderr)
        sys.exit(1)
