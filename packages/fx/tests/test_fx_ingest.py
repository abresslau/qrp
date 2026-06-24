"""FX ingest loader (Epic FX, FX2) — fill_fx window resolution + load_fx accounting.

DB-free (fake connection) and network-free (fake FxSource that records its fetch window).
Covers the one-loader collapse: fill_fx with no start_date resolves the tail since the
latest stored date (or DEFAULT_FX_FLOOR on an empty table); an explicit start_date fills
from that floor; an inverted/exhausted window is a no-op. load_fx's insert/skip/implausible
counters are checked end-to-end.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fx.ingest import DEFAULT_FX_FLOOR, fill_fx, load_fx
from fx.source import FxObservation

END = date(2026, 6, 5)  # a Friday


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    """Duck-typed psycopg connection for the four queries the loader issues."""

    def __init__(self, *, currencies=("BRL", "GBP"), max_stored=None, existing=(),
                 stored_ccys=None):
        self.autocommit = False
        self._currencies = currencies          # the `currency` reference table
        self._max_stored = max_stored          # date | None — latest stored as_of_date
        # currencies that actually HAVE stored rows (per-ccy tail); default: all of them
        self._stored_ccys = tuple(stored_ccys) if stored_ccys is not None else tuple(currencies)
        self._existing = set(existing)          # {(ccy, as_of_date)} -> INSERT hits ON CONFLICT
        self.inserted: list[tuple] = []         # captured successful inserts
        self.rejections: list[tuple] = []       # persisted fx_rate_review rows (S.1)

    def execute(self, sql, params=None):
        if "INSERT INTO fx.fx_rate_review" in sql:
            # (quote, as_of_date, rate, prior, relative, source, reason)
            self.rejections.append(params)
            return _Cur()
        if "SELECT 1 FROM fx.fx_rate_review" in sql:
            return _Cur(one=None)               # drain gate: no open rejections
        if "SELECT code FROM fx.currency" in sql:
            return _Cur(rows=[(c,) for c in self._currencies])
        if "SELECT quote_currency, max(as_of_date) FROM fx.fx_rate" in sql:
            if self._max_stored is None:
                return _Cur(rows=[])
            return _Cur(rows=[(c, self._max_stored) for c in self._stored_ccys])
        if "SELECT rate FROM fx.fx_rate" in sql:
            return _Cur(one=None)  # no prior stored rate -> first obs seeds the band
        if "INSERT INTO fx.fx_rate" in sql:
            ccy, as_of, rate, source = params
            if (ccy, as_of) in self._existing:
                return _Cur(one=None)  # ON CONFLICT DO NOTHING -> no RETURNING row
            self.inserted.append((ccy, as_of, rate, source))
            return _Cur(one=(ccy,))
        raise AssertionError(sql)


class _FakeSource:
    """Records the (currencies, start, end) window and returns obs inside it."""

    SOURCE = "frankfurter"

    def __init__(self, observations=()):
        self._obs = list(observations)
        self.calls: list[tuple] = []

    def fetch(self, currencies, start, end):
        self.calls.append((sorted(c for c in currencies if c != "USD"), start, end))
        return [o for o in self._obs if start <= o.as_of_date <= end]


# --- fill_fx: window resolution (the one-loader collapse) ----------------------------


def test_tail_on_empty_table_starts_at_floor():
    # start_date=None + nothing stored -> fill from the ECB-inception floor.
    conn, src = _Conn(max_stored=None), _FakeSource()
    s = fill_fx(conn, src, end_date=END)
    assert src.calls == [(["BRL", "GBP"], DEFAULT_FX_FLOOR, END)]
    # The summary surfaces the resolved window so the caller can display it.
    assert s.start_date == DEFAULT_FX_FLOOR and s.end_date == END


def test_tail_resumes_after_latest_stored_date():
    # start_date=None + data through 06-03 -> resume at 06-04 (last + 1 day).
    conn, src = _Conn(max_stored=date(2026, 6, 3)), _FakeSource()
    s = fill_fx(conn, src, end_date=END)
    assert src.calls == [(["BRL", "GBP"], date(2026, 6, 4), END)]
    assert s.start_date == date(2026, 6, 4) and s.end_date == END  # resolved tail surfaced


def test_tail_already_current_is_noop():
    # Latest stored == end -> resolved start (end + 1 day) > end: no fetch, zero counters,
    # but the resolved window is still surfaced (so the operator sees why nothing loaded).
    conn, src = _Conn(max_stored=END), _FakeSource()
    s = fill_fx(conn, src, end_date=END)
    assert src.calls == [] and conn.inserted == []
    assert (s.currencies, s.inserted, s.skipped_existing, s.implausible) == (0, 0, 0, 0)
    assert s.flagged == []
    assert s.start_date == date(2026, 6, 6) and s.end_date == END


def test_tail_opens_to_floor_for_a_new_currency():
    # GBP exists in `currency` but has no stored rows -> the tail window opens to the
    # floor so its whole history is pulled (BRL's refetch is an ON CONFLICT skip).
    conn = _Conn(currencies=("BRL", "GBP"), max_stored=date(2026, 6, 3), stored_ccys={"BRL"})
    src = _FakeSource()
    s = fill_fx(conn, src, end_date=END)
    assert src.calls == [(["BRL", "GBP"], DEFAULT_FX_FLOOR, END)]
    assert s.start_date == DEFAULT_FX_FLOOR


def test_explicit_start_ignores_stored_max():
    # An explicit start_date fills from that floor and never consults the stored max.
    conn = _Conn(max_stored=date(2026, 6, 3))  # would resume at 06-04 in the tail case
    src = _FakeSource()
    fill_fx(conn, src, start_date=date(2026, 6, 1), end_date=END)
    assert src.calls == [(["BRL", "GBP"], date(2026, 6, 1), END)]


def test_explicit_inverted_window_is_noop():
    # start_date after end_date short-circuits before any fetch (zero counters), but the
    # offending window is still echoed back on the summary.
    conn, src = _Conn(), _FakeSource()
    s = fill_fx(conn, src, start_date=date(2026, 6, 10), end_date=END)
    assert src.calls == [] and conn.inserted == []
    assert (s.currencies, s.inserted, s.skipped_existing, s.implausible) == (0, 0, 0, 0)
    assert s.start_date == date(2026, 6, 10) and s.end_date == END


def test_currencies_subset_passes_through_untouched():
    # An explicit subset bypasses the `currency` reference table.
    conn, src = _Conn(currencies=("BRL", "GBP", "EUR")), _FakeSource()
    fill_fx(conn, src, start_date=date(2026, 6, 1), end_date=END, currencies=["BRL"])
    assert src.calls == [(["BRL"], date(2026, 6, 1), END)]


# --- load_fx: insert / skip / implausible accounting ---------------------------------


def test_inserts_new_rows_and_skips_existing():
    obs = [
        FxObservation("BRL", date(2026, 6, 4), Decimal("5.40")),  # marked existing -> skip
        FxObservation("BRL", date(2026, 6, 5), Decimal("5.45")),  # ~1% move -> insert
        FxObservation("GBP", date(2026, 6, 5), Decimal("0.78")),  # insert
    ]
    conn = _Conn(existing={("BRL", date(2026, 6, 4))})
    src = _FakeSource(obs)
    s = load_fx(conn, src, start_date=date(2026, 6, 4), end_date=END)
    assert s.currencies == 2
    assert s.inserted == 2 and s.skipped_existing == 1
    assert s.implausible == 0 and s.flagged == []
    assert ("BRL", date(2026, 6, 4)) not in [(c, d) for c, d, *_ in conn.inserted]


def test_flags_implausible_observation_without_inserting_it():
    obs = [
        FxObservation("BRL", date(2026, 6, 3), Decimal("5.40")),  # seeds the band
        FxObservation("BRL", date(2026, 6, 4), Decimal("54.0")),  # 10x decimal shift -> reject
        FxObservation("BRL", date(2026, 6, 5), Decimal("5.45")),  # vs 5.40 (prev unmoved) -> ok
    ]
    s = load_fx(_Conn(), _FakeSource(obs), start_date=date(2026, 6, 3), end_date=END)
    assert s.currencies == 1
    assert s.inserted == 2 and s.implausible == 1
    assert s.flagged == ["BRL@2026-06-04=54.0"]


def test_autocommit_is_set_for_per_row_durability():
    # load_fx must flip autocommit so each ON CONFLICT insert commits durably.
    conn = _Conn()
    load_fx(conn, _FakeSource(), start_date=date(2026, 6, 1), end_date=END)
    assert conn.autocommit is True
