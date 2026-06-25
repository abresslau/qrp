"""Tests for the Wikipedia index source + revision-diff engine (Story U2.3). DB-free."""

from __future__ import annotations

from datetime import date

import pytest

from universe.providers.index_source import IndexSourceError
from universe.providers.wikipedia import (
    WikipediaIndexSource,
    parse_wikitables,
    revision_diff,
    split_yahoo_suffix,
)
from universe.registry import EXACT, JOIN, LEAVE, POLL_BOUNDED

_CONSTITUENTS_HTML = """
<table class="wikitable sortable" id="constituents">
<tr><th>Symbol</th><th>Security</th><th>Date added</th></tr>
<tr><td><a href="/x">MMM</a></td><td>3M</td><td>1976-08-09</td></tr>
<tr><td><a href="/x">AOS</a><sup class="reference">[1]</sup></td><td>A. O. Smith</td>
<td>2017-07-26</td></tr>
<tr><td>BRK.B</td><td>Berkshire</td><td></td></tr>
</table>
<table class="wikitable">
<tr><th colspan="2">Added</th><th colspan="2">Removed</th><th>Reason</th></tr>
<tr><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th><th></th></tr>
<tr><td>2023-03-15</td><td>NEW</td><td>NewCo</td><td>OLD</td><td>OldCo</td><td>M&amp;A</td></tr>
</table>
"""


class _FakeWiki:
    def __init__(self, html):
        self._html = html

    def page_html(self, title):
        return self._html


def test_parse_wikitables_extracts_rows_and_strips_refs():
    tables = parse_wikitables(_CONSTITUENTS_HTML)
    assert len(tables) == 2
    # header + 3 data rows in the constituents table
    assert tables[0][0][0] == "Symbol"
    assert tables[0][2][0] == "AOS"  # the [1] reference is stripped


def test_current_constituents_use_real_date_added():
    src = WikipediaIndexSource(_FakeWiki(_CONSTITUENTS_HTML))
    changes = src.fetch("sp500", date(2000, 1, 1), date(2024, 6, 1))
    mmm = next(c for c in changes if c.raw_identifier == "ticker:MMM@XNYS")
    assert mmm.change == JOIN and mmm.effective_date == date(1976, 8, 9)
    assert mmm.effective_date_precision == EXACT


def test_missing_date_added_falls_back_to_poll_bounded():
    src = WikipediaIndexSource(_FakeWiki(_CONSTITUENTS_HTML))
    changes = src.fetch("sp500", date(2000, 1, 1), date(2024, 6, 1))
    brk = next(c for c in changes if c.raw_identifier == "ticker:BRK.B@XNYS")
    assert brk.effective_date == date(2024, 6, 1)
    assert brk.effective_date_precision == POLL_BOUNDED


def test_changes_table_yields_dated_join_and_leave():
    src = WikipediaIndexSource(_FakeWiki(_CONSTITUENTS_HTML))
    changes = src.fetch("sp500", date(2000, 1, 1), date(2024, 6, 1))
    join = next(c for c in changes if c.raw_identifier == "ticker:NEW@XNYS")
    leave = next(c for c in changes if c.raw_identifier == "ticker:OLD@XNYS")
    assert join.change == JOIN and join.effective_date == date(2023, 3, 15)
    assert leave.change == LEAVE and leave.effective_date == date(2023, 3, 15)


def test_empty_page_is_loud_error():
    src = WikipediaIndexSource(_FakeWiki("<p>nothing here</p>"))
    with pytest.raises(IndexSourceError):
        src.fetch("sp500", date(2000, 1, 1), date(2024, 6, 1))


def test_unknown_index_raises():
    src = WikipediaIndexSource(_FakeWiki(_CONSTITUENTS_HTML))
    with pytest.raises(IndexSourceError):
        src.fetch("nikkei", date(2000, 1, 1), date(2024, 6, 1))


# --- European Yahoo-suffix handling -----------------------------------------


def test_split_yahoo_suffix_maps_exchange():
    assert split_yahoo_suffix("ADS.DE", "XETR") == ("ADS", "XETR")
    assert split_yahoo_suffix("AIR.PA", "XETR") == ("AIR", "XPAR")  # suffix overrides default
    assert split_yahoo_suffix("NESN.SW", "XSWX") == ("NESN", "XSWX")


def test_split_yahoo_suffix_keeps_share_class_dot():
    # .A is a share class, not an exchange suffix → ticker kept, default MIC used.
    assert split_yahoo_suffix("BT.A", "XLON") == ("BT.A", "XLON")


def test_split_yahoo_suffix_no_dot():
    assert split_yahoo_suffix("III", "XLON") == ("III", "XLON")


def test_european_constituents_resolve_each_to_home_venue():
    html = """
    <table class="wikitable">
    <tr><th>Ticker</th><th>Name</th></tr>
    <tr><td>ADS.DE</td><td>Adidas</td></tr>
    <tr><td>AIR.PA</td><td>Airbus</td></tr>
    </table>
    """
    src = WikipediaIndexSource(_FakeWiki(html), {"x": {"title": "X", "mic": "XETR",
                                                       "yahoo_suffix": True}})
    changes = src.fetch("x", date(2024, 1, 1), date(2024, 6, 1))
    tokens = {c.raw_identifier for c in changes}
    assert "ticker:ADS@XETR" in tokens  # German
    assert "ticker:AIR@XPAR" in tokens  # French — suffix routed it to Paris


# --- revision-diff engine ---------------------------------------------------


def test_revision_diff_seeds_then_diffs():
    snaps = [
        (date(2020, 1, 1), {"ticker:A@XNYS", "ticker:B@XNYS"}),
        (date(2021, 1, 1), {"ticker:B@XNYS", "ticker:C@XNYS"}),
    ]
    changes = revision_diff(snaps)
    kinds = {(c.raw_identifier, c.change, c.effective_date) for c in changes}
    assert ("ticker:A@XNYS", JOIN, date(2020, 1, 1)) in kinds  # seed
    assert ("ticker:B@XNYS", JOIN, date(2020, 1, 1)) in kinds  # seed
    assert ("ticker:C@XNYS", JOIN, date(2021, 1, 1)) in kinds  # joiner
    assert ("ticker:A@XNYS", LEAVE, date(2021, 1, 1)) in kinds  # leaver
    assert all(c.effective_date_precision == POLL_BOUNDED for c in changes)


def test_revision_diff_normalizes_so_format_drift_is_not_a_change():
    # Already-normalized tokens; a BRK.B that becomes BRK-B upstream must dedupe.
    from universe.membership_diff import ticker_token

    snaps = [
        (date(2020, 1, 1), {ticker_token("BRK.B", "XNYS")}),
        (date(2021, 1, 1), {ticker_token("BRK-B", "XNYS")}),
    ]
    changes = revision_diff(snaps)
    # Only the seed join; no leave+rejoin from the separator drift.
    assert len([c for c in changes if c.effective_date == date(2021, 1, 1)]) == 0
