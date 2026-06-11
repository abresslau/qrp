"""Parser/fetcher tests for macro.sources — fixture payloads only, no live network."""

from __future__ import annotations

import json
import urllib.error
from datetime import date

import pytest

import macro.sources as sources
from macro.sources import (
    _parse_period,
    fetch_ecb,
    fetch_eurostat,
    fetch_fiscaldata_avg_rates,
    fetch_fiscaldata_debt,
    fetch_fiscaldata_rows,
    fetch_oecd_cpi,
    parse_sdmx_csv,
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
    def fake_get(url: str) -> bytes:
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

    def fake_get(url: str) -> bytes:
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

    def fake_get(url: str) -> bytes:
        page = int(url.split("page%5Bnumber%5D=")[1].split("&")[0])
        return json.dumps(pages[page]).encode()

    monkeypatch.setattr(sources, "_get", fake_get)
    rows = fetch_fiscaldata_rows("/v2/test", "v", page_size=10000)
    assert [r["v"] for r in rows] == ["1", "2", "3"]  # all pages fetched, nothing truncated


def test_fetch_fiscaldata_rows_missing_data_key_is_an_error_not_eof(monkeypatch):
    monkeypatch.setattr(
        sources, "_get", lambda url: json.dumps({"error": "Invalid Query Param"}).encode()
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
