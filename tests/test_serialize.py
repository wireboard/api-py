"""Tests for query-parameter serialization."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from wireboard_api._serialize import serialize_params


def _encoded(params: dict) -> str:
    return urlencode(serialize_params(params))


def _decoded(params: dict) -> str:
    from urllib.parse import unquote

    return unquote(_encoded(params))


def test_serialises_scalar_fields() -> None:
    out = serialize_params({"site_id": "xK4mP2nT", "limit": 50})
    assert ("site_id", "xK4mP2nT") in out
    assert ("limit", "50") in out


def test_normalises_dates_in_from_to() -> None:
    decoded = _decoded(
        {
            "site_id": "xK4mP2nT",
            "from": date(2026, 5, 1),
            "to": "2026-05-22",
        }
    )
    assert "from=2026-05-01" in decoded
    assert "to=2026-05-22" in decoded


def test_from_underscore_maps_to_wire_from() -> None:
    """`from_=` is the Python kwarg; the wire key is `from`."""
    decoded = _decoded({"from_": "2026-05-01", "to": "2026-05-22"})
    assert "from=2026-05-01" in decoded
    assert "from_=" not in decoded


def test_serialises_arrays_as_comma_separated() -> None:
    decoded = _decoded({"group_by": ["category", "utm_source"]})
    assert "group_by=category,utm_source" in decoded


def test_serialises_event_filter_columns() -> None:
    decoded = _decoded(
        {"filter": {"category": "Purchase", "utm_source": "newsletter"}}
    )
    assert "filter[category]=Purchase" in decoded
    assert "filter[utm_source]=newsletter" in decoded


def test_serialises_event_prop_filters() -> None:
    decoded = _decoded({"filter": {"props": {"plan": "pro", "tier": "gold"}}})
    assert "filter[props.plan]=pro" in decoded
    assert "filter[props.tier]=gold" in decoded


def test_skips_none_values() -> None:
    out = serialize_params({"a": "x", "b": None, "c": None, "d": 1})
    keys = [k for k, _ in out]
    assert keys == ["a", "d"]


def test_encodes_special_characters_in_filter_values() -> None:
    # url-decode the encoded output to verify special chars round-trip
    decoded = _decoded({"filter": {"category": "a&b=c"}})
    assert "filter[category]=a&b=c" in decoded


def test_booleans_render_lowercase() -> None:
    out = dict(serialize_params({"flag_on": True, "flag_off": False}))
    assert out["flag_on"] == "true"
    assert out["flag_off"] == "false"
