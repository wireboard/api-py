# Browser example server

A small Flask app that wraps the installed `wireboard_api` SDK and serves
four HTML pages so you can click through and visually verify the SDK
against your real account.

This is also the reference implementation of the
**server-proxied-token** architecture the SDK docs recommend for production:
the Python SDK runs server-side, the browser only talks to your server, and
the long-lived bearer token never leaves the host.

## Run

```sh
pip install -e ".[examples]"           # adds flask + python-dotenv
WIREBOARD_TOKEN=… ./scripts/serve-examples.sh
```

The wrapper script loads `WIREBOARD_TOKEN` from a `.env` file at the repo
root if it isn't already exported, finds a free port in `8080–8089`, and
starts the Flask app. The startup banner prints the URL and the list of
pages.

You can also run the Python entry point directly:

```sh
WIREBOARD_TOKEN=… python scripts/serve_examples.py --port=8080
```

## Architecture

```text
                        wireboard_api SDK
   ┌──────────────────┐ (sync WireBoardClient
   │ scripts/         │  + LiveClient        )       ┌─────────────────────┐
   │   serve_examples │ ────────────────────────────▶│ api.wireboard.io    │
   │   .py            │ ◀────── HTTP / SSE ──────────│ (REST + SSE stream) │
   └──────────────────┘                              └─────────────────────┘
        ▲      │
   HTTP │      │  text/event-stream
   /JSON│      ▼
   ┌──────────────────┐
   │ Browser pages    │
   │ (HTML + vanilla  │
   │  JS in static/)  │
   └──────────────────┘
```

- The Flask app holds one `WireBoardClient` for REST and, per request,
  starts a managed `LiveClient` or `LiveRawClient` from the SDK.
- The Live pages open an `EventSource` to a Flask SSE endpoint
  (`/api/live-stream`, `/api/multi-stream`). Flask subscribes a
  per-request `queue.Queue` to the SDK's `on_change` / `on_event`
  callback and re-emits each update as `data: <json>\n\n`.
- When the browser closes the EventSource, the generator's `finally`
  block runs, unsubscribes the queue, and — if it was the last
  subscriber — stops the underlying SDK client. So switching sites in a
  tab doesn't pile up live subscriptions toward the team-wide cap of 10.

The same token-handling pattern works under FastAPI, Starlette, Django,
aiohttp, or any other Python web framework — only the route handlers
change.

## Pages

| Path | Backed by | Demonstrates |
| --- | --- | --- |
| `/` | `static/index.html` | Nav landing page |
| `/account.html` | `wb.account()` + `wb.sites()` | Authentication, account identity, site list |
| `/historical.html` | `wb.aggregate()`, `wb.breakdown()`, `wb.history()` | 7-day window with the three main historical surfaces |
| `/live-managed.html` | `wb.live(site_id=…)` | Managed mode: SDK owns the merged state, browser renders it. Drop signals applied server-side, JWT rotation invisible. |
| `/live-raw-multi.html` | `wb.live_raw(sites=[…])` | Raw mode: per-site cards, fresh-event highlight, category-aware rolling log |

## JSON / SSE endpoints

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/account` | `Account` payload |
| `GET` | `/api/sites` | `SitesResult` |
| `GET` | `/api/today` | Convenience: `{from, to}` for a 7-day UTC window |
| `GET` | `/api/aggregate?site_id&from&to` | `AggregateResult` |
| `GET` | `/api/breakdown?site_id&from&to&dimension[&limit]` | `BreakdownResult` |
| `GET` | `/api/history?site_id&from&to` | `HistoryResult` |
| `GET` | `/api/live-stream?site_id` | `text/event-stream` — managed-mode merged state on every change |
| `GET` | `/api/multi-stream?sites=A,B,C` | `text/event-stream` — `event: ready` then one envelope per `data:` line |

Errors from the SDK are surfaced as JSON `{error, code?, http_status,
field_errors?, rate_limit?}` with the matching HTTP status code.

## Files

```
scripts/
├── serve-examples.sh          bash wrapper (.env load + flask check + free port)
├── serve_examples.py          Flask app (300 lines, mypy --strict + ruff clean)
└── static/
    ├── style.css              shared stylesheet
    ├── index.html             nav landing
    ├── account.html
    ├── historical.html
    ├── live-managed.html      EventSource → /api/live-stream
    └── live-raw-multi.html    EventSource → /api/multi-stream, with chip selector
```

## Requirements

- Python 3.10+
- The `examples` extra (`pip install -e ".[examples]"` from a checkout, or
  `pip install "wireboard-api[examples]"` once published).
- A WireBoard token with both `analytics:read` and `live:read` abilities
  for the Live pages.

## See also

- [`../examples/`](../examples/) — standalone scripted snippets without
  the web layer.
- [Main README](../README.md) — full API reference and Live-mode docs.
