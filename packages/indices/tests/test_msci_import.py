"""Tests for the MSCI index-level file parser (index-levels fast-follow). DB-free."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from indices.msci import (
    fetch_msci_levels,
    msci_xref_value,
    parse_msci_graph_json,
    parse_msci_rows,
    variant_code,
)


def _rows(text: str) -> list[list[str]]:
    return [list(r) for r in csv.reader(io.StringIO(text))]


_MSCI_CSV = """MSCI WORLD Index (USD) Net
Data as of close of business
,
Date,MSCI WORLD
"May 30, 2024","3,456.78"
"May 31, 2024","3,460.12"
"Jun 03, 2024","3,475.00"
Source: MSCI. All rights reserved.
"""


def test_parses_msci_export_skipping_preamble_and_footer():
    series = parse_msci_rows(_rows(_MSCI_CSV))
    assert series == [
        (date(2024, 5, 30), Decimal("3456.78")),
        (date(2024, 5, 31), Decimal("3460.12")),
        (date(2024, 6, 3), Decimal("3475.00")),
    ]


def test_handles_iso_dates_and_plain_values():
    text = "Date,Value\n2024-01-02,100.5\n2024-01-03,101.25\n"
    assert parse_msci_rows(_rows(text)) == [
        (date(2024, 1, 2), Decimal("100.5")),
        (date(2024, 1, 3), Decimal("101.25")),
    ]


def test_no_date_header_yields_empty():
    assert parse_msci_rows(_rows("Foo,Bar\n1,2\n")) == []


def test_skips_unparseable_and_nonpositive_levels():
    text = 'Date,Idx\n2024-01-02,\n2024-01-03,0\n2024-01-04,"1,234.5"\n'
    assert parse_msci_rows(_rows(text)) == [(date(2024, 1, 4), Decimal("1234.5"))]


# --- direct MSCI EOD pull (getLevelDataForGraph) -------------------------------------------------

def test_variant_code_maps_pr_nr_gr():
    assert variant_code("PR") == "STRD"
    assert variant_code("NR") == "NETR"
    assert variant_code("GR") == "GRTR"
    assert variant_code("nr") == "NETR"  # case-insensitive
    with pytest.raises(ValueError):
        variant_code("TR")


def test_msci_xref_value_encodes_variant():
    # PR/NR/GR of one index must resolve to DISTINCT instruments (variant was dropped from the
    # row dimension), so the msci xref encodes the variant.
    assert msci_xref_value("990100", "NR") == "990100:NETR"
    assert msci_xref_value("990100", "PR") != msci_xref_value("990100", "NR")


def test_parse_graph_json_extracts_series():
    payload = {
        "msci_index_code": "990100", "index_variant_type": "NETR", "ISO_currency_symbol": "USD",
        "indexes": {"INDEX_LEVELS": [
            {"level_eod": 2487.6134344967827, "calc_date": 20001229},
            {"level_eod": 2448.197151650023, "calc_date": 20010102},
            {"level_eod": 0, "calc_date": 20010103},  # non-positive -> dropped
            {"level_eod": None, "calc_date": 20010104},  # missing -> dropped
        ]},
    }
    assert parse_msci_graph_json(payload) == [
        (date(2000, 12, 29), Decimal("2487.6134344967827")),
        (date(2001, 1, 2), Decimal("2448.197151650023")),
    ]


def test_parse_graph_json_raises_on_msci_error():
    # MSCI returns an error_code (e.g. " 100" with a leading space) for bad params.
    payload = {"error_code": " 100", "error_message": " null Invalid Parameter start_date"}
    with pytest.raises(ValueError, match="MSCI error 100"):
        parse_msci_graph_json(payload)


def test_parse_graph_json_treats_zero_error_code_as_success():
    # "0"/0 is a common success sentinel — must NOT raise; the levels still parse.
    payload = {
        "error_code": "0", "error_message": "",
        "indexes": {"INDEX_LEVELS": [{"level_eod": 100.0, "calc_date": 20240102}]},
    }
    assert parse_msci_graph_json(payload) == [(date(2024, 1, 2), Decimal("100.0"))]


def test_parse_graph_json_empty_levels_ok():
    assert parse_msci_graph_json({"indexes": {"INDEX_LEVELS": []}}) == []


def test_fetch_msci_levels_clamps_floor_and_uses_injected_fetcher():
    captured = {}

    def fake_fetch(url: str) -> dict:
        captured["url"] = url
        return {"indexes": {"INDEX_LEVELS": [{"level_eod": 100.0, "calc_date": 20240102}]}}

    out = fetch_msci_levels(
        msci_code="990100", variant="NR", currency="USD",
        start_date=date(1969, 1, 1), end_date=date(2024, 1, 2), _fetch_json=fake_fetch,
    )
    assert out == [(date(2024, 1, 2), Decimal("100.0"))]
    # start clamped to the 1997 floor; variant mapped to NETR; daily frequency
    assert "start_date=19970101" in captured["url"]
    assert "index_variant=NETR" in captured["url"]
    assert "index_codes=990100" in captured["url"]
    assert "data_frequency=DAILY" in captured["url"]
