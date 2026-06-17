"""Fill-source registry tests (the AC1 generalization) — no DB, no network."""

from __future__ import annotations

import pytest

import sym.classification.registry as reg
from sym.classification.gics import (
    SOURCE_PRECEDENCE,
    ClassificationSummary,
    GicsClassification,
    SecurityIdentity,
)
from sym.classification.registry import FillSpec, fill_specs, run_fill_pass, validate_fill_specs


def test_fill_specs_cover_every_source_in_precedence_order():
    names = [s.name for s in fill_specs(llm_enabled=True)]
    assert "financedatabase" not in names  # the primary is the CLI anchor, not a fill spec
    ranks = [SOURCE_PRECEDENCE[n] for n in names]
    assert ranks == sorted(ranks)  # ascending precedence
    assert len(set(ranks)) == len(ranks)  # no duplicate ranks
    # every known source is either the primary or a registered fill spec
    assert set(names) | {"financedatabase"} == set(SOURCE_PRECEDENCE)


def test_fmp_gate_follows_env_key(monkeypatch):
    fmp = next(s for s in fill_specs(llm_enabled=True) if s.name == "fmp")
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    assert fmp.gate() is False
    monkeypatch.setenv("FMP_API_KEY", "k")
    assert fmp.gate() is True


def test_llm_gate_follows_flag_and_always_on_sources_have_no_gate():
    assert next(s for s in fill_specs(llm_enabled=False) if s.name == "llm").gate() is False
    assert next(s for s in fill_specs(llm_enabled=True) if s.name == "llm").gate() is True
    assert next(s for s in fill_specs(llm_enabled=True) if s.name == "b3").gate is None
    assert next(s for s in fill_specs(llm_enabled=True) if s.name == "sec_sic").gate is None


def test_run_fill_pass_gated_off_is_a_clean_skip(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    fmp = next(s for s in fill_specs(llm_enabled=True) if s.name == "fmp")
    r = run_fill_pass(object(), fmp)  # conn is never touched when gated off
    assert r.skipped is True
    assert r.summary is None and r.error is None and r.in_scope == 0
    assert "FMP_API_KEY" in r.skip_line


class _FakeFillSource:
    def __init__(self, mapping):
        self._m = mapping

    def fetch(self, securities):
        return {
            s.composite_figi: self._m[s.composite_figi]
            for s in securities
            if s.composite_figi in self._m
        }


def _classif(figi, sector, source):
    return GicsClassification(
        composite_figi=figi,
        sector_name=sector,
        industry_group_name=None,
        industry_name=None,
        source=source,
    )


def test_run_fill_pass_scopes_plans_applies_and_renders(monkeypatch):
    monkeypatch.setattr(
        reg,
        "read_classifiable_identities",
        lambda conn, source: [SecurityIdentity("F1", ticker="X")],
    )
    monkeypatch.setattr(
        reg,
        "apply_classifications",
        lambda conn, plans: ClassificationSummary(rows_inserted=len(plans)),
    )
    spec = FillSpec(
        "b3",
        lambda: _FakeFillSource({"F1": _classif("F1", "Energy", "b3")}),
        render=lambda src, s, n: [f"ran {n} in-scope / {s.rows_inserted} inserted"],
    )
    r = run_fill_pass(object(), spec)
    assert r.in_scope == 1
    assert r.summary.rows_inserted == 1
    assert r.error is None and not r.skipped
    assert r.lines == ["ran 1 in-scope / 1 inserted"]


def test_run_fill_pass_empty_scope_reports_nothing_to_fill(monkeypatch):
    monkeypatch.setattr(reg, "read_classifiable_identities", lambda conn, source: [])
    spec = FillSpec("b3", lambda: _FakeFillSource({}), render=lambda src, s, n: ["x"])
    r = run_fill_pass(object(), spec)
    assert r.summary is None and r.in_scope == 0 and not r.skipped and r.lines == []


def test_run_fill_pass_isolates_a_source_error(monkeypatch):
    monkeypatch.setattr(
        reg,
        "read_classifiable_identities",
        lambda conn, source: [SecurityIdentity("F1", ticker="X")],
    )

    class _Boom:
        def fetch(self, securities):
            raise RuntimeError("kaboom")

    spec = FillSpec("b3", _Boom, render=lambda src, s, n: ["x"])
    r = run_fill_pass(object(), spec)
    assert r.summary is None
    assert r.error is not None and "kaboom" in r.error


def test_run_fill_pass_isolates_a_factory_error():
    # a source whose CONSTRUCTOR raises (e.g. LlmGicsSource loading a broken artifact)
    # must be caught per-pass, NOT escape and roll back the shared transaction.
    def _boom_factory():
        raise RuntimeError("bad artifact")

    spec = FillSpec("llm", _boom_factory, render=lambda src, s, n: ["x"])
    r = run_fill_pass(object(), spec)  # must not raise
    assert r.summary is None
    assert r.error is not None and "bad artifact" in r.error


def test_validate_fill_specs_rejects_bad_chains():
    good = fill_specs(llm_enabled=True)
    validate_fill_specs(good)  # the shipped chain is valid

    # unknown source name
    with pytest.raises(RuntimeError, match="not in SOURCE_PRECEDENCE"):
        validate_fill_specs([FillSpec("nope", object, render=lambda *a: [])])
    # financedatabase is the anchor, never a fill spec
    with pytest.raises(RuntimeError, match="primary anchor"):
        validate_fill_specs([FillSpec("financedatabase", object, render=lambda *a: [])])
    # out of precedence order (yahoo_profile rank 4 before sec_sic rank 2)
    out_of_order = [
        FillSpec("yahoo_profile", object, render=lambda *a: []),
        FillSpec("sec_sic", object, render=lambda *a: []),
    ]
    with pytest.raises(RuntimeError, match="out of precedence order"):
        validate_fill_specs(out_of_order)
    # incomplete (a known source missing)
    with pytest.raises(RuntimeError, match="unregistered"):
        validate_fill_specs([FillSpec("b3", object, render=lambda *a: [])])


def test_renderers_reproduce_source_attribution():
    # the per-source render closures read each source's side-channels — smoke-check
    # one (sec) end to end so a renamed attribute is caught.
    from sym.classification.sec_sic import SecSicGicsSource

    src = SecSicGicsSource(client=None)
    src.last_unmapped_sic = {"WAT": ("9995", "Non-Classifiable")}
    src.last_unmatched = ["NOCIK"]
    src.last_skipped_non_us = ["BMW"]
    src.last_errors = {"BAD": "HTTP 404"}
    summary = ClassificationSummary(rows_inserted=2, failed=0)
    lines = reg._render_sec(src, summary, 5)
    assert lines[0].startswith("sec_sic fill pass: 5 in-scope active;")
    assert "1 unmapped SIC" in lines[0] and "1 no-CIK/no-SIC" in lines[0]
    assert any("unmapped SIC: WAT" in ln for ln in lines)
    assert any("sec_sic lookup error: BAD" in ln for ln in lines)


@pytest.mark.parametrize("name", ["b3", "sec_sic", "fmp", "yahoo_profile", "llm"])
def test_every_fill_spec_has_a_renderer(name):
    spec = next(s for s in fill_specs(llm_enabled=True) if s.name == name)
    assert callable(spec.render)
    assert callable(spec.factory)


def test_run_classification_chain_runs_primary_then_fills(monkeypatch):
    # The shared orchestrator behind the CLI and the EOD step: primary first, then each
    # fill spec. Stub the gics functions so it's DB-free + deterministic.
    calls: list[str] = []
    monkeypatch.setattr(
        reg, "classify_universe", lambda conn, source: calls.append("primary") or _summary()
    )
    monkeypatch.setattr(reg, "read_classifiable_identities", lambda conn, source: [])
    primary, results = reg.run_classification_chain(object(), llm_enabled=False)
    assert calls == ["primary"]  # primary ran first
    # one PassResult per fill spec (llm excluded because llm_enabled=False gates it off)
    fill_names = [s.name for s in fill_specs(llm_enabled=False)]
    assert [r.name for r in results] == fill_names
    assert "llm" in fill_names  # the spec is present...
    llm_result = next(r for r in results if r.name == "llm")
    assert llm_result.skipped  # ...but gated off → skipped


def _summary():
    return ClassificationSummary(rows_inserted=0)
