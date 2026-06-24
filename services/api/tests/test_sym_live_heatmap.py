"""Live heatmap (Story QH.9). DB-free — a fake conn yields member rows + the universe name, and
the batched quote fan-out is monkeypatched. Covers the live recolor + per-cell freshness, the
share-class collapse carried over from the EOD heatmap, the coverage/as_of/worst-freshness rollup,
the over-cap 422, and the whole-source 503 mapping."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from qrp_api.modules.sym import gateway as gw_mod
from qrp_api.modules.sym import quotes
from qrp_api.modules.sym import router as router_mod
from qrp_api.modules.sym.gateway import DbSymGateway
from qrp_api.modules.sym.quotes import QuoteSourceUnreachable, RawQuote

_EPOCH = 1781553601


class _Cur:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _Conn:
    """Dispatches the two reads live_heatmap issues: the universe-name scalar, then member rows."""

    def __init__(self, member_rows, uname="S&P 500"):
        self.member_rows = member_rows
        self.uname = uname
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "FROM universe WHERE" in sql:
            return _Cur(one=(self.uname,) if self.uname is not None else None)
        return _Cur(rows=self.member_rows)


# (figi, ticker, mic, name, sector, industry, market_cap_usd, market_cap_lcy, currency, isin)
_ROWS = [
    ("F1", "AAPL", "XNAS", "Apple", "Tech", "Hardware", 3000.0, None, "USD", "US0378331005"),
    ("F2a", "BRK.A", "XNYS", "Berkshire A", "Financials", "Insurance", 500.0, None, "USD", "US0846701086"),
    ("F2b", "BRK.B", "XNYS", "Berkshire B", "Financials", "Insurance", 900.0, None, "USD", "US0846707026"),
    ("F3", "XYZ", "XZZZ", "NoMap", "Tech", "Software", 100.0, None, "USD", "ZZ0000000000"),
]


def _batch(monkeypatch, mapping):
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda symbols, **kw: {s: mapping.get(s) for s in symbols})


def test_live_heatmap_recolors_with_freshness_and_collapses_share_classes(monkeypatch):
    # AAPL live (+10%, fresh); BRK-B delayed (+10%, stale 600s); NoMap unmapped MIC -> unavailable.
    _batch(monkeypatch, {
        "AAPL": RawQuote(110.0, 100.0, "USD", _EPOCH),
        "BRK-B": RawQuote(220.0, 200.0, "USD", _EPOCH - 600),
    })
    conn = _Conn(_ROWS)
    out = DbSymGateway(conn, universe_conn=conn).live_heatmap("u1", now=_EPOCH + 10)

    assert out["window"] == "LIVE"
    assert out["shown"] == 3 and out["merged_share_classes"] == 1  # BRK.A/BRK.B -> one issuer
    by = {c["ticker"]: c for c in out["cells"]}
    # the collapsed Berkshire tile is the larger-cap class (BRK.B)
    assert "BRK.B" in by and "BRK.A" not in by
    assert by["AAPL"]["ret"] == pytest.approx(0.10) and by["AAPL"]["freshness"] == "live"
    assert by["BRK.B"]["ret"] == pytest.approx(0.10) and by["BRK.B"]["freshness"] == "delayed"
    assert by["XYZ"]["ret"] is None and by["XYZ"]["freshness"] == "unavailable"  # unmapped MIC -> neutral cell
    # rollup: worst priced = delayed, coverage 2/3, as_of = MOST-RECENT priced quote (QH.9: the
    # freshest mark, not pinned by the older BRK-B at _EPOCH-600 — so AAPL's _EPOCH wins).
    assert out["priced"] == 2 and out["total"] == 3 and out["freshness"] == "delayed"
    assert out["as_of"] == datetime.fromtimestamp(_EPOCH, tz=timezone.utc).isoformat()
    # no internal mic leaked into the response cells
    assert all("_mic" not in c and "mic" not in c for c in out["cells"])


def test_live_heatmap_writes_nothing(monkeypatch):
    _batch(monkeypatch, {"AAPL": RawQuote(110.0, 100.0, "USD", _EPOCH)})
    conn = _Conn(_ROWS)
    DbSymGateway(conn, universe_conn=conn).live_heatmap("u1", now=_EPOCH)
    assert all(
        "INSERT" not in s.upper() and "UPDATE" not in s.upper() and "DELETE" not in s.upper()
        for s in conn.seen
    )


def test_live_heatmap_unknown_universe_raises_lookup(monkeypatch):
    conn = _Conn([], uname=None)
    with pytest.raises(LookupError):
        DbSymGateway(conn, universe_conn=conn).live_heatmap("nope", now=_EPOCH)


def test_live_heatmap_over_cap_raises_value_error(monkeypatch):
    monkeypatch.setattr(gw_mod, "LIVE_HEATMAP_MAX", 1)  # 3 issuers > 1
    _batch(monkeypatch, {})
    with pytest.raises(ValueError):
        DbSymGateway(_CR := _Conn(_ROWS), universe_conn=_CR).live_heatmap("u1", now=_EPOCH)


def test_live_heatmap_whole_source_unreachable_propagates(monkeypatch):
    def boom(symbols, **kw):
        raise QuoteSourceUnreachable("down")

    monkeypatch.setattr(quotes, "fetch_quotes_batch", boom)
    with pytest.raises(QuoteSourceUnreachable):
        DbSymGateway(_CR := _Conn(_ROWS), universe_conn=_CR).live_heatmap("u1", now=_EPOCH)


# --- route mapping ---------------------------------------------------------------

class _Gw:
    def __init__(self, fn):
        self._fn = fn

    def live_heatmap(self, uid):
        return self._fn(uid)


def test_route_maps_unreachable_to_503():
    def boom(uid):
        raise QuoteSourceUnreachable("down")

    with pytest.raises(HTTPException) as exc:
        router_mod.heatmap_live(universe_id="u1", gw=_Gw(boom))
    assert exc.value.status_code == 503


def test_route_maps_over_cap_to_422():
    def boom(uid):
        raise ValueError("too large")

    with pytest.raises(HTTPException) as exc:
        router_mod.heatmap_live(universe_id="u1", gw=_Gw(boom))
    assert exc.value.status_code == 422


def test_route_maps_unknown_universe_to_404():
    def boom(uid):
        raise LookupError("nope")

    with pytest.raises(HTTPException) as exc:
        router_mod.heatmap_live(universe_id="u1", gw=_Gw(boom))
    assert exc.value.status_code == 404
