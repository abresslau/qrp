"""FX source parse + normalization + plausibility (Epic FX, FX2). DB-free, no network."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from sym.fx.ingest import implausible
from sym.fx.source import (
    QUOTE_PER_USD,
    USD_PER_QUOTE,
    FrankfurterSource,
    FxSourceError,
    parse_frankfurter_timeseries,
    to_usd_base,
)

_SAMPLE = {
    "amount": 1,
    "base": "USD",
    "rates": {
        "2024-01-02": {"BRL": 4.85, "GBP": 0.785, "EUR": 0.905},
        "2024-01-03": {"BRL": 4.90, "GBP": 0.788, "EUR": 0.908},
    },
}


def test_parse_timeseries_yields_usd_base_observations():
    obs = parse_frankfurter_timeseries(_SAMPLE)
    assert len(obs) == 6  # 2 days x 3 currencies
    brl = sorted([o for o in obs if o.currency == "BRL"], key=lambda o: o.as_of_date)
    assert brl[0].as_of_date == date(2024, 1, 2) and brl[0].rate == Decimal("4.85")
    assert {o.currency for o in obs} == {"BRL", "GBP", "EUR"}


def test_parse_rejects_non_usd_base_and_empty():
    with pytest.raises(FxSourceError, match="base=USD"):
        parse_frankfurter_timeseries({"base": "EUR", "rates": {"2024-01-02": {"USD": 1.1}}})
    with pytest.raises(FxSourceError, match="no rates"):
        parse_frankfurter_timeseries({"base": "USD", "rates": {}})


def test_to_usd_base_inverts_a_usd_quoted_feed():
    # A USD-base feed passes through; a USD-quoted feed (e.g. EURUSD=X 1.08) inverts.
    assert to_usd_base(Decimal("5.40"), QUOTE_PER_USD) == Decimal("5.40")
    inv = to_usd_base(Decimal("1.08"), USD_PER_QUOTE)
    assert round(inv, 4) == Decimal("0.9259")
    with pytest.raises(FxSourceError):
        to_usd_base(Decimal("0"), USD_PER_QUOTE)


def test_frankfurter_fetch_excludes_usd_and_uses_injected_getter():
    calls = []

    def fake_getter(url, params):
        calls.append((url, params))
        return _SAMPLE

    src = FrankfurterSource(getter=fake_getter)
    obs = src.fetch(["BRL", "GBP", "EUR", "USD"], date(2024, 1, 2), date(2024, 1, 3))
    assert len(obs) == 6
    # USD is dropped from the requested symbols (it's the base, never a quote)
    assert "USD" not in calls[0][1]["symbols"]
    assert calls[0][1]["base"] == "USD"


def test_implausibility_band():
    assert implausible(None, Decimal("5.4")) is False  # first observation
    assert implausible(Decimal("5.40"), Decimal("5.45")) is False  # ~1% move
    assert implausible(Decimal("5.40"), Decimal("0.185")) is True  # inverted feed (~96% drop)
    assert implausible(Decimal("5.40"), Decimal("54.0")) is True  # decimal shift (10x)


def test_fawazahmed_parse_keeps_wanted_usd_base():
    from datetime import date as _date

    from sym.fx.source import parse_fawazahmed_day

    payload = {"date": "2026-06-05", "usd": {"twd": 31.53, "brl": 5.06, "eur": 0.88}}
    obs = parse_fawazahmed_day(payload, {"TWD", "EUR"}, _date(2026, 6, 5))
    got = {o.currency: o.rate for o in obs}
    assert set(got) == {"TWD", "EUR"}  # BRL not requested -> dropped
    assert got["TWD"] == Decimal("31.53") and got["EUR"] == Decimal("0.88")


def test_fawazahmed_fetch_loops_weekdays_and_skips_404():
    from datetime import date as _date

    from sym.fx.source import FawazahmedSource

    calls = []

    def fake_getter(url):
        calls.append(url)
        # 404 (None) for the 2nd weekday to prove skip-on-missing
        if "2026-06-04" in url:
            return None
        return {"usd": {"twd": 31.5}}

    src = FawazahmedSource(getter=fake_getter)
    # 06-03 Wed, 06-04 Thu(404), 06-05 Fri, 06-06 Sat(skip), 06-07 Sun(skip)
    obs = src.fetch(["TWD", "USD"], _date(2026, 6, 3), _date(2026, 6, 7))
    assert len(calls) == 3  # only the 3 weekdays fetched
    assert {o.as_of_date for o in obs} == {_date(2026, 6, 3), _date(2026, 6, 5)}  # 06-04 skipped


def test_source_rank_mirrors_precedence_order():
    from sym.fx.source import source_rank

    # Frankfurter (primary) < ECB (reconcile) < fawazahmed0 (fallback) < unknown.
    assert source_rank("frankfurter") < source_rank("ecb") < source_rank("fawazahmed0")
    assert source_rank("anything_else") == 100


# A trimmed ECB SDMX EXR csvdata payload (EUR-base: OBS_VALUE = ccy per 1 EUR). Real payloads
# carry ~30 columns; the parser indexes by name, so a faithful subset suffices. A blank
# OBS_VALUE (ECB's non-trading-day marker) must be skipped.
_ECB_CSV = (
    "CURRENCY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "USD,2024-01-02,1.10,A\n"
    "BRL,2024-01-02,5.40,A\n"
    "JPY,2024-01-02,,A\n"  # blank -> skipped
    "USD,2024-01-03,1.20,A\n"
    "BRL,2024-01-03,6.00,A\n"
)


def test_parse_ecb_csv_yields_eur_base_map_and_skips_blanks():
    from sym.fx.source import parse_ecb_csv

    eur_base = parse_ecb_csv(_ECB_CSV)
    assert eur_base[date(2024, 1, 2)]["USD"] == Decimal("1.10")
    assert eur_base[date(2024, 1, 2)]["BRL"] == Decimal("5.40")
    assert "JPY" not in eur_base[date(2024, 1, 2)]  # blank OBS_VALUE dropped
    assert parse_ecb_csv("") == {}  # empty body (e.g. an unknown series) -> no rows


def test_rebase_ecb_to_usd_triangulates_through_the_usd_leg():
    from sym.fx.source import parse_ecb_csv, rebase_ecb_to_usd

    obs = rebase_ecb_to_usd(parse_ecb_csv(_ECB_CSV), {"BRL", "EUR", "USD"})
    by = {(o.currency, o.as_of_date): o.rate for o in obs}
    assert ("USD", date(2024, 1, 2)) not in by  # USD is the base, never emitted
    # BRL per USD = (BRL per EUR) / (USD per EUR) = 5.40 / 1.10
    assert round(by[("BRL", date(2024, 1, 2))], 6) == Decimal("4.909091")
    # EUR per USD = 1 / (USD per EUR) = 1 / 1.10
    assert round(by[("EUR", date(2024, 1, 2))], 6) == Decimal("0.909091")
    # 6.00 / 1.20 is exact
    assert by[("BRL", date(2024, 1, 3))] == Decimal("5")


def test_rebase_skips_a_date_with_no_usd_pivot_leg():
    from sym.fx.source import rebase_ecb_to_usd

    eur_base = {date(2024, 1, 2): {"BRL": Decimal("5.40")}}  # BRL but no USD leg
    assert rebase_ecb_to_usd(eur_base, {"BRL"}) == []  # cannot rebase -> skipped


def test_ecb_fetch_requests_usd_pivot_plus_non_eur_currencies():
    from sym.fx.source import EcbSdmxSource

    calls = []

    def fake_getter(url, params):
        calls.append((url, params))
        return _ECB_CSV

    src = EcbSdmxSource(getter=fake_getter)
    obs = src.fetch(["BRL", "EUR", "USD"], date(2024, 1, 2), date(2024, 1, 3))
    # EUR needs no series of its own (derived from the USD leg); USD is the pivot.
    assert "D.BRL+USD.EUR.SP00.A" in calls[0][0]
    assert calls[0][1]["format"] == "csvdata"
    assert {o.currency for o in obs} == {"BRL", "EUR"}  # rebased; USD itself not emitted
