# Changelog

All notable changes to `wireboard-api` (Python) will be documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] — 2026-05-27

### Security
- Live subscriber JWTs are now sent in the `Authorization: Bearer` header
  on the SSE handshake instead of as an `?authorization=<jwt>` URL query
  parameter. The previous behavior allowed the short-lived (`live:read`,
  ~15 min) token to be captured in any log that records request URIs —
  reverse-proxy access logs, the Mercure hub's own logs, and any
  customer-side error reporter (e.g. Sentry) that records the httpx
  request URL when an exception surfaces via `on_error`. TLS continued
  to protect the JWT on the wire; the leak surface was log persistence
  at TLS terminators. Operators who shipped hub access logs to a SIEM
  or third-party aggregator should grep retained logs for
  `authorization=` in URI fields to estimate exposure.
- The SDK now rejects non-`https` hub URLs returned by `/v1/live/token`
  unless the host is a loopback address (so local dev stubs still
  work). Defense in depth against a misconfigured or downgraded hub.
- `Retry-After` values from `429` responses are now clamped to
  `[0, 60]` seconds. A buggy or hostile upstream returning a very large
  value can no longer stall the client indefinitely.

## [1.0.1] — 2026-05-24

### Added
- Two typed error subclasses for plan-gating responses introduced by the
  backend on 2026-05-24:
  - `PlanHistoryLimitExceededError` (extends `WireBoardApiError`,
    `http_status: 422`). Raised on `/v1/analytics/*` endpoints when a
    free-plan caller passes a `from_` older than 30 days. Exposes
    `earliest_allowed: str | None` (parsed from
    `field_errors["earliest_allowed"]`) so callers can auto-correct the
    range or prompt for an upgrade.
  - `PaidPlanRequiredError` (extends `WireBoardApiError`,
    `http_status: 403`). Raised on the entire Live API
    (`/v1/live/token`, `/v1/live/state`) for free-plan callers.

### Changed
- Transport now classifies 403 responses by their `error_code` before
  falling back to the generic auth-vs-api decision. Previously, any
  `403` produced a `WireBoardAuthError`, which stripped the
  `error_code` and `field_errors`, leaving plan-gating errors
  indistinguishable from genuine auth failures. The new
  `PaidPlanRequiredError` preserves both fields and is deliberately
  NOT a subclass of `WireBoardAuthError`, so customers won't push
  affected users through a re-login flow when an upgrade prompt is
  the correct response.
- Both new subclasses extend `WireBoardApiError`, so existing
  `except WireBoardApiError:` blocks continue to match. Order your
  exception handlers specific-to-general to leverage the new types.

## [1.0.0] — 2026-05-23

Initial release. Mirrors the surface of the official TypeScript SDK
([`@wireboard/api`](https://www.npmjs.com/package/@wireboard/api)).

- Sync `WireBoardClient` and async `AsyncWireBoardClient`.
- All REST endpoints: `account`, `sites`, `aggregate`, `timeseries`,
  `history`, `breakdown`, `urls`, `events`, `dimensions`.
- Low-level Live access: `live_state`, `live_token`.
- Managed Live mode (`live(...)`): SDK handles snapshot, drop-signal merge,
  zero-gap JWT rotation, hard-reconnect with snapshot refetch.
- Raw Live mode (`live_raw(...)`): multi-site, customer-owned state.
- Auto-retry once on `429` honouring `Retry-After`.
- Rate-limit visibility via `with_meta(...)`.
- `wireboard-api verify` CLI: exercises every endpoint against a real
  account, prints pass/fail summary, exit code `0`/`1`/`2`.
