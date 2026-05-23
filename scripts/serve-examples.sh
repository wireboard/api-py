#!/usr/bin/env bash
# scripts/serve-examples.sh
#
# Boots a local Flask app that wraps the wireboard_api SDK and serves the
# four browser example pages on a free localhost port. Open the printed URL
# in a browser and click through.
#
# Requires:
#   - WIREBOARD_TOKEN in the environment or in .env at the repo root
#   - The package + the `examples` extra installed in the active venv:
#         pip install -e ".[examples]"
#
# Press Ctrl+C to stop.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ─── load .env if WIREBOARD_TOKEN is not already set ────────────────────────
if [[ -z "${WIREBOARD_TOKEN:-}" && -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

if [[ -z "${WIREBOARD_TOKEN:-}" ]]; then
  echo "error: WIREBOARD_TOKEN is not set." >&2
  echo "       Export it, or add WIREBOARD_TOKEN='…' to .env at the repo root." >&2
  exit 1
fi

# ─── pick the right python ──────────────────────────────────────────────────
PY="python3"
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
fi

# ─── ensure flask is installed ──────────────────────────────────────────────
if ! "$PY" -c 'import flask' >/dev/null 2>&1; then
  echo "error: flask is not installed in $PY." >&2
  echo "       Run:  $PY -m pip install -e \".[examples]\"" >&2
  exit 1
fi

# ─── run ────────────────────────────────────────────────────────────────────
exec "$PY" scripts/serve_examples.py "$@"
