"""Serialise a Python ``dict`` of request params into URL query params.

Handles:
    - ``from`` / ``to`` date-or-string normalisation,
    - the Python keyword-conflict workaround ``from_`` → ``from``,
    - array params (comma-joined, matching the JS SDK),
    - the ``filter`` event-filter shape
      (``filter[<col>]=...`` and ``filter[props.<key>]=...``),
    - skipping ``None`` values.
"""

from __future__ import annotations

from typing import Any

from ._date import to_date_string

_DATE_KEYS = {"from", "to"}


def _wire_key(k: str) -> str:
    """Map Python kwargs to wire-level param names.

    ``from`` is reserved in Python, so callers pass ``from_=...``. We strip
    the trailing underscore at the wire boundary.
    """
    if k.endswith("_") and not k.endswith("__"):
        return k[:-1]
    return k


def serialize_params(params: dict[str, Any]) -> list[tuple[str, str]]:
    """Return a list of ``(key, value)`` pairs ready to hand to httpx as the
    ``params=`` argument. List form (rather than ``dict``) preserves order
    and supports duplicate keys, matching the JS SDK's :class:`URLSearchParams`.
    """
    out: list[tuple[str, str]] = []
    for raw_key, value in params.items():
        if value is None:
            continue
        key = _wire_key(raw_key)

        if key == "filter" and isinstance(value, dict):
            _serialize_event_filter(value, out)
            continue

        if key in _DATE_KEYS:
            out.append((key, to_date_string(value)))
            continue

        if isinstance(value, (list, tuple)):
            out.append((key, ",".join(str(v) for v in value)))
            continue

        if isinstance(value, bool):
            out.append((key, "true" if value else "false"))
            continue

        out.append((key, str(value)))
    return out


def _serialize_event_filter(
    filter_: dict[str, Any],
    out: list[tuple[str, str]],
) -> None:
    for k, v in filter_.items():
        if v is None:
            continue
        if k == "props" and isinstance(v, dict):
            for pk, pv in v.items():
                if pv is None:
                    continue
                out.append((f"filter[props.{pk}]", str(pv)))
            continue
        out.append((f"filter[{k}]", str(v)))
