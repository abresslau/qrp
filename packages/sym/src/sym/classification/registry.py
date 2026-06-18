"""Registry of the GICS fill sources — the precedence-ordered chain in one place.

The primary source (financedatabase, all-actives, re-asserts itself) stays the explicit
anchor in the CLI; this registry owns the FILL sources (b3 → sec_sic → fmp →
yahoo_profile → llm), which were five near-identical hand-written passes in
``_cmd_classify``. Each is a :class:`FillSpec` — name (its ``source`` tag + the
:data:`~sym.classification.gics.SOURCE_PRECEDENCE` key), a factory, an optional gate
(keyed/opt-in), and a renderer for its bespoke attribution. :func:`run_fill_pass` runs one
uniformly: gate → ``read_classifiable_identities(source)`` → plan → apply → render. Adding
the next source is one entry here, not another copy of the pass+report boilerplate.

This is the AC1 "pluggable, precedence-ordered, no concrete-class import in the caller"
generalization: the CLI imports this registry, not the five source classes.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg

from sym.classification.b3 import B3GicsSource
from sym.classification.fmp_profile import FmpProfileGicsSource
from sym.classification.gics import (
    SOURCE_PRECEDENCE,
    ClassificationSummary,
    FinanceDatabaseGicsSource,
    apply_classifications,
    classify_universe,
    plan_classifications,
    read_active_identities,
    read_classifiable_identities,
)
from sym.classification.google_gemini import GoogleGeminiGicsSource, google_enabled
from sym.classification.llm import LlmGicsSource
from sym.classification.opinions import OpinionSummary, apply_source_opinions
from sym.classification.perplexity import PerplexityGicsSource, perplexity_enabled
from sym.classification.sec_sic import SecSicGicsSource
from sym.classification.wikidata import WikidataGicsSource
from sym.classification.yahoo_profile import MAX_CONSECUTIVE_ERRORS, YahooProfileGicsSource


@dataclass(frozen=True)
class FillSpec:
    """One fill source in the chain.

    ``gate=None`` always runs; otherwise the pass runs only when ``gate()`` is truthy
    (keyed sources check the env; opt-in sources check a flag). ``skip_line`` is printed
    when gated off (empty → silent). ``render(source, summary, in_scope)`` returns the
    source's report lines (header + its bespoke attribution detail).
    """

    name: str
    factory: Callable[[], object]
    render: Callable[[object, ClassificationSummary, int], list[str]]
    gate: Callable[[], bool] | None = None
    skip_line: str = ""


@dataclass
class PassResult:
    """Outcome of one fill pass, for the CLI to print after the run commits."""

    name: str
    summary: ClassificationSummary | None
    error: str | None
    in_scope: int
    skipped: bool
    lines: list[str] = field(default_factory=list)
    skip_line: str = ""


def _header(label: str, n: int, s: ClassificationSummary, extra: str) -> str:
    head = (
        f"{label}: {n} in-scope active; {s.rows_inserted} inserted, {s.rows_updated} upgraded, "
        f"{s.unchanged} unchanged, {s.rows_closed} superseded, {s.failed} failed"
    )
    return f"{head}; {extra}" if extra else head


def _render_b3(src, s: ClassificationSummary, n: int) -> list[str]:
    extra = (
        f"{len(set(src.last_unmapped.values()))} unmapped segments "
        f"({len(src.last_unmapped)} tickers), {len(src.last_conflicts)} view conflicts, "
        f"{len(src.last_unmatched)} in-scope unfilled"
    )
    lines = [_header("b3 fill pass", n, s, extra)]
    lines += [
        f"  unmapped B3 segment: {t}: {seg!r}" for t, seg in sorted(src.last_unmapped.items())
    ]
    lines += [
        f"  B3 view conflict (skipped): {t}: {a!r} vs {b!r}"
        for t, (a, b) in sorted(src.last_conflicts.items())
    ]
    if src.last_unmatched:
        lines.append(f"  no B3 classification for: {', '.join(src.last_unmatched)}")
    lines += [f"  b3 write failed: {fail}" for fail in s.failures]
    return lines


def _render_sec(src, s: ClassificationSummary, n: int) -> list[str]:
    extra = (
        f"{len(src.last_unmapped_sic)} unmapped SIC, {len(src.last_unmatched)} no-CIK/no-SIC, "
        f"{len(src.last_skipped_non_us)} non-US skipped, {len(src.last_errors)} lookup error(s)"
    )
    ambiguous = getattr(src, "last_ambiguous_ticker", {})
    if ambiguous:
        extra += f", {len(ambiguous)} ambiguous ticker(s)"
    lines = [_header("sec_sic fill pass", n, s, extra)]
    lines += [
        f"  unmapped SIC: {t}: {sic} ({desc})"
        for t, (sic, desc) in sorted(src.last_unmapped_sic.items())
    ]
    lines += [f"  sec_sic lookup error: {t}: {m}" for t, m in sorted(src.last_errors.items())]
    lines += [
        f"  sec_sic ambiguous ticker {t}: CIKs {', '.join(ciks)} (resolved to active filer)"
        for t, ciks in sorted(ambiguous.items())
    ]
    lines += [f"  sec_sic write failed: {fail}" for fail in s.failures]
    return lines


def _render_fmp(src, s: ClassificationSummary, n: int) -> list[str]:
    extra = (
        f"{len(src.last_unmapped_sector)} unmapped sector, {len(src.last_unmatched)} no-profile, "
        f"{len(src.last_skipped_fund)} funds skipped, {len(src.last_unmapped_mic)} unmappable MIC, "
        f"{len(src.last_errors)} fetch error(s)"
    )
    lines = [_header("fmp fill pass (keyed)", n, s, extra)]
    lines += [
        f"  unmapped FMP sector: {sym}: {sec!r}"
        for sym, sec in sorted(src.last_unmapped_sector.items())
    ]
    lines += [f"  fmp fetch error: {sym}: {m}" for sym, m in sorted(src.last_errors.items())]
    lines += [f"  fmp write failed: {fail}" for fail in s.failures]
    return lines


def _render_yahoo(src, s: ClassificationSummary, n: int) -> list[str]:
    extra = (
        f"{len(src.last_unmapped_sector)} unmapped sector, {len(src.last_unmatched)} no-profile, "
        f"{len(src.last_unmapped_mic)} unmappable MIC, {len(src.last_errors)} fetch error(s)"
    )
    short_circuited = getattr(src, "last_short_circuited", [])
    if short_circuited:
        extra += f", {len(short_circuited)} not attempted (circuit-breaker)"
    lines = [_header("yahoo_profile fill pass", n, s, extra)]
    lines += [
        f"  unmapped Yahoo sector: {sym}: {sec!r}"
        for sym, sec in sorted(src.last_unmapped_sector.items())
    ]
    lines += [
        f"  yahoo_profile fetch error: {sym}: {m}" for sym, m in sorted(src.last_errors.items())
    ]
    if short_circuited:
        lines.append(
            f"  yahoo_profile circuit-breaker tripped after "
            f"{MAX_CONSECUTIVE_ERRORS} consecutive errors; "
            f"{len(short_circuited)} name(s) not attempted (retried next run)"
        )
    lines += [f"  yahoo_profile write failed: {fail}" for fail in s.failures]
    return lines


def _render_llm(src, s: ClassificationSummary, n: int) -> list[str]:
    extra = (
        f"{len(src.last_unmatched)} unmatched (funds/uncovered), "
        f"{len(src.last_mic_mismatch)} MIC mismatch"
    )
    lines = [_header("llm fill pass (opt-in, low-trust)", n, s, extra)]
    lines += [f"  llm write failed: {fail}" for fail in s.failures]
    return lines


def _render_wikidata(src, s: ClassificationSummary, n: int) -> list[str]:
    sc = getattr(src, "last_short_circuited", [])
    extra = (
        f"{len(src.last_unmatched)} no-entity/no-industry, "
        f"{len(src.last_unmapped)} unmapped industries, {len(src.last_errors)} batch error(s)"
    )
    if sc:
        extra += f", {len(sc)} not queried (circuit-breaker)"
    lines = [_header("wikidata fill pass", n, s, extra)]
    lines += [f"  wikidata batch error: {b}: {m}" for b, m in sorted(src.last_errors.items())]
    lines += [f"  wikidata write failed: {fail}" for fail in s.failures]
    return lines


def _render_llm_http(label: str):
    """Renderer factory for the keyed LLM-http sources (perplexity/google) — same shape."""

    def _render(src, s: ClassificationSummary, n: int) -> list[str]:
        sc = getattr(src, "last_short_circuited", [])
        extra = (
            f"{len(src.last_unmapped)} off-taxonomy, {len(src.last_unmatched)} no-answer, "
            f"{len(src.last_errors)} fetch error(s)"
        )
        if sc:
            extra += f", {len(sc)} not attempted (circuit-breaker)"
        lines = [_header(f"{label} fill pass (keyed, low-trust)", n, s, extra)]
        lines += [f"  {label} fetch error: {t}: {m}" for t, m in sorted(src.last_errors.items())]
        lines += [f"  {label} write failed: {fail}" for fail in s.failures]
        return lines

    return _render


def fill_specs(*, llm_enabled: bool) -> list[FillSpec]:
    """The fill chain in precedence order (financedatabase, the primary, is the CLI anchor).

    ``llm_enabled`` gates the opt-in LLM pass; FMP/perplexity/google are gated on their API
    keys (keyed sources — dormant without a key). wikidata is keyless and always runs.
    """
    return [
        FillSpec("b3", B3GicsSource, _render_b3),
        FillSpec("sec_sic", SecSicGicsSource, _render_sec),
        FillSpec(
            "fmp",
            FmpProfileGicsSource,
            _render_fmp,
            gate=lambda: bool(os.environ.get("FMP_API_KEY")),
            skip_line="fmp fill pass: skipped — no FMP_API_KEY (keyed source, dormant until set)",
        ),
        FillSpec("yahoo_profile", YahooProfileGicsSource, _render_yahoo),
        FillSpec("wikidata", WikidataGicsSource, _render_wikidata),
        FillSpec("llm", LlmGicsSource, _render_llm, gate=lambda: llm_enabled, skip_line=""),
        FillSpec(
            "perplexity",
            PerplexityGicsSource,
            _render_llm_http("perplexity"),
            gate=perplexity_enabled,
            skip_line="perplexity fill pass: skipped — no PERPLEXITY_API_KEY (keyed, dormant)",
        ),
        FillSpec(
            "google",
            GoogleGeminiGicsSource,
            _render_llm_http("google"),
            gate=google_enabled,
            skip_line="google fill pass: skipped — no GOOGLE_API_KEY/GEMINI_API_KEY (dormant)",
        ),
    ]


def run_fill_pass(conn: psycopg.Connection, spec: FillSpec) -> PassResult:
    """Run one fill pass uniformly: gate → classifiable scope → plan → apply → render.

    Mirrors the per-pass discipline of the old hand-written blocks: a gated-off pass is a
    clean skip; a fill failure is caught and attributed (it must never roll back or mask
    the earlier passes — the whole chain shares one transaction committed by the caller).
    """
    if spec.gate is not None and not spec.gate():
        return PassResult(spec.name, None, None, 0, True, skip_line=spec.skip_line)
    try:
        # Construct INSIDE the try: a source ctor that does I/O (LlmGicsSource loads its
        # artifact) must fail as a per-pass error, never escape to roll back the shared
        # transaction (the primary + earlier fills already wrote into this connection).
        source = spec.factory()
        ids = read_classifiable_identities(conn, source=spec.name)
        if not ids:
            return PassResult(spec.name, None, None, 0, False)
        summary = apply_classifications(conn, plan_classifications(ids, source))
        return PassResult(
            spec.name, summary, None, len(ids), False, spec.render(source, summary, len(ids))
        )
    except Exception as exc:  # noqa: BLE001 — a fill failure must not mask/destroy earlier passes
        return PassResult(spec.name, None, f"{type(exc).__name__}: {exc}", 0, False)


def run_classification_chain(
    conn: psycopg.Connection, *, llm_enabled: bool = False
) -> tuple[ClassificationSummary, list[PassResult]]:
    """Run the whole chain over one connection and return ``(primary_summary, results)``.

    The financedatabase primary (all-actives, re-asserts itself) runs first, then each fill
    spec in precedence order. This is the SINGLE orchestrator behind both the ``sym classify``
    CLI and the EOD ``classify`` maintenance step, so an unattended daily run and a manual run
    are identical. ``llm_enabled`` defaults False — the opt-in, low-trust LLM pass never runs
    unattended.
    """
    primary = classify_universe(conn, FinanceDatabaseGicsSource())
    results = [run_fill_pass(conn, spec) for spec in fill_specs(llm_enabled=llm_enabled)]
    return primary, results


def validate_fill_specs(specs: list[FillSpec]) -> None:
    """Fail-fast if the fill chain isn't a complete, strictly-ascending-precedence cover of
    :data:`SOURCE_PRECEDENCE` minus the financedatabase primary.

    A mis-ordered or unregistered source is a programming error — raised loudly (an explicit
    ``raise``, NOT ``assert``, so it survives ``python -O``) rather than silently mis-running
    the chain. Called at import below, and exercised directly by the registry tests.
    """
    names = [s.name for s in specs]
    unknown = [n for n in names if n not in SOURCE_PRECEDENCE]
    if unknown:
        raise RuntimeError(f"fill spec name(s) not in SOURCE_PRECEDENCE: {unknown}")
    if "financedatabase" in names:
        raise RuntimeError("financedatabase is the primary anchor, not a fill spec")
    ranks = [SOURCE_PRECEDENCE[n] for n in names]
    if ranks != sorted(ranks) or len(set(ranks)) != len(ranks):
        raise RuntimeError(f"fill specs out of precedence order: {names}")
    if set(names) | {"financedatabase"} != set(SOURCE_PRECEDENCE):
        raise RuntimeError(f"a known source is unregistered in the fill chain: {names}")


validate_fill_specs(fill_specs(llm_enabled=True))


# ---------------------------------------------------------------------------
# Multi-source opinion matrix — every source's OWN opinion over ALL companies
# ---------------------------------------------------------------------------
# Orthogonal to the fill chain above: the fill chain resolves ONE classification into
# gics_scd (fill-only, precedence). This runs EVERY source over EVERY active identity and
# records each opinion in gics_source_opinion (via apply_source_opinions). gics_scd is
# untouched. Explicit/on-demand (`sym classify-opinions`), NOT the nightly EOD — running
# yahoo over the whole universe is slow and the LLM sources cost per call.


@dataclass
class OpinionPass:
    """Outcome of one source's opinion pass, for the CLI to print."""

    name: str
    summary: OpinionSummary | None = None
    skipped: bool = False
    skip_line: str = ""
    error: str | None = None


def _opinion_specs(*, llm_enabled: bool) -> list[tuple]:
    """(name, factory, gate, skip_line) for ALL sources incl. the financedatabase primary.

    The opinion matrix is precedence-INDEPENDENT — it stores every source's opinion. Keyed/
    opt-in sources are gated (FMP/perplexity/google on their key; llm on the flag) and skip
    cleanly when unavailable, exactly as in the resolved chain.
    """
    return [
        ("financedatabase", FinanceDatabaseGicsSource, None, ""),
        ("b3", B3GicsSource, None, ""),
        ("sec_sic", SecSicGicsSource, None, ""),
        ("yahoo_profile", YahooProfileGicsSource, None, ""),
        ("wikidata", WikidataGicsSource, None, ""),
        (
            "fmp",
            FmpProfileGicsSource,
            lambda: bool(os.environ.get("FMP_API_KEY")),
            "fmp opinion: skipped — no FMP_API_KEY",
        ),
        ("llm", LlmGicsSource, (lambda: llm_enabled), "llm opinion: skipped — not enabled"),
        ("perplexity", PerplexityGicsSource, perplexity_enabled,
         "perplexity opinion: skipped — no PERPLEXITY_API_KEY"),
        ("google", GoogleGeminiGicsSource, google_enabled,
         "google opinion: skipped — no GOOGLE_API_KEY/GEMINI_API_KEY"),
    ]


def run_opinion_matrix(conn: psycopg.Connection, *, llm_enabled: bool = False) -> list[OpinionPass]:
    """Run every (gated) source over ALL active identities → gics_source_opinion.

    Each source's opinion is written independently (apply_source_opinions, SCD per
    (figi, source)). A source that errors is isolated (recorded, the rest continue) — it can
    never corrupt gics_scd (this writes only the opinion store). Returns a pass per source.
    """
    ids = read_active_identities(conn)
    results: list[OpinionPass] = []
    for name, factory, gate, skip_line in _opinion_specs(llm_enabled=llm_enabled):
        if gate is not None and not gate():
            results.append(OpinionPass(name, skipped=True, skip_line=skip_line))
            continue
        try:
            source = factory()
            found = source.fetch(ids)
            summary = apply_source_opinions(conn, list(found.values()))
            results.append(OpinionPass(name, summary=summary))
        except Exception as exc:  # noqa: BLE001 — one source failing must not abort the matrix
            results.append(OpinionPass(name, error=f"{type(exc).__name__}: {exc}"))
    return results
