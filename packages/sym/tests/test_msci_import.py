"""Tests for the MSCI index-level file parser (Benchmark fast-follow). DB-free."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from sym.benchmarks.msci import parse_msci_rows


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
