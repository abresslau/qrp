"""Tests for the fact_returns PR+TR loader (Stories 3.4/3.5). Pure, no DB."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from sym.returns.loader import (
    compute_return_rows,
    input_hash,
    total_return_index,
)
from sym.returns.windows import BY_CODE, WINDOWS

SESSIONS = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
ADJ = {
    date(2024, 1, 2): Decimal("100"),
    date(2024, 1, 3): Decimal("110"),
    date(2024, 1, 4): Decimal("121"),
}


def _rows(adj, tri, as_of_date=date(2024, 1, 4)):
    return {
        r.window_id: r
        for r in compute_return_rows("BBG000B9XRY4", [as_of_date], adj, tri, SESSIONS, 53)
    }


def test_one_row_per_window_with_pr_and_tr():
    rows = _rows(ADJ, ADJ)
    assert len(rows) == len(WINDOWS) == 28
    assert rows[BY_CODE["1D"].id].pr == Decimal("0.1")  # 121/110 - 1


def test_insufficient_history_is_null_for_both():
    row = _rows(ADJ, ADJ)[BY_CODE["1Y"].id]  # 1Y base precedes history
    assert row.pr is None and row.tr is None


# --- total-return index (EXDATE_C) ------------------------------------------


def _price_rows(closes):
    # (date, close_raw, adj_close) -- raw == adj here (no splits)
    return [(d, Decimal(str(c)), Decimal(str(c))) for d, c in closes]


def test_no_dividends_tri_equals_price():
    rows = _price_rows([(date(2024, 1, 2), 100), (date(2024, 1, 3), 110)])
    tri = total_return_index(rows, {})
    # TRI ratio == price ratio when there are no dividends
    assert tri[date(2024, 1, 3)] / tri[date(2024, 1, 2)] == Decimal("110") / Decimal("100")


def test_dividend_lifts_the_index_above_price():
    rows = _price_rows([(date(2024, 1, 2), 100), (date(2024, 1, 3), 100)])  # flat price
    tri = total_return_index(rows, {date(2024, 1, 3): Decimal("2")})  # $2 div ex 1/3
    # flat price but a 2% ex-date yield -> TRI up ~2%
    assert tri[date(2024, 1, 3)] / tri[date(2024, 1, 2)] == Decimal("1.02")


def test_dividend_reinvested_on_split_consistent_basis():
    # yfinance reports dividends in TODAY's split basis, and adj_close is also today-basis
    # (close_raw / future-split product). The ex-date yield must use the SAME basis on top
    # and bottom. Here close_raw=10 (historical) but adj_close=20 (a later reverse split
    # doubled the per-share basis), and the $2 dividend is today-basis. True yield is
    # 2/20 = 10% (== historical 1/10), NOT 2/10 = 20%. Mixing bases inflates the
    # reinvestment by the split factor -- the GE 30Y total-return bug.
    rows = [
        (date(2024, 1, 2), Decimal("10"), Decimal("20")),
        (date(2024, 1, 3), Decimal("10"), Decimal("20")),
    ]
    tri = total_return_index(rows, {date(2024, 1, 2): Decimal("2")})
    # growth = 1 + 2/20 = 1.10; TRI = adj_close * growth = 20 * 1.10 = 22.
    assert tri[date(2024, 1, 2)] == Decimal("22")


def test_no_dividends_tr_equals_pr_in_rows():
    rows = _rows(ADJ, ADJ)  # tri == adj
    for r in rows.values():
        assert r.tr == r.pr  # AC #2


def test_dividend_payer_tr_exceeds_pr():
    # build a TRI that grew faster than adj (dividends) over the 1D window
    tri = {date(2024, 1, 3): Decimal("112"), date(2024, 1, 4): Decimal("124")}
    rows = _rows(ADJ, {**ADJ, **tri})
    one_d = rows[BY_CODE["1D"].id]
    assert one_d.tr > one_d.pr  # AC #3


# --- anomaly gate (AR-9 gate half) ------------------------------------------


def test_asof_flagged_gates_all_windows():
    rows = compute_return_rows(
        "BBG000B9XRY4", [date(2024, 1, 4)], ADJ, ADJ, SESSIONS, 53,
        gated_dates={date(2024, 1, 4)},  # the as_of_date price is flagged unreviewed
    )
    assert all(r.gated and r.pr is None and r.tr is None for r in rows)


def test_base_flagged_gates_that_window():
    rows = {
        r.window_id: r
        for r in compute_return_rows(
            "BBG000B9XRY4", [date(2024, 1, 4)], ADJ, ADJ, SESSIONS, 53,
            gated_dates={date(2024, 1, 3)},  # the 1D base is flagged
        )
    }
    one_d = rows[BY_CODE["1D"].id]  # base = 2024-01-03 -> gated
    assert one_d.gated and one_d.pr is None


def test_no_flags_means_not_gated():
    rows = compute_return_rows("BBG000B9XRY4", [date(2024, 1, 4)], ADJ, ADJ, SESSIONS, 53)
    assert not any(r.gated for r in rows)
    assert rows[0].pr is not None  # 1D computes normally


# --- input_hash -------------------------------------------------------------


def test_input_hash_deterministic_and_sensitive():
    args = (53, date(2023, 1, 3), date(2024, 1, 4), Decimal("100"), Decimal("121"))
    a = input_hash(*args, Decimal("100"), Decimal("130"))
    b = input_hash(*args, Decimal("100"), Decimal("130"))
    c = input_hash(*args, Decimal("100"), Decimal("131"))  # TRI change (dividend) -> dirty
    assert a == b and a != c


def test_input_hash_handles_nulls():
    assert input_hash(53, None, date(2024, 1, 4), None, None, None, None)


def test_input_hash_format_is_pinned():
    # Golden digest: the hash payload format (field order + separators) is a stable
    # contract -- it decides the dirty-set skip across 9M+ fact_returns rows. Any
    # reorder/rename of the payload silently re-hashes everything and forces a full
    # rewrite; this pins it so such a change fails loudly instead. (Also guards the
    # AC#5 "windows 1-18 byte-identical" invariant: end==as_of_date for non-period windows,
    # so a non-period row's hash must equal what this fixed input produces.)
    h = input_hash(
        53, date(2023, 1, 3), date(2024, 1, 4),
        Decimal("100"), Decimal("121"), Decimal("100"), Decimal("130"),
    )
    assert h == "f6627aad82b359902f7e85952da70905efece97da2361145d67b40df39e656e4"


# --- anti-drift: migration seed matches windows.py --------------------------


def test_return_window_seed_matches_windows_py():
    # The seed is built across migrations: windows are INSERTed (with window_id+code)
    # and some are later renamed by `UPDATE ... SET code='X' ... WHERE window_id=N`.
    # Reconstruct the final window_id->code map from both, in plan order, so this
    # anti-drift check stays exact as windows are added or relabelled.
    deploy = Path(__file__).resolve().parents[1] / "migrations/deploy"
    plan = (deploy.parent / "sqitch.plan").read_text()
    ordered = re.findall(r"^([a-z0-9_]+) \[", plan, re.MULTILINE)
    id_to_code: dict[int, str] = {}
    for change in ordered:
        sql_path = deploy / f"{change}.sql"
        if not sql_path.exists():
            continue
        sql = sql_path.read_text()
        for block in re.findall(r"INSERT INTO return_window\b.*?VALUES(.*?);", sql, re.DOTALL):
            for wid, code in re.findall(r"\(\s*(\d+),\s*'([0-9A-Z_]+)'", block):
                id_to_code[int(wid)] = code
        rename = r"UPDATE return_window SET[^;]*?\bcode\s*=\s*'([0-9A-Z_]+)'"
        rename += r"[^;]*?\bwindow_id\s*=\s*(\d+)"
        for code, wid in re.findall(rename, sql):
            id_to_code[int(wid)] = code
    assert set(id_to_code.values()) == {w.code for w in WINDOWS}
    assert id_to_code == {w.id: w.code for w in WINDOWS}  # ids match too


# --- survivorship invariant (Story 3.7, AR-8) -------------------------------


def test_returns_engine_has_no_lifecycle_status_filter():
    """No code path in the returns engine may silently filter on status (AR-8).

    A ``status = 'active'`` / ``'delisted'`` predicate here would drop delisted
    securities out of fact_returns, reintroducing survivorship bias. The
    active/delisted split is a query-time choice, never a compute-time filter.
    """
    returns_dir = Path(__file__).resolve().parents[1] / "src/sym/returns"
    offenders = [
        f"{path.name}:{i}: {line.strip()}"
        for path in returns_dir.glob("*.py")
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"status\s*=\s*'(active|delisted|suspended)'", line)
    ]
    assert offenders == [], f"survivorship filter in returns engine: {offenders}"


def test_v_prices_adjusted_does_not_join_securities_status():
    """The adjusted-price view reads prices_raw directly, with no status gate (AC#1)."""
    sql = (
        Path(__file__).resolve().parents[1] / "migrations/deploy/v_prices_adjusted.sql"
    ).read_text(encoding="utf-8")
    assert "status" not in sql.lower()
