"""Parser/fetcher tests for macro.sources — fixture payloads only, no live network."""

from __future__ import annotations

import json
import urllib.error
from datetime import date

import pytest

import macro.sources as sources
from macro.sources import (
    _parse_br_date,
    _parse_period,
    _sidra_period,
    fetch_bcb_focus_12m,
    fetch_bcb_sgs,
    fetch_ecb,
    fetch_eurostat,
    fetch_fiscaldata_avg_rates,
    fetch_fiscaldata_debt,
    fetch_fiscaldata_rows,
    fetch_oecd_cpi,
    fetch_sidra,
    fetch_treasury_par_yield,
    parse_sdmx_csv,
    parse_treasury_par_yield,
)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "boom", None, None)

# --- shared SDMX-CSV parser -------------------------------------------------------------

_OECD_CSV = """\
DATAFLOW,REF_AREA,FREQ,METHODOLOGY,MEASURE,UNIT_MEASURE,EXPENDITURE,ADJUSTMENT,TRANSFORMATION,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT_MULT,BASE_PER,DURABILITY,DECIMALS
OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),USA,M,N,CPI,PA,_T,N,GY,2025-06,2.669213,A,,,,2
OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),USA,M,N,CPI,PA,_T,N,GY,2025-05,2.354897,A,,,,2
OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),USA,M,N,CPI,PA,_T,N,GY,garbled,not-a-number,A,,,,2
OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),USA,M,N,CPI,PA,_T,N,GY,2025-04,,A,,,,2
"""

_ECB_CSV = """\
KEY,FREQ,CURRENCY,TIME_PERIOD,OBS_VALUE
FM.D.U2.EUR.4F.KR.MRR_FR.LEV,D,EUR,2025-01-02,3.15
FM.D.U2.EUR.4F.KR.MRR_FR.LEV,D,EUR,2025-01-03,3.15
FM.D.U2.EUR.4F.KR.MRR_FR.LEV,D,EUR,2025-01-06,2.90
FM.D.U2.EUR.4F.KR.MRR_FR.LEV,D,EUR,2025-01-07,2.90
FM.D.U2.EUR.4F.KR.MRR_FR.LEV,D,EUR,2025-01-08,2.90
"""


def test_parse_sdmx_csv_sorts_descending_rows_and_skips_garbage():
    obs = parse_sdmx_csv(_OECD_CSV)
    # garbled period and empty value rows are SKIPPED, never invented
    assert obs == [
        (date(2025, 5, 1), 2.354897),
        (date(2025, 6, 1), 2.669213),
    ]


def test_parse_sdmx_csv_ref_area_filter_drops_foreign_rows():
    mixed = _OECD_CSV + (
        "OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),MEX,M,N,CPI,PA,_T,N,GY,2025-06,4.5,A,,,,2\n"
    )
    assert (date(2025, 6, 1), 4.5) in parse_sdmx_csv(mixed)  # unfiltered: MEX row present
    obs = parse_sdmx_csv(mixed, ref_area="USA")
    assert (date(2025, 6, 1), 4.5) not in obs
    assert (date(2025, 6, 1), 2.669213) in obs


def test_parse_sdmx_csv_handles_ecb_shape():
    obs = parse_sdmx_csv(_ECB_CSV)
    assert len(obs) == 5
    assert obs[0] == (date(2025, 1, 2), 3.15)


def test_parse_sdmx_csv_skips_non_finite_values():
    # NaN/inf pass float() but would 500 the API's JSON encoder — treated as garbled
    bad = _OECD_CSV + (
        "OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),USA,M,N,CPI,PA,_T,N,GY,2025-03,NaN,A,,,,2\n"
        "OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),USA,M,N,CPI,PA,_T,N,GY,2025-02,inf,A,,,,2\n"
        "OECD.SDD.TPS:DSD_PRICES@DF_PRICES_ALL(1.0),USA,M,N,CPI,PA,_T,N,GY,2025-01,1e999,A,,,,2\n"
    )
    obs = parse_sdmx_csv(bad)
    assert [d for d, _ in obs] == [date(2025, 5, 1), date(2025, 6, 1)]


def test_parse_period_rejects_trailing_junk():
    with pytest.raises(ValueError, match="2025-06-30-99"):
        _parse_period("2025-06-30-99")  # must NOT silently parse as 2025-06-30


def test_fetch_ecb_compresses_to_change_points(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: _ECB_CSV.encode())
    meta, obs = fetch_ecb("FM/D.U2...", "ECB:MRR", "ECB main refinancing rate", "%", "daily")
    # first + change-point + last; the repeated levels in between are dropped
    assert obs == [
        (date(2025, 1, 2), 3.15),
        (date(2025, 1, 6), 2.90),
        (date(2025, 1, 8), 2.90),
    ]
    assert meta["source"] == "ecb"
    assert meta["series_id"] == "ECB:MRR"


def test_fetch_oecd_cpi_maps_404_to_empty_series(monkeypatch):
    def fake_get(url: str, **kw) -> bytes:
        raise _http_error(404)  # OECD NoRecordsFound (verified live for unserved geos)

    monkeypatch.setattr(sources, "_get", fake_get)
    meta, obs = fetch_oecd_cpi("ZZZ")
    assert obs == []  # empty -> caller's no-data rule omits the series, no error noise
    assert meta["series_id"] == "OECD:CPI:ZZZ"


def test_fetch_oecd_cpi_non_404_http_errors_still_raise(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: (_ for _ in ()).throw(_http_error(503)))
    with pytest.raises(urllib.error.HTTPError):
        fetch_oecd_cpi("USA")


# --- FiscalData ---------------------------------------------------------------------------


def test_fetch_fiscaldata_rows_paginates_until_short_page(monkeypatch):
    pages = {
        1: {"data": [{"record_date": "2026-06-08", "v": "1"},
                     {"record_date": "2026-06-09", "v": "2"}]},
        2: {"data": [{"record_date": "2026-06-10", "v": "3"}]},
    }
    urls: list[str] = []

    def fake_get(url: str, **kw) -> bytes:
        urls.append(url)
        page = int(url.split("page%5Bnumber%5D=")[1].split("&")[0])
        return json.dumps(pages[page]).encode()

    monkeypatch.setattr(sources, "_get", fake_get)
    rows = fetch_fiscaldata_rows("/v2/test", "record_date,v", page_size=2)
    assert len(rows) == 3
    assert len(urls) == 2  # full first page -> fetched page 2; short page 2 -> stopped
    assert "page%5Bsize%5D=2" in urls[0] and "page%5Bnumber%5D=1" in urls[0]
    assert "page%5Bnumber%5D=2" in urls[1]


def test_fetch_fiscaldata_rows_follows_total_pages_past_capped_pages(monkeypatch):
    # Server caps page[size] below the requested value: every page is "short" but
    # meta.total-pages says there are 3 — the short-page heuristic alone would
    # silently truncate to one page.
    pages = {
        1: {"data": [{"v": "1"}], "meta": {"total-pages": 3}},
        2: {"data": [{"v": "2"}], "meta": {"total-pages": 3}},
        3: {"data": [{"v": "3"}], "meta": {"total-pages": 3}},
    }

    def fake_get(url: str, **kw) -> bytes:
        page = int(url.split("page%5Bnumber%5D=")[1].split("&")[0])
        return json.dumps(pages[page]).encode()

    monkeypatch.setattr(sources, "_get", fake_get)
    rows = fetch_fiscaldata_rows("/v2/test", "v", page_size=10000)
    assert [r["v"] for r in rows] == ["1", "2", "3"]  # all pages fetched, nothing truncated


def test_fetch_fiscaldata_rows_missing_data_key_is_an_error_not_eof(monkeypatch):
    monkeypatch.setattr(
        sources, "_get", lambda url, **kw: json.dumps({"error": "Invalid Query Param"}).encode()
    )
    with pytest.raises(ValueError, match="no 'data'"):
        fetch_fiscaldata_rows("/v2/test", "v")


def test_fetch_fiscaldata_rows_rejects_nonpositive_page_size():
    with pytest.raises(ValueError, match="page_size"):
        fetch_fiscaldata_rows("/v2/test", "v", page_size=0)  # would loop forever


def test_fetch_fiscaldata_debt_parses_string_values_and_scales(monkeypatch):
    rows = [
        {"record_date": "2026-06-09", "tot_pub_debt_out_amt": "39241722848798.66"},
        {"record_date": "2026-06-08", "tot_pub_debt_out_amt": "null"},  # garbled -> skipped
        {"record_date": "2026-06-07", "tot_pub_debt_out_amt": "NaN"},  # non-finite -> skipped
        {"record_date": "", "tot_pub_debt_out_amt": "1.0"},  # missing date -> skipped
    ]
    monkeypatch.setattr(sources, "fetch_fiscaldata_rows", lambda *a, **k: rows)
    meta, obs = fetch_fiscaldata_debt()
    assert obs == [(date(2026, 6, 9), pytest.approx(39.24172284879866))]  # USD trillions
    assert meta["series_id"] == "UST:DEBT"
    assert meta["source"] == "fiscaldata"
    assert meta["unit"] == "USD trillions"
    assert meta["frequency"] == "daily"


def test_fetch_fiscaldata_avg_rates_one_series_per_marketable_class(monkeypatch):
    rows = [
        {"record_date": "2026-05-31", "security_type_desc": "Marketable",
         "security_desc": "Treasury Bills", "avg_interest_rate_amt": "3.690"},
        {"record_date": "2026-05-31", "security_type_desc": "Marketable",
         "security_desc": "Treasury Notes", "avg_interest_rate_amt": "2.980"},
        {"record_date": "2026-05-31", "security_type_desc": "Marketable",
         "security_desc": "Treasury Bonds", "avg_interest_rate_amt": "3.220"},
        # Non-marketable namesake must NOT leak into the Bills series:
        {"record_date": "2026-05-31", "security_type_desc": "Non-marketable",
         "security_desc": "Treasury Bills", "avg_interest_rate_amt": "9.999"},
        {"record_date": "2026-05-31", "security_type_desc": "Marketable",
         "security_desc": "Federal Financing Bank", "avg_interest_rate_amt": "1.0"},  # unknown
    ]
    monkeypatch.setattr(sources, "fetch_fiscaldata_rows", lambda *a, **k: rows)
    series = fetch_fiscaldata_avg_rates()
    by_id = {meta["series_id"]: obs for meta, obs in series}
    assert set(by_id) == {"UST:AVG_RATE:BILLS", "UST:AVG_RATE:NOTES", "UST:AVG_RATE:BONDS"}
    assert by_id["UST:AVG_RATE:BILLS"] == [(date(2026, 5, 31), 3.690)]
    assert by_id["UST:AVG_RATE:NOTES"] == [(date(2026, 5, 31), 2.980)]
    metas = {meta["series_id"]: meta for meta, _ in series}
    assert metas["UST:AVG_RATE:BILLS"]["frequency"] == "monthly"


# --- US Treasury par yield curve (Atom/XML feed) ------------------------------------------

_PAR_YIELD_XML = """\
<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<feed xml:base="https://home.treasury.gov/x"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
      xmlns="http://www.w3.org/2005/Atom">
  <title type="text">DailyTreasuryYieldCurveRateData</title>
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-01-02T00:00:00</d:NEW_DATE>
    <d:BC_1MONTH m:type="Edm.Double">3.72</d:BC_1MONTH>
    <d:BC_3MONTH m:type="Edm.Double">3.80</d:BC_3MONTH>
    <d:BC_2YEAR m:type="Edm.Double">3.47</d:BC_2YEAR>
    <d:BC_10YEAR m:type="Edm.Double">4.19</d:BC_10YEAR>
    <d:BC_30YEAR m:type="Edm.Double">4.86</d:BC_30YEAR>
  </m:properties></content></entry>
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-01-05T00:00:00</d:NEW_DATE>
    <d:BC_2YEAR m:type="Edm.Double">3.50</d:BC_2YEAR>
    <d:BC_10YEAR m:type="Edm.Double"></d:BC_10YEAR>
  </m:properties></content></entry>
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-01-06T00:00:00</d:NEW_DATE>
    <d:BC_2YEAR m:type="Edm.Double">NaN</d:BC_2YEAR>
    <d:BC_10YEAR m:type="Edm.Double">4.25</d:BC_10YEAR>
  </m:properties></content></entry>
</feed>
"""


def test_parse_treasury_par_yield_extracts_2y_and_10y_skipping_gaps():
    out = parse_treasury_par_yield(_PAR_YIELD_XML)
    assert out["2Y"] == [
        (date(2026, 1, 2), 3.47),
        (date(2026, 1, 5), 3.50),
        # 2026-01-06 2Y cell is NaN -> skipped as garbled
    ]
    assert out["10Y"] == [
        (date(2026, 1, 2), 4.19),
        # 2026-01-05 10Y cell is blank -> skipped
        (date(2026, 1, 6), 4.25),
    ]


def test_fetch_treasury_par_yield_concatenates_years_and_labels(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: _PAR_YIELD_XML.encode())
    series = fetch_treasury_par_yield(start_year=date.today().year)  # single year -> one feed
    by_id = {meta["series_id"]: (meta, obs) for meta, obs in series}
    assert set(by_id) == {
        "UST:PAR_YIELD:3M", "UST:PAR_YIELD:2Y", "UST:PAR_YIELD:10Y", "UST:PAR_YIELD:30Y",
    }
    meta_2y, obs_2y = by_id["UST:PAR_YIELD:2Y"]
    assert meta_2y["source"] == "treasury"
    assert meta_2y["unit"] == "%"
    assert meta_2y["frequency"] == "daily"
    assert obs_2y[0] == (date(2026, 1, 2), 3.47)


# --- Eurostat (JSON-stat 2.0) --------------------------------------------------------------


def _eurostat_payload() -> dict:
    return {
        "version": "2.0",
        "class": "dataset",
        "id": ["freq", "unit", "coicop", "geo", "time"],
        "size": [1, 1, 1, 1, 4],
        # sparse: flat index "2" (2025-03) is absent — must be skipped, never filled
        "value": {"0": 2.5, "1": 2.3, "3": 2.2},
        "dimension": {
            "freq": {"category": {"index": {"M": 0}, "label": {"M": "Monthly"}}},
            "unit": {"category": {"index": {"RCH_A": 0}, "label": {"RCH_A": "Annual rate"}}},
            "coicop": {"category": {"index": {"CP00": 0}, "label": {"CP00": "All items"}}},
            "geo": {"category": {"index": {"EA": 0}, "label": {"EA": "Euro area"}}},
            "time": {"category": {"index": {
                "2025-01": 0, "2025-02": 1, "2025-03": 2, "2025-04": 3,
            }}},
        },
    }


def test_fetch_eurostat_parses_sparse_values_first_of_month(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(_eurostat_payload()).encode())
    meta, obs = fetch_eurostat(
        "prc_hicp_manr", {"geo": "EA", "coicop": "CP00", "unit": "RCH_A"},
        "EU:HICP:EA", "HICP inflation (YoY, monthly)", "% per year",
    )
    assert obs == [
        (date(2025, 1, 1), 2.5),
        (date(2025, 2, 1), 2.3),
        (date(2025, 4, 1), 2.2),  # 2025-03 sparse-missing -> skipped
    ]
    assert meta["source"] == "eurostat"
    assert meta["geo"] == "Euro area"  # label extracted from the pinned geo category


def test_fetch_eurostat_rejects_unpinned_dimension(monkeypatch):
    payload = _eurostat_payload()
    payload["size"] = [1, 1, 1, 2, 4]  # geo NOT pinned to one category
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    with pytest.raises(ValueError, match="geo"):
        fetch_eurostat("prc_hicp_manr", {}, "X", "x", "u")


def test_fetch_eurostat_rejects_invalid_pin_size_zero(monkeypatch):
    # the real shape of an invalid category pin (e.g. une_rt_m geo=EA20): size 0, value {}
    payload = _eurostat_payload()
    payload["size"] = [1, 1, 1, 0, 4]
    payload["value"] = {}
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    with pytest.raises(ValueError, match="geo"):
        fetch_eurostat("une_rt_m", {"geo": "EA20"}, "X", "x", "u")


def test_fetch_eurostat_rejects_array_value_encoding_loudly(monkeypatch):
    # JSON-stat 2.0 permits `value` as an ARRAY — unsupported, must be a clear attributed
    # error, not an AttributeError crash
    payload = _eurostat_payload()
    payload["value"] = [2.5, 2.3, None, 2.2]
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    with pytest.raises(ValueError, match="'value' encoding"):
        fetch_eurostat("prc_hicp_manr", {"geo": "EA"}, "X", "x", "u")


def test_fetch_eurostat_skips_non_finite_values(monkeypatch):
    payload = _eurostat_payload()
    payload["value"] = {"0": 2.5, "1": float("nan"), "3": float("inf")}
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    _, obs = fetch_eurostat("prc_hicp_manr", {"geo": "EA"}, "X", "x", "u")
    assert obs == [(date(2025, 1, 1), 2.5)]  # NaN/inf cells skipped as garbled


# --- BCB SGS (Banco Central do Brasil) --------------------------------------------------


def test_parse_br_date_dd_mm_yyyy():
    assert _parse_br_date("01/03/2026") == date(2026, 3, 1)
    assert _parse_br_date("31/12/1999") == date(1999, 12, 31)


def test_fetch_bcb_sgs_parses_scales_and_dedupes_decade_boundaries(monkeypatch):
    # Same payload returned for every decade window -> the inclusive-boundary dedupe must
    # collapse to the unique dates (not multiply them), and `scale` is a labelled conversion.
    payload = json.dumps(
        [
            {"data": "01/01/2024", "valor": "1000000"},
            {"data": "01/02/2024", "valor": ""},        # empty -> skipped, never faked
            {"data": "01/03/2024", "valor": "2000000"},
        ]
    ).encode()
    monkeypatch.setattr(sources, "_get_retry", lambda url, **kw: payload)
    meta, obs = fetch_bcb_sgs(
        99, "BCB:X", "x", "R$ trillion", "monthly", scale=1e-6, start_year=2020
    )
    assert meta["source"] == "bcb"
    assert obs == [(date(2024, 1, 1), 1.0), (date(2024, 3, 1), 2.0)]  # scaled, gap skipped


def test_fetch_bcb_sgs_compress_steps_keeps_change_points(monkeypatch):
    payload = json.dumps(
        [
            {"data": "01/01/2024", "valor": "14.50"},
            {"data": "02/01/2024", "valor": "14.50"},  # repeat -> dropped
            {"data": "03/01/2024", "valor": "14.25"},  # change -> kept
            {"data": "04/01/2024", "valor": "14.25"},  # repeat -> dropped
            {"data": "05/01/2024", "valor": "14.00"},  # last -> kept
        ]
    ).encode()
    monkeypatch.setattr(sources, "_get_retry", lambda url, **kw: payload)
    _, obs = fetch_bcb_sgs(
        432, "BCB:SELIC_TARGET", "x", "%", "daily", start_year=2024, compress_steps=True
    )
    assert obs == [
        (date(2024, 1, 1), 14.50),
        (date(2024, 1, 3), 14.25),
        (date(2024, 1, 5), 14.00),
    ]


# --- IBGE SIDRA -------------------------------------------------------------------------


def test_sidra_period_monthly_and_quarterly():
    assert _sidra_period("202605", "monthly") == date(2026, 5, 1)
    assert _sidra_period("202601", "quarterly") == date(2026, 3, 1)   # Q1 -> month 3
    assert _sidra_period("202504", "quarterly") == date(2025, 12, 1)  # Q4 -> month 12
    with pytest.raises(ValueError):
        _sidra_period("202609", "quarterly")  # quarter 9 is invalid


_SIDRA_PIB = [
    # legend first: the period dimension is D4 ("Trimestre"), NOT D3 ("Setores")
    {"V": "Valor", "D3C": "Setores (Código)", "D3N": "Setores",
     "D4C": "Trimestre (Código)", "D4N": "Trimestre"},
    {"V": "3235708", "D3C": "90707", "D4C": "202503"},
    {"V": "...", "D3C": "90707", "D4C": "202504"},        # sentinel -> skipped
    {"V": "3250979", "D3C": "90707", "D4C": "202601"},
]


def test_fetch_sidra_finds_period_in_d4_and_skips_sentinels(monkeypatch):
    monkeypatch.setattr(sources, "_get_retry", lambda url, **kw: json.dumps(_SIDRA_PIB).encode())
    meta, obs = fetch_sidra(
        1846, 585, "IBGE:PIB", "GDP", "R$ trillion", frequency="quarterly",
        classifications=[(11255, 90707)], scale=1e-6,
    )
    assert meta["source"] == "ibge"
    assert obs == [(date(2025, 9, 1), 3.235708), (date(2026, 3, 1), 3.250979)]


def test_fetch_sidra_raises_when_no_period_dimension(monkeypatch):
    legend_only = [{"V": "Valor", "D1C": "Brasil (Código)"}, {"V": "1", "D1C": "1"}]
    monkeypatch.setattr(sources, "_get_retry", lambda url, **kw: json.dumps(legend_only).encode())
    with pytest.raises(ValueError, match="no period dimension"):
        fetch_sidra(1, 1, "X", "x", "u")


# --- BCB Focus (market expectations) ----------------------------------------------------


def test_fetch_bcb_focus_12m_parses_and_skips_blank(monkeypatch):
    # one short page (< the 10000 page size) stops the OData walk; the blank-Data row and
    # the null-median row are skipped, never faked.
    page = {
        "value": [
            {"Data": "2026-01-02", "Mediana": 4.01},
            {"Data": "2026-01-03", "Mediana": 4.05},
            {"Data": "", "Mediana": 9.9},
            {"Data": "2026-01-06", "Mediana": None},
        ]
    }
    monkeypatch.setattr(sources, "_get_retry", lambda url, **kw: json.dumps(page).encode())
    meta, obs = fetch_bcb_focus_12m("IPCA", "BCB:FOCUS_IPCA_12M", "x", "% per year")
    assert meta["source"] == "bcb_focus"
    assert obs == [(date(2026, 1, 2), 4.01), (date(2026, 1, 3), 4.05)]


def test_bcb_get_json_retries_transient_html_then_succeeds(monkeypatch):
    # the BCB occasionally returns a 200 + HTML throttle page; _bcb_get_json must retry it
    # rather than fail the series on a transient decode error.
    seq = [b"<html>Service unavailable</html>",
           json.dumps([{"data": "01/01/2024", "valor": "1.0"}]).encode()]
    monkeypatch.setattr(sources, "_get_retry", lambda url, **kw: seq.pop(0))
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    assert sources._bcb_get_json("http://x") == [{"data": "01/01/2024", "valor": "1.0"}]


def test_bcb_get_json_raises_on_persistent_non_json(monkeypatch):
    monkeypatch.setattr(sources, "_get_retry", lambda url, **kw: b"<html>down</html>")
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    with pytest.raises(json.JSONDecodeError):  # persistent failure attributed, never silent
        sources._bcb_get_json("http://x", attempts=2)
