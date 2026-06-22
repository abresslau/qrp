"""Operator-asserted GICS classifications — the authoritative manual fill source.

A curated, reviewable artifact (:data:`MANUAL_CLASSIFICATIONS_PATH`,
``manual_classifications.json``) of GICS sectors the operator asserts as VERIFIABLE
FACTS — never guesses. The motivating case: FTSE-100 closed-end investment trusts
(Scottish Mortgage / Polar Capital Technology / Alliance Witan) which FTSE/ICB and
GICS both classify as **Financials**, but which no automated source can reach in this
environment (``yahoo_profile`` gets HTTP 404 on ``*.L`` in the sim env; Wikidata has
no entity match; ``sec_sic`` is US-only). The fact is authoritative; only the live
*lookup* is blocked — so it is recorded here rather than fabricated or left to a
low-trust guess.

Distinct from :mod:`sym.classification.llm` (low-trust LLM guesses, LAST in
precedence, opt-in): the manual source is **high-trust** (operator-verified facts),
ranks **second only to the ``financedatabase`` primary** among fills, and is
**always on** (no gate) — an operator fact must not be silently overridden by an
automated source's later guess. Like every fill source it is fed only the
still-classifiable identities, so it is fill-only by construction and can never
override the curated primary.

Matches by ``composite_figi`` (the stable identity key — an operator names the exact
security, not a fragile ticker). Sector-only (industry levels NULL, matching
b3/sec_sic/yahoo_profile); a sector outside the 11-name GICS taxonomy is REFUSED at
load (a typo never silently writes a bad row). No network — the judgement is captured
in the artifact ahead of time.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sym.classification.gics import GicsClassification, SecurityIdentity
from sym.classification.llm import GICS_SECTORS

MANUAL_CLASSIFICATIONS_PATH = Path(__file__).with_name("manual_classifications.json")


class ManualClassificationError(RuntimeError):
    """The manual artifact is unreadable, malformed, or carries an invalid sector."""


@dataclass(frozen=True)
class ManualRecord:
    """One operator-asserted classification (an artifact row)."""

    composite_figi: str
    sector: str
    ticker: str | None = None
    name: str | None = None
    rationale: str | None = None


def load_manual_classifications(path: Path | None = None) -> list[ManualRecord]:
    """Read + validate the manual artifact into records.

    Refuses an unknown sector at load time (a typo must never reach the writer) and
    requires a ``composite_figi`` + ``sector`` on every row. A missing file is an
    explicit error — the source is always on, so a deploy without the artifact must
    fail loudly rather than silently classify nothing.
    """
    path = path or MANUAL_CLASSIFICATIONS_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManualClassificationError(f"manual artifact not found: {path}") from exc
    except (OSError, ValueError) as exc:
        raise ManualClassificationError(f"manual artifact unreadable ({path}): {exc}") from exc
    rows = payload.get("classifications") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ManualClassificationError("manual artifact has no 'classifications' list")
    records: list[ManualRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ManualClassificationError(f"manual artifact row is not an object: {row!r}")
        figi = row.get("composite_figi")
        sector = row.get("sector")
        if not figi or not sector:
            raise ManualClassificationError(
                f"manual artifact row missing composite_figi/sector: {row!r}"
            )
        if sector not in GICS_SECTORS:
            raise ManualClassificationError(
                f"manual artifact row for {figi!r} has non-GICS sector {sector!r}"
            )
        records.append(
            ManualRecord(
                composite_figi=str(figi),
                sector=str(sector),
                ticker=row.get("ticker"),
                name=row.get("name"),
                rationale=row.get("rationale"),
            )
        )
    return records


class ManualGicsSource:
    """GICS *sector* classifications from the operator-asserted manual artifact.

    Implements the :class:`sym.classification.gics.GicsSource` protocol. Matches an
    identity by ``composite_figi`` (the stable key — precise, never a ticker
    collision). Every classification is SECTOR-ONLY with ``source='manual'``.

    Attribution side-channels (reset per ``fetch``):

    * ``last_unmatched`` (figis): in-scope identities no artifact row covered — the
      overwhelming majority (the artifact is a tiny curated set), reported for parity
      with the other sources' attribution, not as a problem;
    * ``last_unused`` (figis): artifact rows whose figi was NOT in the in-scope set
      this run (already classified by a higher source, or not an active identity) —
      surfaced so a stale/obsolete manual row is visible rather than silently inert.
    """

    def __init__(self, records: Sequence[ManualRecord] | None = None) -> None:
        self._records = list(records) if records is not None else load_manual_classifications()
        self._by_figi: dict[str, ManualRecord] = {}
        for rec in self._records:
            if rec.composite_figi in self._by_figi:
                raise ManualClassificationError(
                    f"duplicate composite_figi {rec.composite_figi!r} in manual artifact — "
                    "each security must appear at most once"
                )
            self._by_figi[rec.composite_figi] = rec
        self.last_unmatched: list[str] = []
        self.last_unused: list[str] = []

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        self.last_unmatched = []
        self.last_unused = []
        found: dict[str, GicsClassification] = {}
        seen: set[str] = set()
        for security in securities:
            figi = security.composite_figi
            seen.add(figi)
            rec = self._by_figi.get(figi)
            if rec is None:
                self.last_unmatched.append(figi)
                continue
            found[figi] = GicsClassification(
                composite_figi=figi,
                sector_name=rec.sector,
                industry_group_name=None,
                industry_name=None,
                source="manual",
            )
        self.last_unused = [figi for figi in self._by_figi if figi not in seen]
        return found
