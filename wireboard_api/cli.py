"""``wireboard-api verify`` — exercise the SDK against a real account.

Mirrors the JS CLI: hits every REST surface for a 7-day window, opens a
45-second managed Live subscription, and prints a pass/fail summary table.
Exit code ``0`` on full pass, ``1`` on any failure, ``2`` on usage error.
Use ``--no-color`` for CI logs and ``--duration=920`` to also observe a
full JWT rotation cycle.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from . import (
    LIVE_CATEGORIES,
    VERSION,
    LiveEnvelope,
    WireBoardApiError,
    WireBoardAuthError,
    WireBoardClient,
)

USAGE = """wireboard-api verify — exercise the SDK against a real account

Usage:
  wireboard-api verify [--token=TOKEN] [--site=SITE_ID] [--duration=SECONDS] [--no-color]

Options:
  --token=TOKEN       API bearer token. Falls back to WIREBOARD_TOKEN env var.
                      Flag wins over env.
  --site=SITE_ID      Specific site to test against. Defaults to the first site
                      from /v1/sites.
  --duration=SECONDS  How long to keep the Live subscription open. Default: 45.
                      Pass >=920 to observe a full JWT rotation cycle.
  --no-color          Strip ANSI escapes (recommended for CI logs).
  --help, -h          Show this help.

Exit code: 0 on full pass, 1 on any failure, 2 on usage error.
"""


COLORS = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "green": "\x1b[32m",
    "red": "\x1b[31m",
    "yellow": "\x1b[33m",
    "cyan": "\x1b[36m",
}


class Printer:
    def __init__(self, use_color: bool) -> None:
        self.use_color = use_color

    def paint(self, text: str, color: str) -> str:
        if not self.use_color:
            return text
        c = COLORS.get(color, "")
        return f"{c}{text}{COLORS['reset']}"

    def line(self, s: str = "") -> None:
        sys.stdout.write(s + "\n")
        sys.stdout.flush()


@dataclass
class CheckResult:
    name: str
    status: str  # 'pass' | 'fail'
    detail: str
    sublines: list[str] = field(default_factory=list)


@dataclass
class StreamCounters:
    per_category: Counter[str] = field(default_factory=Counter)
    top_drops: int = 0
    session_drops: int = 0
    total: int = 0


def _error_detail(err: BaseException) -> str:
    if isinstance(err, WireBoardApiError):
        code = f" code={err.code}" if err.code else ""
        return f"HTTP {err.http_status}{code}: {err}"
    if isinstance(err, WireBoardAuthError):
        return f"HTTP {err.http_status}: {err}"
    return f"{type(err).__name__}: {err}"


def _format_utc_date(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _run_rest(
    results: list[CheckResult],
    name: str,
    fn: Any,
) -> None:
    try:
        detail = fn()
        results.append(CheckResult(name=name, status="pass", detail=detail))
    except Exception as err:
        results.append(CheckResult(name=name, status="fail", detail=_error_detail(err)))


def _count_drops(env: LiveEnvelope, counters: StreamCounters) -> None:
    cat = env["category"]
    data = env["data"]
    if cat in (
        "top_pages",
        "top_referrers",
        "top_mediums",
        "top_sources",
        "top_search",
        "top_social",
        "top_countries",
        "top_devices",
        "top_browsers",
        "top_oses",
        "top_languages",
        "top_screens",
        "geo",
    ):
        for e in data:
            if e.get("count") == 0:
                counters.top_drops += 1
    elif cat == "active_sessions":
        for s in data:
            if s.get("step_count") == 0:
                counters.session_drops += 1


def _top_categories(c: Counter[str], n: int) -> list[str]:
    return [f"{k}({v})" for k, v in c.most_common(n)]


def _rotation_detail(observed: bool, rotate_at_s: float | None, duration: int) -> str:
    if observed and rotate_at_s is not None:
        return f"JWT rotation: ok (observed at +{round(rotate_at_s, 1)}s)"
    if duration < 920:
        return f"JWT rotation: not observed (need --duration=920 to verify; default {duration}s)"
    return f"JWT rotation: NOT observed (duration {duration}s should have triggered one)"


def _reconnect_detail(count: int, first_at_s: float | None) -> str:
    if count == 0:
        return "reconnects: 0"
    first = f"+{round(first_at_s, 1)}s" if first_at_s is not None else "?"
    return f"reconnects: {count} (first at {first} — silent recovery from connection drop)"


def _print_results(p: Printer, results: list[CheckResult]) -> None:
    name_pad = max(*(len(r.name) for r in results), 28) + 2
    for r in results:
        tag = p.paint("PASS", "green") if r.status == "pass" else p.paint("FAIL", "red")
        p.line(f"  {r.name.ljust(name_pad)}{tag}  {r.detail}")
        if r.sublines:
            indent = " " * (name_pad + 8)
            for sub in r.sublines:
                p.line(f"{indent}{p.paint(sub, 'dim')}")
    p.line(f"  {'─' * (name_pad + 8)}")
    passed = sum(1 for r in results if r.status == "pass")
    total = len(results)
    summary_tag = p.paint("PASS", "green") if passed == total else p.paint("FAIL", "red")
    p.line(f"  {'SUMMARY'.ljust(name_pad)}{summary_tag}  {passed}/{total} surfaces")


def _run_live_stream(
    p: Printer,
    wb: WireBoardClient,
    site_id: str,
    duration_seconds: int,
) -> CheckResult:
    counters = StreamCounters()
    rotation_observed = False
    first_error: list[Exception] = []
    reconnects = [0]
    first_reconnect_at: list[float | None] = [None]
    started_at = time.monotonic()
    rotate_at: list[float | None] = [None]

    def on_event(env: LiveEnvelope) -> None:
        counters.total += 1
        counters.per_category[env["category"]] += 1
        _count_drops(env, counters)

    def on_error(err: Exception) -> None:
        if not first_error:
            first_error.append(err)

    def on_rotate() -> None:
        nonlocal rotation_observed
        rotation_observed = True
        rotate_at[0] = time.monotonic() - started_at

    def on_reconnect() -> None:
        reconnects[0] += 1
        if first_reconnect_at[0] is None:
            first_reconnect_at[0] = time.monotonic() - started_at

    live = wb.live(
        site_id=site_id,
        categories=list(LIVE_CATEGORIES),
        on_event=on_event,
        on_error=on_error,
        on_rotate=on_rotate,
        on_reconnect=on_reconnect,
    )

    p.line(p.paint(f"  · opening live subscription for {duration_seconds}s…", "dim"))

    try:
        live.start()
    except Exception as err:
        return CheckResult(
            name=f"live: stream ({duration_seconds}s)",
            status="fail",
            detail=f"failed to open: {_error_detail(err)}",
        )

    try:
        time.sleep(duration_seconds)
    finally:
        live.stop()
        time.sleep(0.1)  # grace period for in-flight close

    if first_error:
        captured = first_error[0]
        detail = f"caught error during stream: {captured}"
        status = "fail"
    else:
        detail = f"{counters.total} events received"
        status = "pass"

    sublines = [
        f"by category (top): {' '.join(_top_categories(counters.per_category, 8)) or '—'}",
        f"drop signals: top-N={counters.top_drops} active_sessions={counters.session_drops}",
        _rotation_detail(rotation_observed, rotate_at[0], duration_seconds),
        _reconnect_detail(reconnects[0], first_reconnect_at[0]),
        f"errors: {0 if not first_error else 1}",
    ]
    return CheckResult(
        name=f"live: stream ({duration_seconds}s)",
        status=status,
        detail=detail,
        sublines=sublines,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wireboard-api",
        description="WireBoard API SDK CLI",
        add_help=False,
    )
    parser.add_argument("subcommand", nargs="?", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--site", default=None)
    parser.add_argument("--duration", type=int, default=45)
    parser.add_argument("--no-color", action="store_true", dest="no_color")
    parser.add_argument("--help", "-h", action="store_true", dest="help")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    # ``parse_args`` (not ``parse_known_args``) so typos like --tokn=... fail
    # loudly with the usage banner — silently ignoring unknown flags is the
    # exact footgun that lets a user think they set ``--duration=920`` and
    # never observe a JWT rotation.
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already wrote the error; convert its 2 → our 2 (usage).
        return int(exc.code) if isinstance(exc.code, int) else 2

    if args.help:
        sys.stdout.write(USAGE)
        return 0

    if args.subcommand != "verify":
        sys.stderr.write(USAGE)
        return 2

    token = args.token or os.environ.get("WIREBOARD_TOKEN")
    use_color = (
        not args.no_color
        and "NO_COLOR" not in os.environ
        and sys.stdout.isatty()
    )
    p = Printer(use_color)

    if not token:
        p.line(p.paint("error:", "red") + " no token provided. Pass --token=TOKEN or set WIREBOARD_TOKEN.")
        return 1

    if args.duration < 1:
        p.line(p.paint("error:", "red") + f" invalid --duration={args.duration}; must be a positive integer.")
        return 1

    token_suffix = token[-4:]
    p.line(
        p.paint(f"WireBoard SDK verify — token …{token_suffix}", "bold")
        + p.paint(f"  (sdk v{VERSION})", "dim")
    )

    wb = WireBoardClient(token=token)
    results: list[CheckResult] = []

    # 1. account()
    abilities: list[str] = []
    try:
        account = wb.account()
        abilities = list(account["abilities"])
        results.append(
            CheckResult(
                name="account()",
                status="pass",
                detail=f"team-owner: {account['email']}  abilities: {','.join(account['abilities'])}",
            )
        )
    except Exception as err:
        results.append(CheckResult(name="account()", status="fail", detail=_error_detail(err)))
        _print_results(p, results)
        return 1

    # 2. sites()
    site_id: str | None = None
    domain = ""
    try:
        sites = wb.sites()["sites"]
        if len(sites) == 0:
            results.append(CheckResult(name="sites()", status="fail", detail="account has no sites"))
            _print_results(p, results)
            return 1
        picked = sites[0]
        if args.site:
            match = next((s for s in sites if s["id"] == args.site), None)
            if match is None:
                results.append(
                    CheckResult(
                        name="sites()",
                        status="fail",
                        detail=f"site {args.site} not in account (have {len(sites)})",
                    )
                )
                _print_results(p, results)
                return 1
            picked = match
        site_id = picked["id"]
        domain = picked["domain"]
        results.append(
            CheckResult(
                name="sites()",
                status="pass",
                detail=f"{len(sites)} site(s); picked {picked['id']} ({picked['domain']})",
            )
        )
    except Exception as err:
        results.append(CheckResult(name="sites()", status="fail", detail=_error_detail(err)))
        _print_results(p, results)
        return 1

    if not site_id:
        _print_results(p, results)
        return 1

    # 7-day range ending today (UTC)
    today = datetime.now(timezone.utc)
    to = _format_utc_date(today)
    from_ = _format_utc_date(today - timedelta(days=7))

    sid = site_id  # capture for closures

    # 3–9. REST surfaces
    _run_rest(
        results,
        "aggregate()",
        lambda: (lambda r: f"visitors={r['visitors']}  pageviews={r['pageviews']}  bounce={r['bounce_rate']}  dur={r['visit_duration']}s")(
            wb.aggregate(site_id=sid, from_=from_, to=to)
        ),
    )
    _run_rest(
        results,
        "timeseries(visitors,day)",
        lambda: f"{len(wb.timeseries(site_id=sid, from_=from_, to=to, metric='visitors', interval='day')['points'])} points",
    )
    _run_rest(
        results,
        "history()",
        lambda: f"{len(wb.history(site_id=sid, from_=from_, to=to)['points'])} points",
    )

    def _breakdown_check() -> str:
        r = wb.breakdown(site_id=sid, from_=from_, to=to, dimension="country")
        if not r["rows"]:
            return "0 rows (no traffic in window)"
        top = r["rows"][0]
        return f"{len(r['rows'])} rows; top: {top.get('country')} ({top.get('visitors')})"

    _run_rest(results, "breakdown(country)", _breakdown_check)

    _run_rest(
        results,
        "urls()",
        lambda: (lambda r: f"{r['total']} total, {len(r['rows'])} returned")(
            wb.urls(site_id=sid, from_=from_, to=to)
        ),
    )
    _run_rest(
        results,
        "events()",
        lambda: f"{len(wb.events(site_id=sid, from_=from_, to=to)['rows'])} rows",
    )
    _run_rest(
        results,
        "dimensions()",
        lambda: (lambda r: f"{len(r['breakdown_dimensions'])} breakdown dims, {r['max_range_days']} max_range_days")(
            wb.dimensions()
        ),
    )

    # Live API only if the token carries the ability
    if "live:read" not in abilities:
        results.append(
            CheckResult(
                name="live: snapshot",
                status="fail",
                detail="token does not have live:read ability — skipping live checks",
            )
        )
        _print_results(p, results)
        return 1

    # 10. live: state snapshot
    def _live_snapshot() -> str:
        snap = wb.live_state(site_id=sid, categories=list(LIVE_CATEGORIES))
        return f"{len(snap['live'])}/{len(LIVE_CATEGORIES)} categories present"

    _run_rest(results, "live: state snapshot", _live_snapshot)

    # 11. live: stream
    results.append(_run_live_stream(p, wb, sid, args.duration))

    _ = domain  # for log readability — unused after intro

    _print_results(p, results)
    failed = sum(1 for r in results if r.status == "fail")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
