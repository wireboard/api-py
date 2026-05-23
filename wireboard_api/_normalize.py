"""Boundary normalisation for non-canonical server response shapes.

Currently only handles ``GET /v1/live/state``: the production server returns
``live`` as an array of ``{category, ts, data}`` envelopes, while the public
spec documents a ``{ category: data, ... }`` map. The SDK accepts either
shape at the boundary and normalises to the documented map so customer code
and merge logic always see one shape.
"""

from __future__ import annotations

from typing import Any


def normalize_live_state_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    """If ``raw["live"]`` is a list of envelopes, fold it into a per-category
    map. If it's already a dict, return the snapshot unchanged.
    """
    live = raw.get("live")
    if not isinstance(live, list):
        return raw
    folded: dict[str, Any] = {}
    for env in live:
        if not isinstance(env, dict):
            continue
        cat = env.get("category")
        if cat is None:
            continue
        folded[cat] = env.get("data")
    return {**raw, "live": folded}
