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
    apply_classifications,
    plan_classifications,
    read_classifiable_identities,
)
from sym.classification.llm import LlmGicsSource
from sym.classification.sec_sic import SecSicGicsSource
from sym.classification.yahoo_profile import YahooProfileGicsSource


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
    lines = [_header("sec_sic fill pass", n, s, extra)]
    lines += [
        f"  unmapped SIC: {t}: {sic} ({desc})"
        for t, (sic, desc) in sorted(src.last_unmapped_sic.items())
    ]
    lines += [f"  sec_sic lookup error: {t}: {m}" for t, m in sorted(src.last_errors.items())]
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
    lines = [_header("yahoo_profile fill pass", n, s, extra)]
    lines += [
        f"  unmapped Yahoo sector: {sym}: {sec!r}"
        for sym, sec in sorted(src.last_unmapped_sector.items())
    ]
    lines += [
        f"  yahoo_profile fetch error: {sym}: {m}" for sym, m in sorted(src.last_errors.items())
    ]
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


def fill_specs(*, llm_enabled: bool) -> list[FillSpec]:
    """The fill chain in precedence order (financedatabase, the primary, is the CLI anchor).

    ``llm_enabled`` gates the opt-in LLM pass (``sym classify --llm``); the FMP pass is
    gated on ``$FMP_API_KEY`` (keyed source — dormant without a key).
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
        FillSpec("llm", LlmGicsSource, _render_llm, gate=lambda: llm_enabled, skip_line=""),
    ]


def run_fill_pass(conn: psycopg.Connection, spec: FillSpec) -> PassResult:
    """Run one fill pass uniformly: gate → classifiable scope → plan → apply → render.

    Mirrors the per-pass discipline of the old hand-written blocks: a gated-off pass is a
    clean skip; a fill failure is caught and attributed (it must never roll back or mask
    the earlier passes — the whole chain shares one transaction committed by the caller).
    """
    if spec.gate is not None and not spec.gate():
        return PassResult(spec.name, None, None, 0, True, skip_line=spec.skip_line)
    source = spec.factory()
    try:
        ids = read_classifiable_identities(conn, source=spec.name)
        if not ids:
            return PassResult(spec.name, None, None, 0, False)
        summary = apply_classifications(conn, plan_classifications(ids, source))
        return PassResult(
            spec.name, summary, None, len(ids), False, spec.render(source, summary, len(ids))
        )
    except Exception as exc:  # noqa: BLE001 — a fill failure must not mask/destroy earlier passes
        return PassResult(spec.name, None, f"{type(exc).__name__}: {exc}", 0, False)


# Cross-check at import: every spec's name is a known fill source ranked strictly below
# financedatabase, and the specs are in ascending precedence order. A mis-ordered or
# unknown entry is a programming error, surfaced loudly rather than silently mis-running.
_spec_names = [s.name for s in fill_specs(llm_enabled=True)]
assert all(n in SOURCE_PRECEDENCE for n in _spec_names), "fill spec name not in SOURCE_PRECEDENCE"
assert "financedatabase" not in _spec_names, "financedatabase is the primary, not a fill spec"
_ranks = [SOURCE_PRECEDENCE[n] for n in _spec_names]
assert _ranks == sorted(_ranks) and len(set(_ranks)) == len(_ranks), (
    "fill specs out of precedence order"
)
assert set(_spec_names) | {"financedatabase"} == set(SOURCE_PRECEDENCE), "a source is unregistered"
