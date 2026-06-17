"""GICS classification loading into the SCD table (Story 1.8, FR-4, AR-11).

The free ``financedatabase`` source supplies only the top three GICS *labels*
(sector, industry-group, industry); sub-industry and the numeric GICS *codes*
are not available from it, so those columns exist in ``gics_scd`` for a future
coded/point-in-time feed but stay NULL today (see ``migrations/deploy/gics_scd.sql``).

The external dependency is isolated behind the :class:`GicsSource` protocol —
mirroring :class:`sym.identity.figi.OpenFigiClient` — so the loading logic is
testable without the financedatabase frame, and writes go through one
``conn.transaction()`` per security so a single bad row never rolls back the run.
Data is current-only, written in slowly-changing-dimension shape: a re-run with an
unchanged classification is a no-op; a changed one closes the prior row
(``valid_to = as_of_date``) before inserting the new one (never a hard delete).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import psycopg

# financedatabase column -> GICS level. Only the top three labels are supplied.
_FD_SECTOR = "sector"
_FD_INDUSTRY_GROUP = "industry_group"
_FD_INDUSTRY = "industry"

DEFAULT_COVERAGE_THRESHOLD = 0.90  # AC #2 — never silently widened.

# Source precedence for the multi-source fill chain (lower number = HIGHER precedence /
# more authoritative). A source may (re)classify a security that is unclassified OR
# currently held by a STRICTLY lower-precedence source, and must never modify a row from
# an equal-or-higher source. Drives `read_classifiable_identities` (the per-source scope)
# and the supersede/upgrade decision in `apply_classifications`. A source NOT in this map
# (a legacy/manual `source` value) is treated as out-of-band: it is never auto-superseded
# (its row is preserved) and never supersedes another — so unknown rows are never clobbered.
SOURCE_PRECEDENCE: dict[str, int] = {
    "financedatabase": 0,
    "b3": 1,
    "sec_sic": 2,
    "yahoo_profile": 3,
    "llm": 4,
}


def outranks(new_source: str | None, current_source: str | None) -> bool:
    """True if ``new_source`` is STRICTLY higher precedence than ``current_source``.

    Either side being unknown (outside :data:`SOURCE_PRECEDENCE`) returns False — an
    unknown current row is preserved (never auto-superseded) and an unknown new source
    never supersedes — so the chain only ever upgrades between sources it understands.
    """
    new_rank = SOURCE_PRECEDENCE.get(new_source) if new_source is not None else None
    cur_rank = SOURCE_PRECEDENCE.get(current_source) if current_source is not None else None
    if new_rank is None or cur_rank is None:
        return False
    return new_rank < cur_rank


@dataclass(frozen=True)
class GicsClassification:
    """One security's GICS classification.

    Sub-industry and all numeric codes default to NULL: the financedatabase
    source does not provide them. The SCD shape still carries the columns so a
    licensed coded feed can populate them later without a migration.
    """

    composite_figi: str
    sector_name: str | None
    industry_group_name: str | None
    industry_name: str | None
    sub_industry_name: str | None = None
    sector_code: str | None = None
    industry_group_code: str | None = None
    industry_code: str | None = None
    sub_industry_code: str | None = None
    source: str = "financedatabase"

    @property
    def is_classified(self) -> bool:
        """A row counts toward coverage once the source supplies at least a sector."""
        return self.sector_name is not None

    def level_names(self) -> tuple[str | None, str | None, str | None, str | None]:
        """The four level *names*, in level order — the SCD comparison key."""
        return (
            self.sector_name,
            self.industry_group_name,
            self.industry_name,
            self.sub_industry_name,
        )


def _clean_str(value: Any) -> str | None:
    """Normalise a frame cell to a non-empty string or None (NaN/float -> None)."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def classification_from_row(composite_figi: str, row: Mapping[str, Any]) -> GicsClassification:
    """Map a financedatabase row to a :class:`GicsClassification`.

    Only the three label columns are read; everything else stays NULL. NaN/empty
    cells become None so an absent sector is correctly treated as unclassified.
    """
    return GicsClassification(
        composite_figi=composite_figi,
        sector_name=_clean_str(row.get(_FD_SECTOR)),
        industry_group_name=_clean_str(row.get(_FD_INDUSTRY_GROUP)),
        industry_name=_clean_str(row.get(_FD_INDUSTRY)),
    )


@dataclass(frozen=True)
class SecurityIdentity:
    """The identifiers a GICS source may match a security on.

    ``composite_figi`` is our key (and what the result is attributed to);
    ``isin`` is the fallback when the source lacks the CompositeFIGI. ``mic`` is the
    listing exchange — exchange-scoped sources (B3, Story QH.1) need it because their
    tickers are exchange-local strings: matching a foreign security by bare ticker
    would attribute another exchange's classification to it.
    """

    composite_figi: str
    isin: str | None = None
    ticker: str | None = None
    mic: str | None = None


class GicsSource(Protocol):
    """Returns a classification per security the source can match, keyed on CompositeFIGI."""

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]: ...


class FinanceDatabaseGicsSource:
    """GICS labels from the ``financedatabase`` Equities dataset.

    Matches a security by CompositeFIGI first, then falls back to ISIN — many
    non-US names carry an ISIN in the dataset but no CompositeFIGI, so ISIN
    fallback is what lifts coverage over the AC #2 threshold. A match found by
    ISIN is still attributed to *our* CompositeFIGI. The frame is injectable for
    testing; left unset it loads lazily from ``financedatabase`` (a ~150k-row
    dataset, loaded once and cached).
    """

    def __init__(self, frame: Any = None) -> None:
        self._frame = frame

    def _equities_frame(self) -> Any:
        if self._frame is None:
            import financedatabase as fd

            self._frame = fd.Equities().select()
        return self._frame

    @staticmethod
    def _index(frame: Any, key_col: str) -> dict[str, dict[str, Any]]:
        """Map each non-null key to its first classified row (sector present)."""
        if key_col not in frame.columns:
            return {}
        cols = [key_col, _FD_SECTOR, _FD_INDUSTRY_GROUP, _FD_INDUSTRY]
        subset = frame[cols]
        subset = subset[subset[key_col].notna() & subset[_FD_SECTOR].notna()]
        subset = subset.drop_duplicates(subset=[key_col], keep="first")
        return {record[key_col]: record for record in subset.to_dict("records")}

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        frame = self._equities_frame()
        by_figi = self._index(frame, "composite_figi")
        by_isin = self._index(frame, "isin")
        found: dict[str, GicsClassification] = {}
        for security in securities:
            row = by_figi.get(security.composite_figi)
            if row is None and security.isin:
                row = by_isin.get(security.isin)
            if row is None:
                continue
            classification = classification_from_row(security.composite_figi, row)
            if classification.is_classified:
                found[security.composite_figi] = classification
        return found


@dataclass
class ClassificationSummary:
    """What a classification run covered and wrote."""

    active_total: int = 0
    classified: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_closed: int = 0
    unchanged: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)  # attributable per-figi reasons

    @property
    def coverage(self) -> float:
        """Fraction of active securities that received a classification."""
        if self.active_total == 0:
            return 0.0
        return self.classified / self.active_total

    def meets_threshold(self, threshold: float = DEFAULT_COVERAGE_THRESHOLD) -> bool:
        """True when coverage clears ``threshold`` (default AC #2's 0.90)."""
        return self.coverage >= threshold


def plan_classifications(
    securities: Sequence[SecurityIdentity], source: GicsSource
) -> list[GicsClassification]:
    """Resolve classifications for the requested securities (no DB writes).

    Keeps only securities the source actually classified, preserving request order.
    """
    found = source.fetch(list(securities))
    return [
        found[security.composite_figi]
        for security in securities
        if security.composite_figi in found
        and found[security.composite_figi].is_classified
    ]


def read_active_identities(conn: psycopg.Connection) -> list[SecurityIdentity]:
    """Active securities with their current ISIN/ticker (the GICS match keys).

    The ISIN enables the financedatabase ISIN fallback for names the dataset
    lacks a CompositeFIGI for. Active-only is the explicit survivorship scope.
    """
    rows = conn.execute(
        """
        SELECT s.composite_figi,
               max(y.symbol_value) FILTER (WHERE y.symbol_type = 'isin')   AS isin,
               max(y.symbol_value) FILTER (WHERE y.symbol_type = 'ticker') AS ticker
          FROM securities s
          LEFT JOIN security_symbology y
                 ON y.composite_figi = s.composite_figi
                AND y.valid_to IS NULL
         WHERE s.status = 'active'
         GROUP BY s.composite_figi
         ORDER BY s.composite_figi
        """
    ).fetchall()
    return [SecurityIdentity(figi, isin, ticker) for figi, isin, ticker in rows]


def read_active_coverage(conn: psycopg.Connection) -> tuple[int, int]:
    """``(classified_active, total_active)`` after ALL sources have written.

    The primary pass's :class:`ClassificationSummary` only knows financedatabase's
    own coverage; once fill sources (b3, sec_sic) have run, the honest
    whole-universe coverage is whatever currently-effective ``gics_scd`` rows back
    active securities — so the threshold gate is measured here, not from one pass.
    """
    total = conn.execute("SELECT count(*) FROM securities WHERE status = 'active'").fetchone()[0]
    classified = conn.execute(
        """
        SELECT count(*)
          FROM securities s
         WHERE s.status = 'active'
           AND EXISTS (SELECT 1 FROM gics_scd g
                        WHERE g.composite_figi = s.composite_figi
                          AND g.valid_to IS NULL
                          AND g.sector_name IS NOT NULL)
        """
    ).fetchone()[0]
    return (int(classified), int(total))


def read_unclassified_identities(conn: psycopg.Connection) -> list[SecurityIdentity]:
    """Active securities with NO currently-effective GICS row (the fill-source scope).

    Feeding a secondary source (e.g. B3, Story QH.1) only these identities is what
    makes it fill-only: it can never close or overwrite an existing classification,
    so the primary financedatabase source always wins where both could classify.
    """
    rows = conn.execute(
        """
        SELECT s.composite_figi, s.mic,
               max(y.symbol_value) FILTER (WHERE y.symbol_type = 'isin')   AS isin,
               max(y.symbol_value) FILTER (WHERE y.symbol_type = 'ticker') AS ticker
          FROM securities s
          LEFT JOIN security_symbology y
                 ON y.composite_figi = s.composite_figi
                AND y.valid_to IS NULL
         WHERE s.status = 'active'
           AND NOT EXISTS (SELECT 1 FROM gics_scd g
                            WHERE g.composite_figi = s.composite_figi
                              AND g.valid_to IS NULL)
         GROUP BY s.composite_figi, s.mic
         ORDER BY s.composite_figi
        """
    ).fetchall()
    return [SecurityIdentity(figi, isin, ticker, mic) for figi, mic, isin, ticker in rows]


def read_classifiable_identities(
    conn: psycopg.Connection, *, source: str
) -> list[SecurityIdentity]:
    """Active securities the given ``source`` may (re)classify (AC5 precedence scope).

    Returns actives that are either unclassified OR currently held by a STRICTLY
    lower-precedence source (per :data:`SOURCE_PRECEDENCE`) — the latter is what lets a
    higher-precedence source *supersede* a lower one on a later run (e.g. financedatabase
    or sec_sic reclaiming a name an ``llm``/``yahoo_profile`` pass had filled). A row from
    an equal/higher source, or an unknown/legacy source, is excluded so the source can
    never downgrade or clobber it. A ``source`` outside the precedence map gets the plain
    unclassified scope (it can only fill empty slots).
    """
    if source not in SOURCE_PRECEDENCE:
        return read_unclassified_identities(conn)
    rank = SOURCE_PRECEDENCE[source]
    lower_sources = [s for s, r in SOURCE_PRECEDENCE.items() if r > rank]
    # In scope unless a CURRENTLY-EFFECTIVE row "blocks" it — a blocking row is one whose
    # source is NOT strictly-lower (i.e. equal/higher precedence, or NULL/unknown).
    rows = conn.execute(
        """
        SELECT s.composite_figi, s.mic,
               max(y.symbol_value) FILTER (WHERE y.symbol_type = 'isin')   AS isin,
               max(y.symbol_value) FILTER (WHERE y.symbol_type = 'ticker') AS ticker
          FROM securities s
          LEFT JOIN security_symbology y
                 ON y.composite_figi = s.composite_figi
                AND y.valid_to IS NULL
         WHERE s.status = 'active'
           AND NOT EXISTS (SELECT 1 FROM gics_scd g
                            WHERE g.composite_figi = s.composite_figi
                              AND g.valid_to IS NULL
                              AND (g.source IS NULL OR g.source <> ALL(%s::text[])))
         GROUP BY s.composite_figi, s.mic
         ORDER BY s.composite_figi
        """,
        (lower_sources,),
    ).fetchall()
    return [SecurityIdentity(figi, isin, ticker, mic) for figi, mic, isin, ticker in rows]


def _current_row(
    conn: psycopg.Connection, composite_figi: str
) -> tuple[tuple[str | None, str | None, str | None, str | None], date, str | None] | None:
    """The currently-effective ``(level_names, valid_from, source)`` for a FIGI, or None.

    ``valid_from`` distinguishes a same-day correction from a cross-day version change;
    ``source`` lets :func:`apply_classifications` decide whether a writing source
    outranks the row already there (the AC5 precedence-upgrade).
    """
    row = conn.execute(
        """
        SELECT sector_name, industry_group_name, industry_name, sub_industry_name,
               valid_from, source
          FROM gics_scd
         WHERE composite_figi = %s
           AND valid_to IS NULL
        """,
        (composite_figi,),
    ).fetchone()
    if row is None:
        return None
    return (tuple(row[:4]), row[4], row[5])


def apply_classifications(
    conn: psycopg.Connection,
    plans: Sequence[GicsClassification],
    *,
    as_of_date: date | None = None,
) -> ClassificationSummary:
    """Write classifications in SCD shape, one transaction per security.

    Idempotent and survivorship-safe:

    * unchanged currently-effective row → left alone;
    * changed **on a later day** → the prior row is closed (``valid_to = as_of_date``)
      and a new row inserted, so ``gics_scd_no_overlap`` holds and history is kept;
    * changed **on the same day it was written** (``valid_from == as_of_date``) → the
      row is updated **in place**. Closing it would set ``valid_to = valid_from``,
      a zero-width period that violates ``gics_scd_validity_chk`` (``valid_to >
      valid_from``); a same-day correction has no historical period to preserve.

    Precedence-aware (AC5): when the writing source **outranks** the source of the
    currently-effective row (see :func:`outranks`), it supersedes it — same shape as a
    re-classification: levels changed → close + insert (or same-day update); same levels
    → an in-place **provenance upgrade** (no new row, since the classification value is
    unchanged — only its attribution improves). A non-outranking different source never
    modifies the row (defensive; the per-source scope already excludes these).

    Each security writes in its own transaction; a single failing write is
    rolled back, counted in ``summary.failed``, and the run continues — one bad
    row never halts the rest.
    """
    as_of_date = as_of_date or date.today()
    summary = ClassificationSummary()
    for classification in plans:
        try:
            with conn.transaction():
                current = _current_row(conn, classification.composite_figi)
                if current is not None:
                    cur_levels, cur_valid_from, cur_source = current
                    same_source = classification.source == cur_source
                    if not same_source and not outranks(classification.source, cur_source):
                        # A lower/equal-precedence (or unknown) different source must
                        # never overwrite or downgrade an existing row.
                        summary.unchanged += 1
                        continue
                    if cur_levels == classification.level_names():
                        if same_source:
                            summary.unchanged += 1
                            continue
                        # Same sector, higher-precedence source now backs it → upgrade
                        # provenance in place (no new SCD row; value unchanged).
                        _update_in_place(conn, classification)
                        summary.rows_updated += 1
                        continue
                    if cur_valid_from == as_of_date:
                        _update_in_place(conn, classification)
                        summary.rows_updated += 1
                        continue
                    if as_of_date < cur_valid_from:
                        # Backdated write: closing at as_of_date would violate the
                        # valid_to > valid_from CHECK — record WHY, don't let the
                        # CheckViolation vanish into an anonymous count.
                        summary.failed += 1
                        summary.failures.append(
                            f"{classification.composite_figi}: backdated ({as_of_date} < "
                            f"current valid_from {cur_valid_from})"
                        )
                        continue
                    conn.execute(
                        """
                        UPDATE gics_scd
                           SET valid_to = %s
                         WHERE composite_figi = %s
                           AND valid_to IS NULL
                        """,
                        (as_of_date, classification.composite_figi),
                    )
                    summary.rows_closed += 1
                _insert_row(conn, classification, valid_from=as_of_date)
                summary.rows_inserted += 1
        except psycopg.Error as exc:
            # A single security's write failing must not abort the whole run —
            # but it must be attributable, not an anonymous counter.
            summary.failed += 1
            summary.failures.append(
                f"{classification.composite_figi}: {type(exc).__name__}: {str(exc)[:160]}"
            )
    return summary


def _insert_row(
    conn: psycopg.Connection, classification: GicsClassification, *, valid_from: date
) -> None:
    """Insert a new currently-effective (``valid_to`` NULL) classification row."""
    conn.execute(
        """
        INSERT INTO gics_scd
            (composite_figi, sector_code, sector_name,
             industry_group_code, industry_group_name,
             industry_code, industry_name,
             sub_industry_code, sub_industry_name,
             source, valid_from)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            classification.composite_figi,
            classification.sector_code,
            classification.sector_name,
            classification.industry_group_code,
            classification.industry_group_name,
            classification.industry_code,
            classification.industry_name,
            classification.sub_industry_code,
            classification.sub_industry_name,
            classification.source,
            valid_from,
        ),
    )


def _update_in_place(conn: psycopg.Connection, classification: GicsClassification) -> None:
    """Overwrite the currently-effective row's levels (same-day correction).

    Touches only the level/source columns and never ``valid_from``/``valid_to``,
    so no zero-width period is created. The ``set_updated_at`` trigger refreshes
    ``updated_at``.
    """
    conn.execute(
        """
        UPDATE gics_scd
           SET sector_code = %s, sector_name = %s,
               industry_group_code = %s, industry_group_name = %s,
               industry_code = %s, industry_name = %s,
               sub_industry_code = %s, sub_industry_name = %s,
               source = %s
         WHERE composite_figi = %s
           AND valid_to IS NULL
        """,
        (
            classification.sector_code,
            classification.sector_name,
            classification.industry_group_code,
            classification.industry_group_name,
            classification.industry_code,
            classification.industry_name,
            classification.sub_industry_code,
            classification.sub_industry_name,
            classification.source,
            classification.composite_figi,
        ),
    )


def classify_universe(
    conn: psycopg.Connection,
    source: GicsSource,
    *,
    as_of_date: date | None = None,
) -> ClassificationSummary:
    """Classify every active security and report coverage against AC #2's threshold.

    Reads the active universe, resolves classifications from ``source``, writes
    them in SCD shape, and stamps the run's coverage onto the returned summary.
    """
    active = read_active_identities(conn)
    plans = plan_classifications(active, source)
    summary = apply_classifications(conn, plans, as_of_date=as_of_date)
    summary.active_total = len(active)
    # Coverage counts what actually LANDED: failed writes are not classified, and
    # counting them would overstate coverage against the AC#2 threshold.
    summary.classified = len(plans) - summary.failed
    return summary
