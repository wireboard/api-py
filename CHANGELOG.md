# Changelog

All notable changes to `wireboard-api` (Python) will be documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
