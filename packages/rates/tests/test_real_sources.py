"""Real (inflation-linked) curve additions + the new Banco de España daily curve.

Pins the enrichment contract: BoC RRB → real 30y, RBA indexed → real 10y, RBNZ dated linkers →
real with a tenor computed from the bond's maturity date, and the BdE wide/Latin-1/Spanish-date CSV
→ ES govt nominal points at the clean constant-maturity tenors only. All pure (no network).
"""

from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest

from rates.sources.aft_fr import parse_workbook as aft_parse
from rates.sources.aft_tec10 import CurveLayoutError as Tec10LayoutError
from rates.sources.aft_tec10 import parse_tec10
from rates.sources.anbima import parse_ms as anbima_parse
from rates.sources.banco_espana import parse_csv as bde_parse
from rates.sources.boc import parse_observations
from rates.sources.hkma import parse_records as hkma_parse
from rates.sources.oecd_ltir import parse_ltir as oecd_ltir_parse
from rates.sources.rba import parse_csv as rba_parse
from rates.sources.rbnz import parse_workbook


def test_boc_emits_rrb_as_real_long_point():
    payload = {"observations": [
        {"d": "2026-06-29",
         "BD.CDN.10YR.DQ.YLD": {"v": "3.21"},
         "BD.CDN.RRB.DQ.YLD": {"v": "1.71"}},
    ]}
    pts = parse_observations(payload)
    nominal = [p for p in pts if p.basis == "nominal"]
    real = [p for p in pts if p.basis == "real"]
    assert ("CA", 10.0, 3.21) == (nominal[0].country, nominal[0].tenor, nominal[0].value)
    assert len(real) == 1 and real[0].tenor == 30.0 and real[0].value == 1.71


def test_rba_emits_indexed_bond_as_real_10y():
    csv_text = (
        "Title,AU 2yr,AU 10yr,Indexed\n"
        "Series ID,FCMYGBAG2D,FCMYGBAG10D,FCMYGBAGID\n"
        "24-Jun-2026,3.10,4.20,2.499\n"
    )
    pts = rba_parse(csv_text)
    by = {(p.basis, p.tenor): p.value for p in pts}
    assert by[("nominal", 2.0)] == 3.10
    assert by[("nominal", 10.0)] == 4.20
    assert by[("real", 10.0)] == 2.499  # FCMYGBAGID indexed bond → real


def test_bde_parses_clean_govt_tenors_only_from_wide_latin1_csv():
    # code row (we map on CÓDIGO), then descrip/freq metadata, then one Spanish-dated data row.
    # Columns: a range bill (skip), Letras 6m, Bonos 3y, Bonos 10y, an AIAF private series (skip).
    rows = [
        '"CÓDIGO DE LA SERIE",D_DTES00B7,D_DTES00S7,D_G0B1F0ZN,D_G0B1F0ZP,D_KG8SZ03M',
        '"ALIAS DE LA SERIE","TI_1_3.1","TI_1_3.2","TI_1_3.8","TI_1_3.11","TI_1_3.13"',
        '"FRECUENCIA","DIARIA","DIARIA","DIARIA","DIARIA","DIARIA"',
        '"26 JUN 2026",2.276,2.410,2.630,3.310,9.99',
        '"25 JUN 2026",2.153,"_",2.669,3.310,9.88',
    ]
    pts = bde_parse("\n".join(rows))
    latest = [p for p in pts if p.as_of_date == date(2026, 6, 26)]
    by = {p.tenor: p.value for p in latest}
    assert by == {0.5: 2.410, 3.0: 2.630, 10.0: 3.310}  # range bill + AIAF private excluded
    assert all(p.country == "ES" and p.basis == "nominal" and p.curve_set == "govt" for p in pts)
    # the 6m on 25 Jun is "_" (missing) → skipped, not zero
    assert {p.tenor for p in pts if p.as_of_date == date(2026, 6, 25)} == {3.0, 10.0}


def _xlsx(rows: list[list]) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_aft_emits_real_and_breakeven_scaled_from_decimals():
    # title/header preamble (non-date rows skipped), then data rows: date, real, nominal, breakeven
    # as DECIMAL fractions (x100 -> %). A blank real (early history) → only the breakeven point.
    rows = [
        ["Rendement des OAT indexées", None, None, None],
        [None, "zone euro 10 ans", None, None],
        [date(2026, 6, 1), 0.01462, 0.03654, 0.02192],
        [date(2013, 11, 1), None, None, 0.01766],  # early: breakeven only, real blank
    ]
    pts = aft_parse(_xlsx(rows))
    by = {(p.basis, p.as_of_date): p for p in pts}
    assert all(p.country == "FR" and p.curve_set == "govt" and p.tenor == 10.0 for p in pts)
    assert abs(by[("real", date(2026, 6, 1))].value - 1.462) < 1e-9
    assert abs(by[("inflation", date(2026, 6, 1))].value - 2.192) < 1e-9
    # real + breakeven == nominal (source identity), and the blank-real early row → inflation only
    assert ("real", date(2013, 11, 1)) not in by
    assert abs(by[("inflation", date(2013, 11, 1))].value - 1.766) < 1e-9


def test_tec10_parses_daily_fr_nominal_10y():
    html = "<p>TEC 10 index on Wednesday 01 July 2026: 3.65%</p>"
    pt = parse_tec10(html)
    assert (pt.country, pt.currency, pt.curve_set, pt.basis, pt.rate_type, pt.tenor) == (
        "FR", "EUR", "govt", "nominal", "yield", 10.0)
    assert pt.as_of_date == date(2026, 7, 1) and pt.value == 3.65


def test_tec10_fails_loud_on_layout_drift():
    with pytest.raises(Tec10LayoutError):
        parse_tec10("<p>no tec ten value here</p>")


def test_hkma_daily_maps_terms_to_tenors_and_skips_unknowns():
    records = [
        {"end_of_date": "2026-06-30", "term": "1W", "issue_no": "Q1", "yield": 2.45, "price": None},
        {"end_of_date": "2026-06-30", "term": "3M", "issue_no": "Q2", "yield": 2.45},
        {"end_of_date": "2026-06-30", "term": "12M", "issue_no": "Y1", "yield": 2.66},
        {"end_of_date": "2026-06-30", "term": "2 YR", "issue_no": "N1", "yield": 2.901},
        {"end_of_date": "2026-06-30", "term": "5 YR", "yield": None},  # null yield → skip
        {"end_of_date": "2026-06-30", "term": "weird", "yield": 3.0},  # unparseable term → skip
    ]
    pts = hkma_parse(records)
    by = {p.tenor: p.value for p in pts}
    assert by == {round(7 / 365, 6): 2.45, 0.25: 2.45, 1.0: 2.66, 2.0: 2.901}
    assert all(p.country == "HK" and p.currency == "HKD" and p.basis == "nominal"
               and p.curve_set == "govt" and p.rate_type == "yield" for p in pts)
    assert all(p.as_of_date == date(2026, 6, 30) for p in pts)


def test_anbima_emits_nominal_and_real_dedupes_ltn_over_ntnf_excludes_legacy():
    text = (
        "ANBIMA - Associacao...\n\n"
        "Titulo@Data Referencia@Codigo SELIC@Data Base/Emissao@Data Vencimento@Tx. Compra@"
        "Tx. Venda@Tx. Indicativas@PU@Desvio\n"
        # LTN short, LTN 2029, NTN-F same 2029 date (should lose to LTN), NTN-F long 2035
        "LTN@20260630@100000@20230106@20260701@14,3495@14,3196@14,3196@999,47@0\n"
        "LTN@20260630@100000@20240105@20290101@13,95@13,94@13,953@821,64@0\n"
        "NTN-F@20260630@950199@20100101@20290101@13,90@13,88@13,89@1050,0@0\n"
        "NTN-F@20260630@950199@20100101@20350101@14,20@14,18@14,19@980,0@0\n"
        "NTN-B@20260630@760199@20000715@20350515@8,1311@8,0984@8,1098@4181,03@0\n"  # real
        "NTN-C@20260630@770100@20000701@20310101@8,28@7,95@8,0626@7992,77@0\n"  # IGP-M excluded
        "LFT@20260630@210100@20000701@20260901@-0,03@-0,07@-0,06@19326,08@0\n"  # floater excluded
    )
    pts = anbima_parse(text)
    by = {(p.basis, round(p.tenor, 4)): p for p in pts}
    assert all(p.country == "BR" and p.curve_set == "anbima" and p.rate_type == "yield"
               for p in pts)
    # NTN-C + LFT excluded; LTN 2029 wins over the same-maturity NTN-F (zero-coupon preferred)
    t2029 = round((date(2029, 1, 1) - date(2026, 6, 30)).days / 365, 4)
    assert by[("nominal", t2029)].value == 13.953  # the LTN, not the NTN-F 13.89
    # NTN-F still populates the 2035 long tenor no LTN covers
    t2035 = round((date(2035, 1, 1) - date(2026, 6, 30)).days / 365, 4)
    assert by[("nominal", t2035)].value == 14.19
    # real NTN-B present
    t_real = round((date(2035, 5, 15) - date(2026, 6, 30)).days / 365, 4)
    assert by[("real", t_real)].value == 8.1098
    assert {p.basis for p in pts} == {"nominal", "real"}


def test_oecd_ltir_parses_ch_10y_yield_at_month_end():
    csv_text = (
        "STRUCTURE,REF_AREA,FREQ,MEASURE,UNIT_MEASURE,TIME_PERIOD,OBS_VALUE\n"
        "x,CHE,M,IRLT,PA,2026-05,0.44\n"
        "x,CHE,M,IRLT,PA,2026-04,0.45\n"
        "x,CHE,M,IR3TIB,PA,2026-05,-0.04\n"  # short-term rate → filtered out (MEASURE != IRLT)
    )
    pts = oecd_ltir_parse(csv_text, country="CH", currency="CHF")
    by = {p.as_of_date: p.value for p in pts}
    assert by == {date(2026, 5, 31): 0.44, date(2026, 4, 30): 0.45}  # month-END dated
    assert all(p.country == "CH" and p.currency == "CHF" and p.curve_set == "govt"
               and p.basis == "nominal" and p.rate_type == "yield" and p.tenor == 10.0 for p in pts)


def _b2_workbook(rows: list[list]) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_rbnz_linker_tenor_computed_from_maturity_date():
    # header rows then a Series Id row then data. One nominal 10y + two dated real linkers.
    rows = [
        ["group"], ["label"], [], [],
        ["Series Id", "INM.DG110.NZZCF", "INM.DG29.NS3009ZC", "INM.DG29.NS4009ZC"],
        [date(2026, 6, 29), 4.50, 1.52, 2.79],
    ]
    pts = parse_workbook(_b2_workbook(rows))
    nominal = [p for p in pts if p.basis == "nominal"]
    real = sorted((p for p in pts if p.basis == "real"), key=lambda p: p.tenor)
    assert nominal[0].tenor == 10.0 and nominal[0].value == 4.50
    # 2030-09-20 − 2026-06-29 ≈ 4.23y ; 2040-09-20 − 2026-06-29 ≈ 14.23y
    assert len(real) == 2
    assert abs(real[0].tenor - (date(2030, 9, 20) - date(2026, 6, 29)).days / 365.25) < 1e-6
    assert real[0].value == 1.52 and real[1].value == 2.79
    assert abs(real[1].tenor - (date(2040, 9, 20) - date(2026, 6, 29)).days / 365.25) < 1e-6
