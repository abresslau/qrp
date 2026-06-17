"""LLM gap-fill source tests (multi-source, AC #4) — no network, no LLM call."""

from __future__ import annotations

import contextlib
import json
from datetime import date

import pytest

from sym.classification.gics import SecurityIdentity, apply_classifications
from sym.classification.llm import (
    GICS_SECTORS,
    LlmClassificationError,
    LlmGicsSource,
    LlmRecord,
    load_llm_classifications,
)

# --- the shipped artifact loads + is sane -----------------------------------------------


def test_shipped_artifact_loads_and_is_all_gics():
    records = load_llm_classifications()
    assert records, "the shipped artifact should carry at least one classification"
    for rec in records:
        assert rec.sector in GICS_SECTORS
        assert rec.ticker == rec.ticker.upper()


def test_shipped_artifact_excludes_funds():
    # the residual funds/ETFs must NOT be classified (a fund has no GICS sector)
    tickers = {r.ticker for r in load_llm_classifications()}
    for fund in ("JAVA", "SMT", "PCLN", "SHLD", "PCL", "EMC"):
        assert fund not in tickers


# --- load validation --------------------------------------------------------------------


def _write(tmp_path, payload):
    p = tmp_path / "art.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_load_rejects_non_gics_sector(tmp_path):
    path = _write(tmp_path, {"classifications": [{"ticker": "X", "sector": "Technology"}]})
    # "Technology" is Yahoo's label, NOT a GICS sector — must be refused at load
    with pytest.raises(LlmClassificationError, match="non-GICS sector"):
        load_llm_classifications(path)


def test_load_rejects_missing_fields(tmp_path):
    path = _write(tmp_path, {"classifications": [{"ticker": "X"}]})
    with pytest.raises(LlmClassificationError, match="missing ticker/sector"):
        load_llm_classifications(path)


def test_load_missing_file_is_explicit_error(tmp_path):
    with pytest.raises(LlmClassificationError, match="not found"):
        load_llm_classifications(tmp_path / "nope.json")


def test_load_no_classifications_list(tmp_path):
    path = _write(tmp_path, {"meta": "x"})
    with pytest.raises(LlmClassificationError, match="no 'classifications' list"):
        load_llm_classifications(path)


# --- fetch ------------------------------------------------------------------------------


def test_fetch_classifies_sector_only_with_llm_provenance():
    src = LlmGicsSource(records=[LlmRecord(ticker="KLG", sector="Consumer Staples", mic="XNYS")])
    out = src.fetch([SecurityIdentity("FIGI_KLG", ticker="KLG", mic="XNYS")])

    assert set(out) == {"FIGI_KLG"}
    c = out["FIGI_KLG"]
    assert c.sector_name == "Consumer Staples"
    assert c.source == "llm"
    assert c.industry_group_name is None
    assert c.industry_name is None


def test_fetch_unmatched_ticker_recorded_not_guessed():
    src = LlmGicsSource(records=[LlmRecord(ticker="KLG", sector="Consumer Staples", mic="XNYS")])
    out = src.fetch([SecurityIdentity("FIGI_FUND", ticker="JAVA", mic="XNAS")])

    assert out == {}
    assert src.last_unmatched == ["JAVA"]


def test_fetch_mic_mismatch_not_applied():
    # a foreign listing sharing a US ticker must never inherit the record's sector
    src = LlmGicsSource(records=[LlmRecord(ticker="CMA", sector="Financials", mic="XNYS")])
    out = src.fetch([SecurityIdentity("FIGI_AV", ticker="CMA", mic="XLON")])

    assert out == {}
    assert src.last_mic_mismatch == ["CMA"]


def test_fetch_mic_less_identity_matches_ticker_only():
    src = LlmGicsSource(records=[LlmRecord(ticker="CMA", sector="Financials", mic="XNYS")])
    out = src.fetch([SecurityIdentity("FIGI_CMA", ticker="CMA")])

    assert out["FIGI_CMA"].sector_name == "Financials"


# --- AC8: provenance persists end-to-end ------------------------------------------------


class _RecordingConn:
    def __init__(self):
        self.inserts: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        if sql.upper().lstrip().startswith("INSERT"):
            self.inserts.append((sql, params))
        return _NullCursor()

    def transaction(self):
        return contextlib.nullcontext()


class _NullCursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_apply_classifications_persists_llm_provenance():
    plans = list(
        LlmGicsSource(records=[LlmRecord(ticker="ZEUS", sector="Materials", mic="XNYS")])
        .fetch([SecurityIdentity("FIGI_ZEUS", ticker="ZEUS", mic="XNYS")])
        .values()
    )
    conn = _RecordingConn()
    summary = apply_classifications(conn, plans, as_of_date=date(2026, 6, 17))

    assert summary.rows_inserted == 1
    _sql, params = conn.inserts[0]
    assert "llm" in params
    assert "Materials" in params
