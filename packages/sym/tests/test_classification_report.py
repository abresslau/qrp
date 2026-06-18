"""Golden/snapshot regression for the per-pass classification report lines.

Pins the EXACT wording every fill source's renderer emits, so a future change to a
report line (like the empty-scope "— not queried" drift caught by hand in the registry
review) fails a test instead of silently shipping. DB-free, network-free: each renderer
reads only its source's ``last_*`` side-channels, so a ``SimpleNamespace`` with the right
attributes stands in for the real source (no ctor, no I/O).
"""

from __future__ import annotations

from types import SimpleNamespace

from sym.classification.gics import ClassificationSummary
from sym.classification.registry import (
    _render_b3,
    _render_fmp,
    _render_llm,
    _render_sec,
    _render_yahoo,
)
from sym.classification.yahoo_profile import MAX_CONSECUTIVE_ERRORS

# A representative summary reused across passes: a bit of every counter so the shared
# _header format is fully exercised (inserted / upgraded / unchanged / superseded / failed).
_SUMMARY = ClassificationSummary(
    rows_inserted=2, rows_updated=1, unchanged=3, rows_closed=1, failed=0, failures=[]
)


def test_render_b3_golden():
    src = SimpleNamespace(
        last_unmapped={"PETR4": "Energia"},
        last_conflicts={"VALE3": ("Mineração", "Metais")},
        last_unmatched=["XYZ3"],
    )
    assert _render_b3(src, _SUMMARY, 7) == [
        "b3 fill pass: 7 in-scope active; 2 inserted, 1 upgraded, 3 unchanged, "
        "1 superseded, 0 failed; 1 unmapped segments (1 tickers), 1 view conflicts, "
        "1 in-scope unfilled",
        "  unmapped B3 segment: PETR4: 'Energia'",
        "  B3 view conflict (skipped): VALE3: 'Mineração' vs 'Metais'",
        "  no B3 classification for: XYZ3",
    ]


def test_render_sec_golden_includes_ambiguous_ticker_line():
    src = SimpleNamespace(
        last_unmapped_sic={"WAT": ("9995", "Non-Classifiable")},
        last_unmatched=["NOCIK"],
        last_skipped_non_us=["BMW"],
        last_errors={"BAD": "HTTP 404"},
        last_ambiguous_ticker={"ZZZ": ["0000000111", "0000000222"]},
    )
    assert _render_sec(src, _SUMMARY, 5) == [
        "sec_sic fill pass: 5 in-scope active; 2 inserted, 1 upgraded, 3 unchanged, "
        "1 superseded, 0 failed; 1 unmapped SIC, 1 no-CIK/no-SIC, 1 non-US skipped, "
        "1 lookup error(s), 1 ambiguous ticker(s)",
        "  unmapped SIC: WAT: 9995 (Non-Classifiable)",
        "  sec_sic lookup error: BAD: HTTP 404",
        "  sec_sic ambiguous ticker ZZZ: CIKs 0000000111, 0000000222 (resolved to active filer)",
    ]


def test_render_fmp_golden():
    src = SimpleNamespace(
        last_unmapped_sector={"ABC": "Conglomerates"},
        last_unmatched=["NP"],
        last_skipped_fund=["SPY"],
        last_unmapped_mic=["WAT"],
        last_errors={"BAD": "HTTP 429"},
    )
    assert _render_fmp(src, _SUMMARY, 4) == [
        "fmp fill pass (keyed): 4 in-scope active; 2 inserted, 1 upgraded, 3 unchanged, "
        "1 superseded, 0 failed; 1 unmapped sector, 1 no-profile, 1 funds skipped, "
        "1 unmappable MIC, 1 fetch error(s)",
        "  unmapped FMP sector: ABC: 'Conglomerates'",
        "  fmp fetch error: BAD: HTTP 429",
    ]


def test_render_yahoo_golden_includes_circuit_breaker_line():
    src = SimpleNamespace(
        last_unmapped_sector={"ABC.L": "Conglomerates"},
        last_unmatched=["NP.L"],
        last_unmapped_mic=["WAT"],
        last_errors={"BAD.L": "HTTP 401"},
        last_short_circuited=["X.L", "Y.L"],
    )
    assert _render_yahoo(src, _SUMMARY, 6) == [
        "yahoo_profile fill pass: 6 in-scope active; 2 inserted, 1 upgraded, 3 unchanged, "
        "1 superseded, 0 failed; 1 unmapped sector, 1 no-profile, 1 unmappable MIC, "
        "1 fetch error(s), 2 not attempted (circuit-breaker)",
        "  unmapped Yahoo sector: ABC.L: 'Conglomerates'",
        "  yahoo_profile fetch error: BAD.L: HTTP 401",
        f"  yahoo_profile circuit-breaker tripped after {MAX_CONSECUTIVE_ERRORS} "
        "consecutive errors; 2 name(s) not attempted (retried next run)",
    ]


def test_render_yahoo_golden_no_circuit_breaker_when_not_tripped():
    # the short-circuit line + count must be ABSENT when the breaker never tripped
    src = SimpleNamespace(
        last_unmapped_sector={},
        last_unmatched=["NP.L"],
        last_unmapped_mic=[],
        last_errors={},
        last_short_circuited=[],
    )
    assert _render_yahoo(src, _SUMMARY, 6) == [
        "yahoo_profile fill pass: 6 in-scope active; 2 inserted, 1 upgraded, 3 unchanged, "
        "1 superseded, 0 failed; 0 unmapped sector, 1 no-profile, 0 unmappable MIC, "
        "0 fetch error(s)",
    ]


def test_render_llm_golden():
    src = SimpleNamespace(last_unmatched=["FUND1", "FUND2"], last_mic_mismatch=["XUS"])
    assert _render_llm(src, _SUMMARY, 3) == [
        "llm fill pass (opt-in, low-trust): 3 in-scope active; 2 inserted, 1 upgraded, "
        "3 unchanged, 1 superseded, 0 failed; 2 unmatched (funds/uncovered), 1 MIC mismatch",
    ]
