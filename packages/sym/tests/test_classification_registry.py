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
from sym.classification.registry import FillSpec, fill_specs, run_fill_pass


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
