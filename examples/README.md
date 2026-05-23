# Examples

Single-purpose, copy-pasteable snippets demonstrating `wireboard-api` in
each style. Each file is self-contained and uses only the SDK's public
surface — no helpers, no internal imports.

```
examples/
├── quickstart.py              Sync · smallest useful example
├── quickstart_async.py        Async · same, with the async client
├── managed_live.py            Sync · managed Live mode for one site
├── managed_live_async.py      Async · managed Live mode for one site
└── raw_multi_site.py          Sync · raw Live across the first 3 sites
```

For a browser-renderable demo — Flask server + four HTML pages, real-time
SSE bridge for the Live tabs — see [`scripts/`](../scripts/) instead. The
snippets here are the building blocks; `scripts/` shows them assembled.

## Run

Install the package and export your token:

```sh
pip install wireboard-api
export WIREBOARD_TOKEN=…

python examples/quickstart.py
python examples/quickstart_async.py
python examples/managed_live.py
python examples/managed_live_async.py
python examples/raw_multi_site.py
```

| File | What it shows |
| --- | --- |
| [`quickstart.py`](./quickstart.py) | Authenticate, print account + first 5 sites — synchronous |
| [`quickstart_async.py`](./quickstart_async.py) | Same, using `AsyncWireBoardClient` inside `asyncio.run` |
| [`managed_live.py`](./managed_live.py) | Subscribe to one site; SDK handles snapshot + drop signals + JWT rotation |
| [`managed_live_async.py`](./managed_live_async.py) | Same, inside an `async with` block |
| [`raw_multi_site.py`](./raw_multi_site.py) | One SSE connection across up to 3 sites; per-site envelope counters |

## Token safety

These snippets take the bearer token directly from `WIREBOARD_TOKEN` so they
stay short. **Never ship that token to the browser.** Anyone with it has
full read access to your analytics for as long as it exists.

For browser apps, the correct pattern is:

1. Your Python server holds the long-lived bearer token.
2. When a browser session needs Live data, your server calls
   [`live_token()`](https://wireboard.io/docs/api-live#mint-jwt) and returns
   the short-lived (15 min) JWT to the browser.
3. The browser opens an `EventSource` to the returned `hub_url` with the JWT
   as a query param.
4. When the JWT expires, the browser asks your server for a fresh one.

The Flask app in [`../scripts/`](../scripts/) is the reference
implementation of exactly that pattern — the bearer stays on the server,
the browser only talks to JSON / SSE endpoints, and you can copy the
relevant route handlers straight into your own FastAPI / Django / Flask
project.

## More

- [Main README](../README.md) — install, full quickstart, API reference table
- [`../scripts/`](../scripts/) — browser-renderable Flask demo
- [API overview](https://wireboard.io/docs/api-overview)
- [REST reference](https://wireboard.io/docs/api-rest)
- [Live API](https://wireboard.io/docs/api-live)
- [Authentication](https://wireboard.io/docs/api-authentication)
- [Errors & limits](https://wireboard.io/docs/api-errors)
