"""Tests for GICS classification loading (Story 1.8).

Unit-level and DB-free, matching the house style (see tests/test_lifecycle.py):
a fake ``GicsSource`` stands in for financedatabase and a routing fake connection
stands in for psycopg. The one financedatabase-shaped test builds a small real
pandas frame so NaN handling is exercised for real, without a network call.
"""

from __future__ import annotations

import contextlib
from datetime import date

import pandas as pd
import psycopg

from sym.classification.gics import (
    ClassificationSummary,
    FinanceDatabaseGicsSource,
    GicsClassification,
    SecurityIdentity,
    apply_classifications,
    classification_from_row,
    classify_universe,
    outranks,
    plan_classifications,
    read_classifiable_identities,
)


def _gics(
    figi,
    sector="Information Technology",
    ig="Software & Services",
    ind="Software",
):
    return GicsClassification(
        composite_figi=figi,
        sector_name=sector,
        industry_group_name=ig,
        industry_name=ind,
    )


def _row(
    valid_from,
    sector="Information Technology",
    ig="Software & Services",
    ind="Software",
    source="financedatabase",
):
    """A currently-effective gics_scd row as _RouterConn stores it (6-tuple:
    the four level names, valid_from, then source — matching `_current_row`'s SELECT)."""
    return (sector, ig, ind, None, valid_from, source)


class _FakeSource:
    def __init__(self, mapping):
        self._mapping = mapping  # composite_figi -> GicsClassification

    def fetch(self, securities):
        return {
            s.composite_figi: self._mapping[s.composite_figi]
            for s in securities
            if s.composite_figi in self._mapping
        }


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _RouterConn:
    """Routes SELECTs by table; records every executed statement.

    ``current`` maps a FIGI to its currently-effective gics_scd row as a 5-tuple:
    the four level names followed by ``valid_from`` (matching the columns
    ``_current_row`` selects). The securities query returns identity-shaped
    ``(composite_figi, isin, ticker)`` rows.
    """

    def __init__(self, active_figis=(), current=None):
        self._active = [(f, None, None) for f in active_figis]
        self._current = current or {}
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        upper = sql.upper()
        if "FROM SECURITIES" in upper:
            return _Cursor(self._active)
        if "FROM GICS_SCD" in upper and upper.lstrip().startswith("SELECT"):
            row = self._current.get(params[0])
            return _Cursor([row] if row else [])
        return _Cursor([])

    def transaction(self):
        return contextlib.nullcontext()


class _FailingConn:
    """A connection whose writes (UPDATE/INSERT) always raise, to test isolation."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        upper = sql.upper().lstrip()
        if upper.startswith(("INSERT", "UPDATE")):
            raise psycopg.Error("simulated write failure")
        return _Cursor([])  # SELECT current -> no currently-effective row

    def transaction(self):
        return contextlib.nullcontext()


# --- classification_from_row (financedatabase row -> record) ----------------


def test_row_maps_top_three_labels_and_nulls_the_rest():
    row = {
        "sector": "Health Care",
        "industry_group": "Pharmaceuticals, Biotechnology & Life Sciences",
        "industry": "Biotechnology",
    }
    c = classification_from_row("BBG000BVPV84", row)
    assert c.sector_name == "Health Care"
    assert c.industry_group_name == "Pharmaceuticals, Biotechnology & Life Sciences"
    assert c.industry_name == "Biotechnology"
    # financedatabase supplies neither sub-industry nor numeric GICS codes.
    assert c.sub_industry_name is None
    assert c.sector_code is None
    assert c.sub_industry_code is None
    assert c.is_classified


def test_row_with_missing_sector_is_not_classified():
    c = classification_from_row("BBG000000001", {"sector": float("nan")})
    assert c.sector_name is None
    assert c.is_classified is False


# --- FinanceDatabaseGicsSource over an injected pandas frame ----------------


def test_finance_database_source_keys_on_composite_figi_and_drops_nan():
    frame = pd.DataFrame(
        [
            {
                "composite_figi": "BBG000B9XRY4",
                "isin": "US0378331005",
                "sector": "Information Technology",
                "industry_group": "Technology Hardware & Equipment",
                "industry": "Technology Hardware, Storage & Peripherals",
            },
            {  # no composite_figi -> unjoinable by figi, must be skipped
                "composite_figi": float("nan"),
                "isin": float("nan"),
                "sector": "Financials",
                "industry_group": "Banks",
                "industry": "Banks",
            },
            {  # has figi but no sector -> not classified, skipped
                "composite_figi": "BBG000000XXX",
                "isin": float("nan"),
                "sector": float("nan"),
                "industry_group": float("nan"),
                "industry": float("nan"),
            },
        ]
    )
    source = FinanceDatabaseGicsSource(frame=frame)
    found = source.fetch(
        [
            SecurityIdentity("BBG000B9XRY4", isin="US0378331005"),
            SecurityIdentity("BBG000000XXX"),
            SecurityIdentity("BBG000NOTHERE"),
        ]
    )
    assert set(found) == {"BBG000B9XRY4"}
    assert found["BBG000B9XRY4"].sector_name == "Information Technology"


def test_finance_database_source_falls_back_to_isin():
    # The dataset has the GICS under an ISIN but NOT under our CompositeFIGI
    # (common for non-US names). The match must attribute to OUR figi.
    frame = pd.DataFrame(
        [
            {
                "composite_figi": "BBG_DATASET_FIGI",
                "isin": "GB0005405286",
                "sector": "Financials",
                "industry_group": "Banks",
                "industry": "Banks",
            },
        ]
    )
    source = FinanceDatabaseGicsSource(frame=frame)
    found = source.fetch([SecurityIdentity("BBG_OUR_FIGI", isin="GB0005405286")])
    assert "BBG_OUR_FIGI" in found  # attributed to our composite_figi, matched via ISIN
    assert found["BBG_OUR_FIGI"].sector_name == "Financials"


# --- plan_classifications ---------------------------------------------------


def test_plan_keeps_only_classified_and_requested():
    source = _FakeSource(
        {"BBG000000001": _gics("BBG000000001"), "BBG000000002": _gics("BBG000000002")}
    )
    plans = plan_classifications(
        [SecurityIdentity("BBG000000001"), SecurityIdentity("BBG000000404")], source
    )
    assert [p.composite_figi for p in plans] == ["BBG000000001"]


# --- coverage (AC #2: >=90%) ------------------------------------------------


def test_coverage_meets_threshold_at_ninety_percent():
    figis = [f"BBG0000000{i:02d}" for i in range(10)]
    mapping = {f: _gics(f) for f in figis[:9]}  # 9 of 10 classified
    conn = _RouterConn(active_figis=figis)
    summary = classify_universe(conn, _FakeSource(mapping), as_of_date=date(2026, 6, 6))
    assert summary.active_total == 10
    assert summary.classified == 9
    assert summary.coverage == 0.9
    assert summary.meets_threshold() is True  # default threshold is 0.90, not widened


def test_coverage_below_threshold_is_reported_not_widened():
    figis = [f"BBG0000000{i:02d}" for i in range(10)]
    mapping = {f: _gics(f) for f in figis[:8]}  # only 8 of 10
    conn = _RouterConn(active_figis=figis)
    summary = classify_universe(conn, _FakeSource(mapping), as_of_date=date(2026, 6, 6))
    assert summary.coverage == 0.8
    assert summary.meets_threshold() is False
    assert summary.meets_threshold(0.80) is True


# --- apply_classifications: idempotent SCD writes ---------------------------


def test_rerun_with_identical_classification_is_noop():
    figi = "BBG000B9XRY4"
    current = {figi: _row(date(2026, 1, 1))}  # same levels as _gics(figi)
    conn = _RouterConn(current=current)
    summary = apply_classifications(conn, [_gics(figi)], as_of_date=date(2026, 6, 6))
    assert summary.unchanged == 1
    assert summary.rows_inserted == 0
    assert not any("INSERT" in sql.upper() for sql, _ in conn.calls)


def test_changed_classification_on_a_later_day_closes_prior_row_then_inserts():
    figi = "BBG000B9XRY4"
    # Prior row was written on an EARLIER day, so closing it yields a non-empty period.
    current = {figi: _row(date(2026, 1, 1), ind="Old Industry")}
    conn = _RouterConn(current=current)
    summary = apply_classifications(conn, [_gics(figi)], as_of_date=date(2026, 6, 6))
    assert summary.rows_closed == 1
    assert summary.rows_inserted == 1
    assert summary.rows_updated == 0
    statements = " ".join(sql.upper() for sql, _ in conn.calls)
    assert "SET VALID_TO" in statements  # the prior row is closed
    assert "INSERT INTO GICS_SCD" in statements
    assert "DELETE" not in statements  # SCD closes, never deletes


def test_changed_classification_on_the_same_day_updates_in_place():
    """A same-day correction must NOT close-then-insert (that sets valid_to == valid_from,
    violating gics_scd_validity_chk); it overwrites the currently-effective row instead."""
    figi = "BBG000B9XRY4"
    as_of_date = date(2026, 6, 6)
    # Prior row was written TODAY (valid_from == as_of_date) with a stale industry label.
    current = {figi: _row(as_of_date, ind="Old Industry")}
    conn = _RouterConn(current=current)
    summary = apply_classifications(conn, [_gics(figi)], as_of_date=as_of_date)
    assert summary.rows_updated == 1
    assert summary.rows_closed == 0
    assert summary.rows_inserted == 0
    statements = " ".join(sql.upper() for sql, _ in conn.calls)
    assert "SET VALID_TO" not in statements  # never closes -> no zero-width period
    assert "INSERT INTO GICS_SCD" not in statements
    assert "SET SECTOR_CODE" in statements  # in-place level overwrite


def test_new_figi_inserts_without_closing():
    figi = "BBG000B9XRY4"
    conn = _RouterConn()  # no currently-effective row
    summary = apply_classifications(conn, [_gics(figi)], as_of_date=date(2026, 6, 6))
    assert summary.rows_closed == 0
    assert summary.rows_inserted == 1


def test_failed_write_is_isolated_and_counted():
    """One security's write failing is rolled back and counted; the run continues."""
    conn = _FailingConn()
    plans = [_gics("BBG000000001"), _gics("BBG000000002")]
    summary = apply_classifications(conn, plans, as_of_date=date(2026, 6, 6))
    assert summary.failed == 2  # both attempted despite the first failing
    assert summary.rows_inserted == 0


def test_summary_coverage_is_zero_when_no_active_securities():
    assert ClassificationSummary().coverage == 0.0


# --- cross-source precedence / merge (multi-source AC5/AC8) ------------------


class _StatefulConn:
    """A fake conn that models gics_scd effective rows in memory ACROSS calls.

    Unlike `_RouterConn` (static `current`), this records what `apply_classifications`
    inserts, so a second source's pass sees the first source's writes — letting a
    test exercise the cross-source merge: fill-only precedence + per-row provenance.
    """

    def __init__(self):
        # composite_figi -> (level_names tuple, source, valid_from)
        self.effective: dict[str, tuple] = {}

    def execute(self, sql, params=()):
        upper = sql.upper().lstrip()
        if upper.startswith("SELECT") and "FROM GICS_SCD" in sql.upper():
            row = self.effective.get(params[0])
            if row is None:
                return _Cursor([])
            names, source, valid_from = row
            return _Cursor([(names[0], names[1], names[2], names[3], valid_from, source)])
        if upper.startswith("INSERT"):
            # _insert_row order: figi, sector_code, sector_name, ig_code, ig_name,
            # ind_code, ind_name, sub_code, sub_name, source, valid_from
            figi, sector_name = params[0], params[2]
            ig_name, ind_name, sub_name = params[4], params[6], params[8]
            source, valid_from = params[9], params[10]
            self.effective[figi] = ((sector_name, ig_name, ind_name, sub_name), source, valid_from)
        return _Cursor([])

    def transaction(self):
        return contextlib.nullcontext()

    def unclassified(self, all_figis):
        """The fill-source scope: actives with no effective row yet (in request order)."""
        return [SecurityIdentity(f) for f in all_figis if f not in self.effective]


def _src_class(figi, sector, source):
    return GicsClassification(
        composite_figi=figi, sector_name=sector, industry_group_name=None,
        industry_name=None, source=source,
    )


def test_cross_source_merge_is_fill_only_first_writer_wins_with_provenance():
    """A later (lower-precedence) source fed only the unclassified set fills the gaps
    and NEVER overwrites an earlier source's rows; each row keeps its own `source`."""
    conn = _StatefulConn()
    all_figis = ["BBG000000001", "BBG000000002", "BBG000000003"]

    # Pass 1 (primary): classifies #1 and #2.
    primary = _FakeSource(
        {
            "BBG000000001": _src_class("BBG000000001", "Energy", "financedatabase"),
            "BBG000000002": _src_class("BBG000000002", "Materials", "financedatabase"),
        }
    )
    p1 = plan_classifications([SecurityIdentity(f) for f in all_figis], primary)
    s1 = apply_classifications(conn, p1, as_of_date=date(2026, 6, 17))
    assert s1.rows_inserted == 2

    # Only #3 remains in the fill scope.
    assert {s.composite_figi for s in conn.unclassified(all_figis)} == {"BBG000000003"}

    # Pass 2 (fill source): WOULD reclassify #1 differently, but is fed only the
    # unclassified set, so it can only touch #3.
    fill = _FakeSource(
        {
            "BBG000000001": _src_class("BBG000000001", "Industrials", "sec_sic"),  # never seen
            "BBG000000003": _src_class("BBG000000003", "Utilities", "sec_sic"),
        }
    )
    p2 = plan_classifications(conn.unclassified(all_figis), fill)
    s2 = apply_classifications(conn, p2, as_of_date=date(2026, 6, 17))
    assert s2.rows_inserted == 1
    assert s2.rows_closed == 0  # no overwrite of #1

    # #1 keeps the primary source + value (never overwritten); #3 gets the fill source.
    assert conn.effective["BBG000000001"][0][0] == "Energy"
    assert conn.effective["BBG000000001"][1] == "financedatabase"
    assert conn.effective["BBG000000002"][1] == "financedatabase"
    assert conn.effective["BBG000000003"][0][0] == "Utilities"
    assert conn.effective["BBG000000003"][1] == "sec_sic"


# --- AC5 precedence upgrade: higher source supersedes lower -----------------


class _CaptureConn:
    """Records executed (sql, params); returns empty cursors. For scope-query tests."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return _Cursor([])

    def transaction(self):
        return contextlib.nullcontext()


def test_outranks_precedence_order():
    assert outranks("financedatabase", "llm")
    assert outranks("financedatabase", "yahoo_profile")
    assert outranks("sec_sic", "yahoo_profile")
    assert outranks("yahoo_profile", "llm")
    assert not outranks("llm", "financedatabase")  # lower never outranks higher
    assert not outranks("financedatabase", "financedatabase")  # equal is not STRICTLY higher
    assert not outranks("financedatabase", "manual")  # unknown current is preserved
    assert not outranks("manual", "llm")  # unknown new never supersedes
    assert not outranks(None, "llm")


def test_higher_precedence_source_supersedes_lower_on_later_day():
    """financedatabase (high) replacing an llm (low) row with a DIFFERENT sector closes
    the llm row and inserts the new one — a genuine cross-source supersede."""
    figi = "BBG000B9XRY4"
    current = {figi: _row(date(2026, 1, 1), sector="Energy", source="llm")}
    conn = _RouterConn(current=current)
    # _gics default source = financedatabase (outranks llm), default sector differs from Energy
    summary = apply_classifications(conn, [_gics(figi)], as_of_date=date(2026, 6, 6))
    assert summary.rows_closed == 1
    assert summary.rows_inserted == 1
    assert summary.rows_updated == 0
    statements = " ".join(sql.upper() for sql, _ in conn.calls)
    assert "SET VALID_TO" in statements
    assert "INSERT INTO GICS_SCD" in statements


def test_higher_precedence_same_sector_upgrades_provenance_in_place():
    """financedatabase agreeing with an llm row's sector upgrades provenance IN PLACE —
    no new SCD row (the classification value is unchanged, only its attribution)."""
    figi = "BBG000B9XRY4"
    current = {figi: _row(date(2026, 1, 1), source="llm")}  # same levels as _gics default
    conn = _RouterConn(current=current)
    summary = apply_classifications(conn, [_gics(figi)], as_of_date=date(2026, 6, 6))
    assert summary.rows_updated == 1
    assert summary.rows_inserted == 0
    assert summary.rows_closed == 0
    assert summary.unchanged == 0
    statements = " ".join(sql.upper() for sql, _ in conn.calls)
    assert "SET VALID_TO" not in statements  # not closed
    assert "INSERT INTO GICS_SCD" not in statements  # no new row
    assert "SET SECTOR_CODE" in statements  # in-place update (rewrites source too)


def test_lower_precedence_source_never_overwrites_higher():
    """An llm (low) classification must never overwrite a financedatabase (high) row,
    even with a different sector — the defensive guard leaves it unchanged."""
    figi = "BBG000B9XRY4"
    current = {figi: _row(date(2026, 1, 1), sector="Energy", source="financedatabase")}
    conn = _RouterConn(current=current)
    llm_class = GicsClassification(
        composite_figi=figi, sector_name="Materials", industry_group_name=None,
        industry_name=None, source="llm",
    )
    summary = apply_classifications(conn, [llm_class], as_of_date=date(2026, 6, 6))
    assert summary.unchanged == 1
    assert summary.rows_inserted == 0
    assert summary.rows_closed == 0
    assert summary.rows_updated == 0
    statements = " ".join(sql.upper() for sql, _ in conn.calls)
    assert "SET VALID_TO" not in statements
    assert "INSERT INTO GICS_SCD" not in statements


def test_unknown_source_row_is_preserved():
    """A legacy/manual classification (source outside the precedence map) is never
    auto-superseded — we don't clobber rows we don't understand."""
    figi = "BBG000B9XRY4"
    current = {figi: _row(date(2026, 1, 1), sector="Energy", source="manual")}
    conn = _RouterConn(current=current)
    summary = apply_classifications(conn, [_gics(figi)], as_of_date=date(2026, 6, 6))
    assert summary.unchanged == 1
    assert summary.rows_inserted == 0
    assert summary.rows_closed == 0


def test_cross_source_higher_precedence_supersedes_lower_end_to_end():
    """Full sequence: llm classifies a name, then financedatabase (higher) supersedes it
    on a later run — the row's source + sector both flip to financedatabase."""
    conn = _StatefulConn()
    figi = "BBG000000001"
    llm = _FakeSource({figi: _src_class(figi, "Utilities", "llm")})
    apply_classifications(conn, plan_classifications([SecurityIdentity(figi)], llm),
                          as_of_date=date(2026, 6, 6))
    assert conn.effective[figi][1] == "llm"

    fd = _FakeSource({figi: _src_class(figi, "Energy", "financedatabase")})
    s = apply_classifications(conn, plan_classifications([SecurityIdentity(figi)], fd),
                              as_of_date=date(2026, 6, 7))
    assert s.rows_closed == 1
    assert s.rows_inserted == 1
    assert conn.effective[figi][0][0] == "Energy"
    assert conn.effective[figi][1] == "financedatabase"


def test_read_classifiable_scope_lower_sources_by_precedence():
    """The scope query passes exactly the strictly-lower-precedence sources as the
    'supersedable' set (so a source sees unclassified + lower-held names)."""
    conn = _CaptureConn()
    read_classifiable_identities(conn, source="sec_sic")
    _sql, params = conn.calls[-1]
    assert set(params[0]) == {"yahoo_profile", "llm"}

    conn2 = _CaptureConn()
    read_classifiable_identities(conn2, source="financedatabase")
    assert set(conn2.calls[-1][1][0]) == {"b3", "sec_sic", "yahoo_profile", "llm"}

    conn3 = _CaptureConn()
    read_classifiable_identities(conn3, source="llm")
    assert conn3.calls[-1][1][0] == []  # nothing ranks below llm → only unclassified in scope


def test_read_classifiable_unknown_source_falls_back_to_unclassified():
    conn = _CaptureConn()
    read_classifiable_identities(conn, source="manual")
    sql, _params = conn.calls[-1]
    # the plain unclassified query has no source-precedence filter
    assert "<> ALL" not in sql.upper()
