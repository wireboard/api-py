"""Tests for date normalisation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from wireboard_api._date import to_date_string


def test_accepts_yyyy_mm_dd_string() -> None:
    assert to_date_string("2026-05-22") == "2026-05-22"


def test_rejects_malformed_strings() -> None:
    with pytest.raises(TypeError):
        to_date_string("2026-5-22")
    with pytest.raises(TypeError):
        to_date_string("22/05/2026")
    with pytest.raises(TypeError):
        to_date_string("")


def test_converts_date_to_yyyy_mm_dd() -> None:
    assert to_date_string(date(2026, 5, 22)) == "2026-05-22"


def test_converts_naive_datetime_to_yyyy_mm_dd() -> None:
    d = datetime(2026, 5, 22, 13, 26, 27)
    assert to_date_string(d) == "2026-05-22"


def test_uses_utc_for_aware_datetime() -> None:
    # 2026-05-22T23:30:00-05:00 == 2026-05-23T04:30:00Z → next UTC day
    d = datetime(2026, 5, 22, 23, 30, 0, tzinfo=timezone(_offset_hours(-5)))
    assert to_date_string(d) == "2026-05-23"


def test_rejects_non_date_input() -> None:
    with pytest.raises(TypeError):
        to_date_string(42)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_date_string(None)  # type: ignore[arg-type]


# Helper: a fixed-offset timedelta. We avoid `zoneinfo` because Python 3.10
# CI images sometimes ship without the tzdata package; ``timedelta`` is
# stdlib everywhere.
def _offset_hours(h: int) -> timedelta:
    return timedelta(hours=h)
