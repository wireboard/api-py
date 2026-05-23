"""Date normalisation for ``from``/``to`` parameters."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import TypeAlias

#: One of:
#:
#: - A ``YYYY-MM-DD`` string (interpreted as UTC by the server).
#: - A :class:`datetime.date`.
#: - A timezone-aware :class:`datetime.datetime` — converted to UTC, then the
#:   calendar day is taken.
#: - A *naive* :class:`datetime.datetime` — used as-is. If you want "today in
#:   UTC", pass ``datetime.now(datetime.timezone.utc)`` (not the deprecated
#:   ``datetime.utcnow()``, and not the naive ``datetime.now()``, which uses
#:   the system local clock and can land you on a different calendar day).
DateInput: TypeAlias = str | date | datetime

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def to_date_string(d: DateInput) -> str:
    """Normalise a date input to ``YYYY-MM-DD``.

    Raises :class:`TypeError` if ``d`` is not a string in the expected format,
    a ``date``, or a ``datetime``.
    """
    if isinstance(d, str):
        if not _DATE_RE.match(d):
            raise TypeError(f'Invalid date string: "{d}". Expected YYYY-MM-DD.')
        return d
    # ``datetime`` is a subclass of ``date`` — check it first so we can handle
    # tz-aware conversion separately from the plain-date path below.
    if isinstance(d, datetime):
        if d.tzinfo is not None:
            d = d.astimezone(timezone.utc)
        # Naive datetime: use the calendar day as-is. See :data:`DateInput`
        # for the rationale on caller-supplied tz handling.
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    raise TypeError(f"Invalid date input: {d!r}")
