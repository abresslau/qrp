"""Shared LLM-http classifier base + Perplexity/Google gating — fake client, no network."""

from __future__ import annotations

from sym.classification._llm_classifier import (
    MAX_CONSECUTIVE_ERRORS,
    LlmClassifierError,
    LlmGicsSourceBase,
    map_answer_to_sector,
)
from sym.classification.gics import SecurityIdentity
from sym.classification.google_gemini import GoogleGeminiGicsSource, google_enabled
from sym.classification.perplexity import PerplexityGicsSource, perplexity_enabled


def test_map_answer_to_sector_finds_canonical_sector():
    assert map_answer_to_sector("Information Technology") == "Information Technology"
    assert map_answer_to_sector("The sector is Financials.") == "Financials"
    assert map_answer_to_sector("Consumer Discretionary") == "Consumer Discretionary"
    assert map_answer_to_sector("I'm not sure, maybe tech?") is None  # off-taxonomy → None
    assert map_answer_to_sector(None) is None


class _FakeClient:
    def __init__(self, answers, raises=None):
        self._answers = answers
        self._raises = raises or set()
        self.calls: list[str] = []

    def sector_answer(self, ticker, mic, name):
        self.calls.append(ticker)
        if ticker in self._raises:
            raise LlmClassifierError("quota")
        return self._answers.get(ticker)


class _Src(LlmGicsSourceBase):
    source = "perplexity"


def test_base_classifies_validates_and_records_offtaxonomy():
    client = _FakeClient({"AAPL": "Information Technology", "ZZZ": "definitely not a sector"})
    src = _Src(client)
    out = src.fetch(
        [
            SecurityIdentity("F_AAPL", ticker="AAPL", mic="XNAS"),
            SecurityIdentity("F_ZZZ", ticker="ZZZ", mic="XNAS"),
        ]
    )
    assert out["F_AAPL"].sector_name == "Information Technology"
    assert out["F_AAPL"].source == "perplexity"
    assert "ZZZ" in src.last_unmapped
    assert "F_ZZZ" not in out


def test_base_circuit_breaker_trips_on_consecutive_errors():
    n = MAX_CONSECUTIVE_ERRORS + 4
    ids = [SecurityIdentity(f"F{i}", ticker=f"T{i}", mic="XNAS") for i in range(n)]
    client = _FakeClient({}, raises={f"T{i}" for i in range(n)})
    src = _Src(client)
    out = src.fetch(ids)
    assert out == {}
    assert len(client.calls) == MAX_CONSECUTIVE_ERRORS  # stopped after K consecutive errors
    assert len(src.last_short_circuited) == n - MAX_CONSECUTIVE_ERRORS


def test_errors_interleaved_with_hits_never_trip_breaker():
    ids, answers, raises = [], {}, set()
    for i in range(12):
        ids.append(SecurityIdentity(f"F{i}", ticker=f"T{i}", mic="XNAS"))
        if i % 2 == 0:
            raises.add(f"T{i}")
        else:
            answers[f"T{i}"] = "Energy"
    src = _Src(_FakeClient(answers, raises=raises))
    out = src.fetch(ids)
    assert src.last_short_circuited == []
    assert len(out) == 6


def test_gating_follows_env_keys(monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    assert perplexity_enabled() is False
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
    assert perplexity_enabled() is True

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert google_enabled() is False
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert google_enabled() is True


def test_concrete_sources_carry_their_tag():
    assert PerplexityGicsSource(client=_FakeClient({})).source == "perplexity"
    assert GoogleGeminiGicsSource(client=_FakeClient({})).source == "google"
