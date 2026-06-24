"""ECB euro-area source — enumeration of universes × rate types × grid (download monkeypatched)."""

from __future__ import annotations

from datetime import date

from rates.sources import ecb
from rates.sources.ecb import EcbYieldCurveSource

# A minimal one-row SDMX CSV; the source derives series identity from the URL, not the body.
_CSV = "KEY,TIME_PERIOD,OBS_VALUE\nYC.X,2026-06-22,3.21\n"


def test_fetch_enumerates_both_universes_three_rate_types(monkeypatch):
    seen_urls: list[str] = []

    def fake_download(url, *, timeout=120):
        seen_urls.append(url)
        return _CSV

    monkeypatch.setattr(ecb, "_download", fake_download)
    pts = EcbYieldCurveSource().fetch()

    # 2 universes × 3 rate types × 12 tenors = 72 series, one point each.
    assert len(seen_urls) == 72
    assert len(pts) == 72
    combos = {(p.curve_set, p.basis, p.rate_type) for p in pts}
    assert combos == {
        ("govt", "nominal", "spot"), ("govt", "nominal", "forward"), ("govt", "nominal", "par"),
        ("govt_all", "nominal", "spot"), ("govt_all", "nominal", "forward"),
        ("govt_all", "nominal", "par"),
    }
    assert all(p.country == "EU" and p.currency == "EUR" for p in pts)
    # forward uses the IF_ token, par the PY_, all-bonds the G_N_C key
    assert any("G_N_C" in u and "IF_10Y" in u for u in seen_urls)
    assert any("G_N_A" in u and "PY_30Y" in u for u in seen_urls)


def test_partial_grid_tolerated_when_a_series_is_unavailable(monkeypatch):
    def flaky_download(url, *, timeout=120):
        if "IF_30Y" in url:
            raise OSError("503 from a single series")
        return _CSV

    monkeypatch.setattr(ecb, "_download", flaky_download)
    pts = EcbYieldCurveSource().fetch()
    # the two IF_30Y series (AAA + all) drop out; the other 70 still load.
    assert len(pts) == 70
    assert not any(p.rate_type == "forward" and p.tenor == 30.0 for p in pts)


def test_partial_grid_tolerated_when_a_series_returns_a_garbled_200(monkeypatch):
    # a 200 with an HTML/maintenance body parses to a CurveLayoutError (not an OSError) — it must
    # still be tolerated per-series, not abort the whole grid.
    def garbled_download(url, *, timeout=120):
        if "PY_3M" in url:
            return "<html>ECB service temporarily unavailable</html>"
        return _CSV

    monkeypatch.setattr(ecb, "_download", garbled_download)
    pts = EcbYieldCurveSource().fetch()
    assert len(pts) == 70  # the two PY_3M series drop; the other 70 load
    assert not any(p.rate_type == "par" and p.tenor == 0.25 for p in pts)


def test_wholesale_outage_raises_not_silent_empty(monkeypatch):
    # if EVERY series fails, fetch must raise rather than silently return [] (which would let a
    # full ECB outage / layout drift land as a no-op).
    def all_bad(url, *, timeout=120):
        raise OSError("503")

    monkeypatch.setattr(ecb, "_download", all_bad)
    try:
        EcbYieldCurveSource().fetch()
    except ecb.CurveLayoutError:
        pass
    else:
        raise AssertionError("expected a CurveLayoutError on a wholesale outage")


def test_member_long_term_rate_unchanged(monkeypatch):
    monkeypatch.setattr(ecb, "_download", lambda url, *, timeout=120: _CSV)
    pts = ecb.EcbLongTermRateSource("FR").fetch()
    assert len(pts) == 1
    p = pts[0]
    assert p.country == "FR" and p.rate_type == "yield" and p.tenor == 10.0
    assert p.as_of_date == date(2026, 6, 22)
