<p align="center">
  <a href="https://wireboard.io">
    <img src="https://wireboard.io/img/logo-blue.png" alt="WireBoard" height="64">
  </a>
</p>

<h1 align="center"><code>wireboard-api</code></h1>

<p align="center">
  Official Python SDK for the <a href="https://wireboard.io">WireBoard</a> REST and Live APIs.
</p>

<p align="center">
  Pull historical analytics, subscribe to real-time visitor activity, and integrate WireBoard with anything you can write Python against.
</p>

<p align="center">
  <a href="https://pypi.org/project/wireboard-api/"><img src="https://img.shields.io/pypi/v/wireboard-api.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/wireboard-api/"><img src="https://img.shields.io/pypi/pyversions/wireboard-api.svg" alt="Python versions"></a>
  <a href="https://pypi.org/project/wireboard-api/"><img src="https://img.shields.io/badge/types-PEP%20561-blue.svg" alt="types: PEP 561"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/pypi/l/wireboard-api.svg" alt="license: MIT"></a>
</p>

---

- Sync **and** async client — pick whichever fits your app
- Strict type hints end-to-end via `TypedDict`, `Literal`, and PEP 561 (`py.typed`)
- One SSE engine, used by both managed and raw Live clients
- Built on `httpx` + `httpx-sse` — works under asyncio, FastAPI, Django, Flask, scripts
- Zero-config JWT rotation, drop-signal merging, hard-reconnect with snapshot refetch

## Install

```sh
pip install wireboard-api
```

## Quickstart

Mint a token in [**Settings → API**](https://wireboard.io/dashboard/settings/api)
on your WireBoard dashboard (needs the `analytics:read` ability for REST,
`live:read` for the Live API). Then:

```python
import os
import time
from wireboard_api import WireBoardClient

wb = WireBoardClient(token=os.environ["WIREBOARD_TOKEN"])

# Historical
sites = wb.sites()["sites"]
site = sites[0]

summary = wb.aggregate(
    site_id=site["id"],
    from_="2026-05-01",
    to="2026-05-22",
)
print(f"{summary['visitors']} visitors, {summary['pageviews']} pageviews")

# Real-time (managed mode — SDK handles state, drop signals, JWT rotation)
live = wb.live(
    site_id=site["id"],
    categories=["visitors", "top_pages"],
)

live.subscribe(lambda state: print(
    "now:", state["live"]["visitors"]["live"] if state["live"]["visitors"] else 0,
    "top:", state["live"]["top_pages"][0]["url"] if state["live"]["top_pages"] else None,
))

live.start()
time.sleep(30)
live.stop()
```

The SDK handles snapshot rebuild on reconnect, drop signals, and short-lived
JWT rotation for you. A NEW state object is emitted on every update, so
`prev is not next` works as a change check.

### Async

The same surface is available under `AsyncWireBoardClient`:

```python
import asyncio
import os
from wireboard_api import AsyncWireBoardClient

async def main():
    async with AsyncWireBoardClient(token=os.environ["WIREBOARD_TOKEN"]) as wb:
        sites = (await wb.sites())["sites"]
        summary = await wb.aggregate(
            site_id=sites[0]["id"], from_="2026-05-01", to="2026-05-22",
        )
        print(summary)

asyncio.run(main())
```

## API at a glance

Every method returns the unwrapped `data` payload from the API envelope and
raises `WireBoardApiError` / `WireBoardAuthError` on failure (see
[Errors](#errors)).

| Method | Returns | What it does |
| --- | --- | --- |
| `account()` | `Account` | Team-owner identity + the abilities of this token |
| `sites()` | `SitesResult` | Every site owned by the team |
| `aggregate(...)` | `AggregateResult` | Period totals (visitors, pageviews, bounce, duration) |
| `timeseries(...)` | `TimeseriesResult` | One metric, bucketed by `hour` or `day` |
| `history(...)` | `HistoryResult` | Visitors / returning / pageviews / bounce / duration per day |
| `breakdown(...)` | `BreakdownResult` | Top-N rows by a single dimension |
| `urls(...)` | `UrlsResult` | Per-URL metrics with `prefix` / `contains` / `exact` filters |
| `events(...)` | `EventsResult` | Custom events report |
| `dimensions()` | `Dimensions` | Meta: supported dimensions, metrics, limits |
| `live_state(...)` | `LiveStateSnapshot` | Current per-category snapshot for one site |
| `live_token(...)` | `LiveTokenResult` | Mint a 15-min subscriber JWT for the SSE stream |
| `live(...)` | `LiveClient` | Managed Live client (handles snapshot + merge + rotation) |
| `live_raw(...)` | `LiveRawClient` | Raw Live client (multi-site, custom merge) |
| `with_meta(fn)` | `(data, rate_limit)` | Run a call and capture its rate-limit headers |

The async client (`AsyncWireBoardClient`) has identical method names with
`async`/`await` and `AsyncLiveClient` / `AsyncLiveRawClient` for Live.

Full reference: [REST](https://wireboard.io/docs/api-rest) · [Live](https://wireboard.io/docs/api-live) · [Errors](https://wireboard.io/docs/api-errors).

### Parameter conventions

- The wire-level `from` parameter is a Python reserved word. Pass it as
  `from_=` (trailing underscore — Python convention for keyword conflicts);
  the SDK strips the underscore at the wire boundary. `to=` is unchanged.
- Date params accept a `YYYY-MM-DD` string, a `datetime.date`, or a
  `datetime.datetime`. Aware datetimes are converted to UTC; naive
  datetimes are taken as-is (pass `datetime.now(timezone.utc)`, not
  `datetime.now()`, if you want "today in UTC").
- Array params (e.g. `categories=["visitors", "top_pages"]`) are comma-joined.
- The `filter` argument on `events()` is serialised as
  `filter[<col>]=...` / `filter[props.<key>]=...` automatically.

## Live API: two modes

The SDK exposes both a managed and a raw client over the same SSE protocol.
Pick based on what your UI needs.

### Managed mode — single site, SDK owns the state

```python
live = wb.live(
    site_id="xK4mP2nT",
    categories=["visitors", "top_pages", "active_sessions"],
    on_change=lambda state: render(state["live"]),
    on_error=lambda err: print(f"error: {err}"),
    on_rotate=lambda: print("jwt rotated"),     # optional, observability
    on_reconnect=lambda: print("reconnected"),  # optional, observability
)

live.start()              # blocks until snapshot loaded + stream open
# state available at `live.state`; subscribe(...) returns an unsubscribe fn
```

What the managed client handles automatically:

- Fetches `/v1/live/state` on first connect and replays the snapshot.
- Merges drop signals per category (`count: 0` → remove from top-N,
  `step_count: 0` → remove from `active_sessions`).
- Rotates the 15-minute JWT 60 s before expiry, with a 1 s zero-gap
  overlap between the old and new SSE connections — no event gap.
- Dedupes events by `lastEventId` across the rotation boundary.
- On a hard reconnect (connection drop before JWT expiry), waits 500 ms,
  refetches the snapshot, mints a fresh JWT, and resumes — fires
  `on_reconnect` once so you can surface "silent recovery" in your UI.

`on_rotate` and `on_reconnect` are optional observability hooks; not
implementing them is the supported case for most apps.

### Raw mode — multi-site, you own the state

```python
def on_event(env):
    # env["category"] is one of the 20 Live categories
    if env["category"] == "top_pages":
        for row in env["data"]:
            # row["count"] == 0 means "remove from local state"
            ...

raw = wb.live_raw(
    sites=["xK4mP2nT", "aB3cD4fG"],
    categories=["visitors", "top_pages"],
    on_event=on_event,
)

raw.start()
```

Use raw mode for multi-site dashboards, when you already have your own
reactive store, or when you want full control over how drop signals apply.

### Sync vs async Live

The sync `LiveClient` runs the SSE engine on a background asyncio event-loop
thread. Callbacks (`on_change`, `on_event`, ...) fire on that thread; use
threading primitives if your handler needs to mutate state shared with your
main thread.

The async `AsyncLiveClient` runs on the caller's event loop. Use it inside
FastAPI / Starlette / aiohttp / any asyncio app.

## Types

The SDK ships strict type hints. Response types are `TypedDict`s, so dict
access works and your type checker can narrow safely:

```python
from wireboard_api import WireBoardClient, AggregateResult

wb = WireBoardClient(token=token)
r: AggregateResult = wb.aggregate(site_id=sid, from_="2026-05-01", to="2026-05-22")
visitors: int = r["visitors"]
```

The Live envelope (`LiveEnvelope`) carries a `category` literal and a
loosely-typed `data`. Narrow with an `if env["category"] == ...` check:

```python
def on_event(env: LiveEnvelope) -> None:
    if env["category"] == "visitors":
        print("live:", env["data"]["live"])
    elif env["category"] == "top_pages":
        for row in env["data"]:
            print(row["url"], row["count"])
```

## Errors

Two exception classes:

```python
from wireboard_api import WireBoardApiError, WireBoardAuthError

try:
    wb.aggregate(site_id=sid, from_=f, to=t)
except WireBoardAuthError as err:
    # 401 → re-auth; 403 → re-mint a token with the right abilities
    print(err.http_status, err)
except WireBoardApiError as err:
    if err.code == "site_not_found":
        ...  # unknown site or wrong team
    elif err.code == "concurrent_limit_reached":
        ...  # too many live subscriptions
    elif err.code == "unknown_filter":
        ...  # events filter not whitelisted
    # err.field_errors, err.http_status, err.rate_limit are on the error
```

The SDK auto-retries **once** on a 429 (honouring `Retry-After`). Opt out
with `WireBoardClient(token=token, retry_on_429=False)`. There are no
retries on 5xx or network errors — your code decides.

## Cancellation

The HTTP client uses `httpx` under the hood. To cancel a long-running
async call, cancel the surrounding task — `httpx` propagates the cancel
into the open connection:

```python
import asyncio

async def with_timeout():
    try:
        async with asyncio.timeout(5):
            await wb.urls(site_id=sid, from_=f, to=t, prefix="/checkout")
    except asyncio.TimeoutError:
        ...
```

The Live clients are cancelled via `stop()` instead — it also aborts the
in-flight snapshot fetch and JWT mint.

## Rate-limit visibility

Every successful response carries `X-RateLimit-*` headers. To read them
without an extra HTTP call, wrap the request in `with_meta`:

```python
data, rate_limit = wb.with_meta(
    lambda c: c.aggregate(site_id=sid, from_=f, to=t),
)
print(f"{rate_limit['remaining']}/{rate_limit['limit']} requests left this minute")
```

`with_meta` is safe under concurrent use; each call captures its own slot.
Calls on the outer client (not the closure's `c`) are NOT instrumented.

In async code, the callback returns an awaitable:

```python
data, rate_limit = await wb.with_meta(
    lambda c: c.aggregate(site_id=sid, from_=f, to=t),
)
```

## Browser examples

Four pages you can click through to see the SDK working against your real
account. They double as a reference implementation of the production
architecture: the Python SDK runs server-side, the browser only talks to
your server, and the bearer token never leaves the host.

```text
   Browser  ──HTTP/JSON──▶  Flask (scripts/)  ──SDK──▶  api.wireboard.io
                  ▲                ▼
                  └──── SSE ───────┘
                  (real-time state)
```

```sh
pip install -e ".[examples]"          # adds flask + python-dotenv
WIREBOARD_TOKEN=… ./scripts/serve-examples.sh
```

The server binds to the first free port in `8080–8089` and prints the URL.

| Path | What it shows |
| --- | --- |
| `/account.html` | `account()` + `sites()` |
| `/historical.html` | 7-day `aggregate()` + `breakdown(country)` + daily `history()` |
| `/live-managed.html` | A managed `LiveClient` per site, streamed to the browser over SSE — full merged state, drop signals applied, JWT rotation invisible |
| `/live-raw-multi.html` | A `LiveRawClient` across selected sites; per-site cards flash on each envelope, plus a rolling category-aware event log |

The token is loaded by the server from `WIREBOARD_TOKEN` or a `.env` file at
the repo root. Browsers see only short-lived data, never the bearer.

See [`scripts/README.md`](./scripts/README.md) for the Flask app's endpoint
list and architecture notes.

## Verify your setup

The package ships a CLI that exercises every endpoint against your real
account:

```sh
WIREBOARD_TOKEN=… wireboard-api verify
```

It hits every REST surface for a 7-day window, opens a 45 s managed Live
subscription, and prints a pass/fail summary table.

```text
WireBoard SDK verify — token …62bb  (sdk v1.0.0)
  account()                     PASS  team-owner: …  abilities: analytics:read,live:read
  sites()                       PASS  43 site(s); picked NxpRrJXr (analytics-alternative.com)
  aggregate()                   PASS  visitors=10  pageviews=22  bounce=70  dur=56s
  …
  live: stream (45s)            PASS  237 events received
                                      JWT rotation: not observed (need --duration=920 to verify)
                                      reconnects: 0
                                      errors: 0
  ──────────────────────────────────────
  SUMMARY                       PASS  11/11 surfaces
```

| Flag | Default | Notes |
| --- | --- | --- |
| `--token=TOKEN` | `$WIREBOARD_TOKEN` | API bearer; flag wins over env. |
| `--site=SITE_ID` | first from `/v1/sites` | Pin a specific site. |
| `--duration=SECONDS` | `45` | Live-stream window. Pass `>=920` to also observe a full JWT rotation cycle (mints fire at expires_in − 60 s = 840 s). |
| `--no-color` | (auto) | Strip ANSI escapes; recommended for CI logs. |

Exit code is `0` on full pass, `1` on any failure, `2` on usage error
(unknown flag, malformed value).

## Runtime targets

| Runtime | Tested | Notes |
| --- | --- | --- |
| CPython 3.10–3.13 | ✓ | Reference target |
| PyPy 3.10+ | likely | Untested but uses no CPython-only APIs |
| Async runtimes | asyncio, Trio (via `anyio`) | Whatever `httpx` supports |
| Frameworks | Django, Flask, FastAPI, Starlette, aiohttp | Just `pip install wireboard-api` |

The release was sanity-checked against production by running four
concurrent `wireboard-api verify --duration=920` sessions in parallel —
one observed a graceful JWT rotation at `+840.7 s` (the spec'd
`expires_in − 60 s`), the other three exercised the hard-reconnect path
when prod-side infra closed the connection before rotation could fire.
Zero customer-visible errors across ~62 min of combined live streaming.

## Contributing

```sh
git clone https://github.com/wireboard/api-py
cd api-py
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Quality gates (each one is also runnable in isolation):

```sh
pytest                              # 70 tests, ~17 s; includes an SSE stub-server
                                    # integration suite for rotation + reconnect
mypy --strict wireboard_api         # strict typing, no implicit Any
ruff check wireboard_api scripts/ tests/
```

To exercise the SDK against your real account:

```sh
WIREBOARD_TOKEN=… wireboard-api verify              # 45 s smoke test
WIREBOARD_TOKEN=… wireboard-api verify --duration=920   # full JWT-rotation cycle
```

To bring up the Flask browser examples locally, add the `examples` extra:

```sh
pip install -e ".[examples]"
WIREBOARD_TOKEN=… ./scripts/serve-examples.sh
```

A `.env` file at the repo root (gitignored) is auto-loaded by both the CLI
helper and the example server.

## More

- [API overview](https://wireboard.io/docs/api-overview)
- [REST reference](https://wireboard.io/docs/api-rest)
- [Live API](https://wireboard.io/docs/api-live)
- [Authentication](https://wireboard.io/docs/api-authentication)
- [Errors & limits](https://wireboard.io/docs/api-errors)

## License

[MIT](./LICENSE).
