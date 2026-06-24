"""Fed GSW CSV parser — pure, no network. Synthetic CSVs matching the feds200628/200805 layout."""

from __future__ import annotations

from datetime import date

from rates.sources.fed_gsw import _SPECS_NOMINAL, _SPECS_TIPS, parse_gsw

# A nominal-file slice: preamble, a header with the SVEN families + parameters/special-forward
# columns we must IGNORE (BETA*, TAU*, SVEN1F*), then two business days (one with an NA cell).
_NOMINAL_CSV = """\
"Note: research product, not an official release."

Series,Compounding Convention,Mnemonic(s)
Zero-coupon yield,Continuously Compounded,SVENYXX

Date,BETA0,BETA1,SVEN1F01,SVENY01,SVENY02,SVENPY01,SVENPY02,SVENF01,SVENF02,TAU1
2024-01-02,3.9,-1.2,4.10,4.50,4.20,4.55,4.25,4.40,4.10,1.5
2024-01-03,3.8,-1.1,4.00,4.40,NA,4.45,4.15,4.30,4.00,1.4
"""

_TIPS_CSV = """\
"Note: research product."

Date,BETA0,TIPSY02,TIPSY05,TIPSPY02,TIPSF02,BKEVEN02,BKEVENPY02,BKEVENF02,TIPS5F5
2024-01-02,1.1,1.80,2.00,1.85,1.75,2.40,2.42,2.38,2.50
"""


def test_nominal_maps_spot_par_forward_and_skips_params_and_specials():
    pts = parse_gsw(_NOMINAL_CSV, _SPECS_NOMINAL)
    # only SVENY/SVENPY/SVENF kept — BETA*, SVEN1F*, TAU* dropped.
    kept = {(p.basis, p.rate_type, p.tenor) for p in pts}
    assert kept == {
        ("nominal", "spot", 1.0), ("nominal", "spot", 2.0),
        ("nominal", "par", 1.0), ("nominal", "par", 2.0),
        ("nominal", "forward", 1.0), ("nominal", "forward", 2.0),
    }
    spot01 = next(p for p in pts if p.rate_type == "spot" and p.tenor == 1.0
                  and p.as_of_date == date(2024, 1, 2))
    assert spot01.value == 4.50
    assert spot01.country == "US" and spot01.currency == "USD" and spot01.curve_set == "gsw"


def test_na_cell_is_skipped_not_invented():
    pts = parse_gsw(_NOMINAL_CSV, _SPECS_NOMINAL)
    day2 = [p for p in pts if p.as_of_date == date(2024, 1, 3)]
    # SVENY02 was NA on 2024-01-03 → no spot/2y node that day; the rest are present.
    assert not any(p.rate_type == "spot" and p.tenor == 2.0 for p in day2)
    assert any(p.rate_type == "spot" and p.tenor == 1.0 for p in day2)


def test_tips_maps_real_and_breakeven_and_skips_5f5():
    pts = parse_gsw(_TIPS_CSV, _SPECS_TIPS)
    kept = {(p.basis, p.rate_type, p.tenor) for p in pts}
    assert kept == {
        ("real", "spot", 2.0), ("real", "spot", 5.0),
        ("real", "par", 2.0), ("real", "forward", 2.0),
        ("inflation", "spot", 2.0), ("inflation", "par", 2.0), ("inflation", "forward", 2.0),
    }
    be = next(p for p in pts if p.basis == "inflation" and p.rate_type == "spot")
    assert be.value == 2.40 and be.tenor == 2.0


def test_empty_or_headerless_text_is_empty():
    assert parse_gsw("", _SPECS_NOMINAL) == []
    assert parse_gsw("no header here\njust,junk\n", _SPECS_NOMINAL) == []
