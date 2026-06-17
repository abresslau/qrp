"""LLM-assisted GICS gap-fill (multi-source, AC #4) — last-resort, low-trust, reviewable.

The residual after the deterministic sources (financedatabase, b3, sec_sic,
yahoo_profile) is a short tail of mostly funds/ETFs — which CORRECTLY have no GICS
sector — plus a handful of operating companies the data sources missed (recent
renames/spinoffs). This source carries human-in-the-loop classifications produced
by an LLM (Claude) and persisted as a REVIEWABLE artifact
(:data:`LLM_CLASSIFICATIONS_PATH`, ``llm_classifications.json``): each entry pairs
a ticker with one of the 11 GICS sectors and a rationale, written ``source='llm'``.

Lowest trust, LAST in precedence: fed only the still-unclassified identities, so
fill-only by construction (it can never override an authoritative source). Opt-in
via ``sym classify --llm`` — never part of the default run. The JSON artifact is
the review surface; a wrong call is a one-line edit + reclassify. Funds are
DELIBERATELY ABSENT — a fund has no sector, so this source never invents one.

Sector-only (industry levels NULL, matching b3/sec_sic/yahoo_profile). A sector
outside the 11-name GICS taxonomy is REFUSED at load (a typo never silently
writes a bad row). No network, no LLM API call at runtime — the LLM judgement is
captured in the artifact ahead of time.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sym.classification.gics import GicsClassification, SecurityIdentity

# The 11 GICS sectors — the only legal `sector` values in the artifact (kept
# identical to the labels the other sources emit so the heatmap/validate group).
GICS_SECTORS = frozenset(
    {
        "Energy",
        "Materials",
        "Industrials",
        "Consumer Discretionary",
        "Consumer Staples",
        "Health Care",
        "Financials",
        "Information Technology",
        "Communication Services",
        "Utilities",
        "Real Estate",
    }
)

LLM_CLASSIFICATIONS_PATH = Path(__file__).with_name("llm_classifications.json")


class LlmClassificationError(RuntimeError):
    """The LLM artifact is unreadable, malformed, or carries an invalid sector."""


@dataclass(frozen=True)
class LlmRecord:
    """One reviewed LLM classification (an artifact row)."""

    ticker: str
    sector: str
    mic: str | None = None
    name: str | None = None
    rationale: str | None = None


def load_llm_classifications(path: Path | None = None) -> list[LlmRecord]:
    """Read + validate the LLM artifact into records.

    Refuses an unknown sector at load time (a typo must never reach the writer),
    and requires a ticker + sector on every row. A missing file is an explicit
    error — the caller decides whether running ``--llm`` without an artifact is
    acceptable.
    """
    path = path or LLM_CLASSIFICATIONS_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LlmClassificationError(f"LLM artifact not found: {path}") from exc
    except (OSError, ValueError) as exc:
        raise LlmClassificationError(f"LLM artifact unreadable ({path}): {exc}") from exc
    rows = payload.get("classifications") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise LlmClassificationError("LLM artifact has no 'classifications' list")
    records: list[LlmRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            raise LlmClassificationError(f"LLM artifact row is not an object: {row!r}")
        ticker = row.get("ticker")
        sector = row.get("sector")
        if not ticker or not sector:
            raise LlmClassificationError(f"LLM artifact row missing ticker/sector: {row!r}")
        if sector not in GICS_SECTORS:
            raise LlmClassificationError(
                f"LLM artifact row for {ticker!r} has non-GICS sector {sector!r}"
            )
        records.append(
            LlmRecord(
                ticker=str(ticker).upper(),
                sector=str(sector),
                mic=row.get("mic"),
                name=row.get("name"),
                rationale=row.get("rationale"),
            )
        )
    return records


class LlmGicsSource:
    """GICS *sector* classifications from the reviewed LLM artifact.

    Implements the :class:`sym.classification.gics.GicsSource` protocol. Matches an
    identity by ticker; when both the record and the identity carry a MIC they must
    agree (a foreign listing sharing a ticker never inherits a US record's sector —
    same posture as b3/sec_sic). Every classification is SECTOR-ONLY with
    ``source='llm'``.

    Attribution side-channels (reset per ``fetch``):

    * ``last_unmatched`` (tickers): in-scope identities no artifact row covered —
      expected for the funds/ETFs deliberately left out;
    * ``last_mic_mismatch`` (tickers): a ticker matched a record but the MICs
      disagreed (the record was NOT applied — never cross-listed).
    """

    def __init__(self, records: Sequence[LlmRecord] | None = None) -> None:
        self._records = list(records) if records is not None else load_llm_classifications()
        self._by_ticker: dict[str, LlmRecord] = {}
        for rec in self._records:
            if rec.ticker in self._by_ticker:
                # A duplicate ticker (e.g. a dual-listing) would silently lose one
                # row under first-wins — refuse loudly so the artifact is fixed
                # (key by (ticker, mic) if a real dual-listing ever needs covering).
                raise LlmClassificationError(
                    f"duplicate ticker {rec.ticker!r} in LLM artifact — "
                    "each ticker must appear at most once"
                )
            self._by_ticker[rec.ticker] = rec
        self.last_unmatched: list[str] = []
        self.last_mic_mismatch: list[str] = []

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        self.last_unmatched = []
        self.last_mic_mismatch = []
        found: dict[str, GicsClassification] = {}
        for security in securities:
            if not security.ticker:
                continue
            ticker = security.ticker.upper()
            rec = self._by_ticker.get(ticker)
            if rec is None:
                self.last_unmatched.append(ticker)
                continue
            if rec.mic is not None and security.mic is not None and rec.mic != security.mic:
                # ticker matched but the listing venue disagrees — do not apply.
                self.last_mic_mismatch.append(ticker)
                continue
            found[security.composite_figi] = GicsClassification(
                composite_figi=security.composite_figi,
                sector_name=rec.sector,
                industry_group_name=None,
                industry_name=None,
                source="llm",
            )
        return found
