"""Membership accuracy gate (Story U3.3, FR14 — SM-6-style for membership).

A periodic cross-check of a universe's *maintained* membership against an
**independent** second source (e.g. ETF holdings vs a Wikipedia-derived list — not
two derivatives of the same upstream). It alarms when the symmetric difference
exceeds a threshold, so a universe that is *wrong* (not merely stale) is caught.
A proxy reference (an ETF that tracks but is not the index) gets a wider tolerance
to avoid alert fatigue.

The comparison is on normalised identifier tokens (both pipelines build tokens via
``membership_diff``). Caveats the operator must know: ``maintained_tokens`` reads
the PROJECTION (resolved members only — an unresolved member is invisible to the
gate), and the comparison is only meaningful when both sides use the SAME token
scheme — a ``ticker:``-tokenised universe checked against an ``isin:``-tokenised
ETF reference diverges toward 1.0 regardless of truth (compare on resolved FIGIs
for cross-scheme checks; see the deferred-work ledger).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from sym.universe.membership_diff import figi_token
from sym.universe.providers.index_source import ARCHETYPE_ETF, get_index_source
from sym.universe.registry import (
    JOIN,
    MembershipChange,
    UniverseError,
    UnknownUniverseError,
)

DEFAULT_THRESHOLD = 0.05
# A proxy (ETF holdings) legitimately differs from the index it tracks; widen the
# alarm tolerance for a proxy reference so normal tracking drift isn't an alarm.
# Callers pass this as ``proxy_tolerance`` when the reference is a proxy — it is
# NOT applied automatically (the gate can't know the reference's nature).
DEFAULT_PROXY_TOLERANCE = 0.05


@dataclass
class AccuracyResult:
    maintained_count: int
    reference_count: int
    missing: set[str] = field(default_factory=set)  # in reference, not maintained
    extra: set[str] = field(default_factory=set)  # in maintained, not reference
    divergence: float = 0.0
    threshold: float = DEFAULT_THRESHOLD
    alarm: bool = False
    reference_source: str = ""


def evaluate(
    maintained: set[str],
    reference: set[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    proxy_tolerance: float = 0.0,
) -> AccuracyResult:
    """Compare maintained vs reference membership; alarm on excess divergence.

    Divergence is the Jaccard distance ``|A △ B| / |A ∪ B|``. The effective
    threshold is ``threshold + proxy_tolerance`` (use ``proxy_tolerance`` when the
    reference is an ETF proxy). An empty union is zero divergence (no alarm).
    """
    missing = reference - maintained
    extra = maintained - reference
    union = maintained | reference
    divergence = (len(missing) + len(extra)) / len(union) if union else 0.0
    effective = threshold + proxy_tolerance
    return AccuracyResult(
        maintained_count=len(maintained),
        reference_count=len(reference),
        missing=missing,
        extra=extra,
        divergence=divergence,
        threshold=effective,
        alarm=divergence > effective,
    )


def current_tokens_from_changes(changes: Iterable[MembershipChange]) -> set[str]:
    """The current member-token set implied by a snapshot source's join events.

    A snapshot source (ETF holdings, a current Wikipedia table) emits ``join`` for
    every current member; this collects them as the reference set.
    """
    return {c.raw_identifier for c in changes if c.change == JOIN}


def maintained_tokens(conn: psycopg.Connection, universe_id: str) -> set[str]:
    """The current maintained member tokens (open intervals) for a universe."""
    rows = conn.execute(
        """
        SELECT DISTINCT raw_identifier
          FROM universe_membership
         WHERE universe_id = %s AND valid_to IS NULL AND raw_identifier IS NOT NULL
        """,
        (universe_id,),
    ).fetchall()
    return {r[0] for r in rows}


def run_accuracy_check(
    conn: psycopg.Connection,
    universe_id: str,
    reference: set[str],
    *,
    reference_source: str,
    as_of_date: date,
    threshold: float = DEFAULT_THRESHOLD,
    proxy_tolerance: float = 0.0,
    sample: int = 20,
    maintained: set[str] | None = None,
) -> AccuracyResult:
    """Cross-check maintained membership vs an independent ``reference`` set.

    Writes a ``universe_accuracy_check`` audit row and returns the result. The
    detail JSON carries a bounded sample of the missing/extra members. Pass
    ``maintained`` explicitly for a comparison on something other than the raw
    projection tokens (the FIGI-level cross-scheme path).
    """
    conn.autocommit = True
    if maintained is None:
        maintained = maintained_tokens(conn, universe_id)
    result = evaluate(
        maintained, reference, threshold=threshold, proxy_tolerance=proxy_tolerance
    )
    result.reference_source = reference_source
    detail = {
        "missing_sample": sorted(result.missing)[:sample],
        "extra_sample": sorted(result.extra)[:sample],
    }
    conn.execute(
        """
        INSERT INTO universe_accuracy_check
            (universe_id, as_of_date, reference_source, maintained_count, reference_count,
             missing, extra, divergence, threshold, alarm, detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            universe_id, as_of_date, reference_source, result.maintained_count,
            result.reference_count, len(result.missing), len(result.extra),
            result.divergence, result.threshold, result.alarm, Jsonb(detail),
        ),
    )
    return result


# --- configured runner (Story U3.5, Task 4) ----------------------------------


def _schemes(tokens: Iterable[str]) -> set[str]:
    return {t.split(":", 1)[0] for t in tokens}


def open_member_figis(conn: psycopg.Connection, universe_id: str) -> set[str]:
    """Current maintained members as ``figi:`` tokens (for cross-scheme checks)."""
    rows = conn.execute(
        """
        SELECT DISTINCT composite_figi
          FROM universe_membership
         WHERE universe_id = %s AND valid_to IS NULL
        """,
        (universe_id,),
    ).fetchall()
    return {figi_token(r[0]) for r in rows}


def _reference_as_figi_tokens(conn: psycopg.Connection, reference: set[str]) -> set[str]:
    """Resolve reference tokens to ``figi:`` tokens via the local (no-network) resolver.

    A token the master can't resolve is KEPT verbatim — it can't corroborate the
    maintained set, so it must count toward divergence rather than silently vanish
    from the comparison.
    """
    from sym.universe.resolution import make_local_resolve_fn

    resolved = make_local_resolve_fn(conn)(sorted(reference))
    out: set[str] = set()
    for tok in reference:
        res = resolved.get(tok)
        if res is not None and res.composite_figi:
            out.add(figi_token(res.composite_figi))
        else:
            out.add(tok)
    return out


def fetch_reference_tokens(
    conn: psycopg.Connection, universe_id: str, *, as_of_date: date
) -> tuple[set[str], str, bool]:
    """Fetch the configured independent reference set for a universe.

    Returns ``(tokens, reference_archetype, is_proxy)``. The reference archetype
    comes from ``universe.config.accuracy_reference`` and MUST differ from the
    primary source — two reads of the same upstream corroborate nothing.
    """
    import sym.universe.providers  # noqa: F401  (ensure archetype sources self-register)

    row = conn.execute(
        "SELECT kind, config, source_pref FROM universe WHERE universe_id = %s",
        (universe_id,),
    ).fetchone()
    if row is None:
        raise UnknownUniverseError(f"unknown universe {universe_id!r}")
    _kind, config, source_pref = row
    config = dict(config or {})
    reference_archetype = config.get("accuracy_reference")
    if not reference_archetype:
        raise UniverseError(
            f"universe {universe_id!r} has no config.accuracy_reference — set it to a "
            "source archetype independent of the primary before running the gate"
        )
    pref = list(source_pref or config.get("source_pref") or ())
    if not pref:
        from sym.universe.providers.index_provider import DEFAULT_SOURCE_PREF

        pref = list(DEFAULT_SOURCE_PREF)
    if reference_archetype == pref[0]:
        raise UniverseError(
            f"accuracy_reference {reference_archetype!r} IS the primary source for "
            f"{universe_id!r} — the gate needs an independent reference"
        )
    index_key = config.get("index")
    if not index_key:
        raise UniverseError(
            f"universe {universe_id!r} has no config.index — the accuracy gate "
            "supports index universes only"
        )
    source_config = config.get(reference_archetype)
    if not isinstance(source_config, dict):
        source_config = {}
    source = get_index_source(reference_archetype, **source_config)
    changes = list(source.fetch(index_key, as_of_date, as_of_date))
    tokens = getattr(source, "last_snapshot_tokens", None) or current_tokens_from_changes(
        changes
    )
    if not tokens:
        raise UniverseError(
            f"reference source {reference_archetype!r} produced no members for "
            f"{universe_id!r} — refusing a vacuous accuracy check"
        )
    return set(tokens), reference_archetype, reference_archetype == ARCHETYPE_ETF


def run_configured_accuracy_check(
    conn: psycopg.Connection,
    universe_id: str,
    *,
    as_of_date: date,
    threshold: float = DEFAULT_THRESHOLD,
) -> AccuracyResult:
    """Run the accuracy gate against the universe's configured reference source.

    An ETF-proxy reference automatically gets ``DEFAULT_PROXY_TOLERANCE`` added to
    the threshold. When the reference emits a different token scheme than the
    maintained set (``isin:`` vs ``ticker:``), both sides are resolved to ``figi:``
    tokens first — a raw cross-scheme comparison diverges toward 1.0 regardless of
    truth.
    """
    reference, reference_archetype, is_proxy = fetch_reference_tokens(
        conn, universe_id, as_of_date=as_of_date
    )
    maintained: set[str] | None = maintained_tokens(conn, universe_id)
    if maintained and _schemes(maintained) != _schemes(reference):
        maintained = open_member_figis(conn, universe_id)
        reference = _reference_as_figi_tokens(conn, reference)
    return run_accuracy_check(
        conn,
        universe_id,
        reference,
        reference_source=reference_archetype,
        as_of_date=as_of_date,
        threshold=threshold,
        proxy_tolerance=DEFAULT_PROXY_TOLERANCE if is_proxy else 0.0,
        maintained=maintained,
    )


def accuracy_alarms(conn: psycopg.Connection) -> list[dict]:
    """The latest accuracy check per universe where it alarmed (for the digest)."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (universe_id)
               universe_id, checked_at, reference_source, divergence, threshold,
               missing, extra
          FROM universe_accuracy_check
         ORDER BY universe_id, checked_at DESC
        """
    ).fetchall()
    cols = ["universe_id", "checked_at", "reference_source", "divergence", "threshold",
            "missing", "extra"]
    return [dict(zip(cols, r, strict=True)) for r in rows if r[3] > r[4]]
