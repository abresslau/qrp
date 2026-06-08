"""OpenFIGI resolution and FIGI-assignment classification (Story 1.6, FR-1..FR-4).

This module turns seed resolution inputs (``ResolutionInput``) into one of four
outcomes per security, *without* touching price ingestion — FIGI assignment is a
separate external dependency, so an OpenFIGI outage raised here never reaches the
ingest path (the decoupling is structural: see ``sym.ingest``).

Outcomes (``Outcome``):
  * ``assigned``             — exactly one CompositeFIGI; securities row is written.
  * ``no_figi_found``        — OpenFIGI returned no match.
  * ``ambiguous_figi``       — more than one distinct CompositeFIGI; candidates
                               recorded, nothing auto-assigned.
  * ``share_class_conflict`` — two distinct seed inputs resolved to the *same*
                               CompositeFIGI (would collapse two securities onto
                               one PK); both routed to review, neither assigned.

The HTTP call is isolated behind :class:`OpenFigiClient` so the classification
logic is testable without the network, and so an outage is a raised exception
(loud) rather than a silent "no match" (which would mis-mark every name).
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

import psycopg
import requests

from sym.identity.names import write_name
from sym.identity.review_queue import enqueue_review
from sym.identity.symbology import write_security
from sym.identity.universe import ISIN, TICKER, ResolutionInput, SeedSecurity

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

# sym symbol_type -> OpenFIGI idType.
_ID_TYPE = {TICKER: "TICKER", ISIN: "ID_ISIN"}


def _openfigi_ticker(value: str, exch_code: str | None = None) -> str:
    """Normalise a seed ticker to OpenFIGI/Bloomberg convention.

    Share classes use ``/`` not ``.`` (``BRK.A`` -> ``BRK/A``). Hong Kong drops
    leading zeros (``0700`` -> ``700``); this is exchange-specific -- Korea, by
    contrast, keeps them (``005930``), so leading zeros are only stripped for HK.
    """
    if exch_code == "HK" and value.isdigit():
        return str(int(value))
    return value.replace(".", "/")

# Outcome labels. The three review labels match securities_review_queue.status.
ASSIGNED = "assigned"
NO_FIGI_FOUND = "no_figi_found"
AMBIGUOUS_FIGI = "ambiguous_figi"
SHARE_CLASS_CONFLICT = "share_class_conflict"


class OpenFigiError(RuntimeError):
    """OpenFIGI was unreachable or returned an error status (an outage, not a no-match)."""


@dataclass(frozen=True)
class FigiRecord:
    """One instrument record returned by OpenFIGI for a query."""

    composite_figi: str
    share_class_figi: str | None
    figi: str | None = None
    ticker: str | None = None
    exch_code: str | None = None
    security_type: str | None = None
    name: str | None = None

    def as_candidate(self) -> dict[str, str | None]:
        """Compact JSON-serialisable form recorded in the review queue."""
        return {
            "composite_figi": self.composite_figi,
            "share_class_figi": self.share_class_figi,
            "figi": self.figi,
            "ticker": self.ticker,
            "exch_code": self.exch_code,
            "security_type": self.security_type,
            "name": self.name,
        }


@dataclass
class Resolution:
    """The classification result for a single seed security."""

    seed: SeedSecurity
    outcome: str
    query: ResolutionInput
    composite_figi: str | None = None
    share_class_figi: str | None = None
    name: str | None = None
    candidates: list[dict[str, str | None]] = field(default_factory=list)
    detail: str | None = None


class OpenFigiClient(Protocol):
    """Maps resolution inputs to FIGI records, one record list per input."""

    def map_identifiers(self, inputs: Sequence[ResolutionInput]) -> list[list[FigiRecord]]: ...


class HttpOpenFigiClient:
    """Live OpenFIGI v3 ``/mapping`` client.

    Honours the public rate limits (10 jobs/request unkeyed, 100 keyed) and
    raises :class:`OpenFigiError` on transport/HTTP failure so callers can treat
    an outage distinctly from a genuine no-match.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session: requests.Session | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        min_interval: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries
        # OpenFIGI caps a /mapping request at 100 jobs with an API key, 10 without.
        self._batch_size = 100 if api_key else 10
        # Pace requests under the public rate limit (≈25/min unkeyed, ≈250/min
        # keyed) so a large universe resolution doesn't trip 429 storms. Default
        # is a safe spacing for the current tier when not overridden.
        if min_interval is None:
            min_interval = 0.3 if api_key else 2.6
        self._min_interval = min_interval
        self._last_request = 0.0

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-OPENFIGI-APIKEY"] = self._api_key
        return headers

    @staticmethod
    def _job(inp: ResolutionInput) -> dict[str, str]:
        job = {"idType": _ID_TYPE[inp.symbol_type], "idValue": inp.symbol_value}
        if inp.symbol_type == TICKER:
            # Disambiguate a ticker by OpenFIGI exchCode (e.g. US/LN), NOT micCode:
            # OpenFIGI's micCode expects the segment MIC (XNGS), not the operating
            # MIC we store (XNAS), so micCode=XNAS matches nothing.
            job["idValue"] = _openfigi_ticker(inp.symbol_value, inp.exch_code)
            if inp.exch_code:
                job["exchCode"] = inp.exch_code
        return job

    @staticmethod
    def _parse_item(item: dict) -> list[FigiRecord]:
        # A successful item carries "data"; a no-match carries "warning";
        # a malformed job carries "error". Both non-data cases mean "no records".
        data = item.get("data")
        if not data:
            return []
        records = []
        for row in data:
            composite = row.get("compositeFIGI") or row.get("figi")
            if not composite:
                continue
            records.append(
                FigiRecord(
                    composite_figi=composite,
                    share_class_figi=row.get("shareClassFIGI"),
                    figi=row.get("figi"),
                    ticker=row.get("ticker"),
                    exch_code=row.get("exchCode"),
                    security_type=row.get("securityType"),
                    name=row.get("name"),
                )
            )
        return records

    def _throttle(self) -> None:
        """Sleep so consecutive requests are at least ``min_interval`` apart."""
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _post(self, jobs: list[dict[str, str]]) -> list[dict]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            self._throttle()
            try:
                resp = self._session.post(
                    OPENFIGI_URL, json=jobs, headers=self._headers(), timeout=self._timeout
                )
            except requests.RequestException as exc:  # network-level failure
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code == 429:  # rate limited: back off harder and retry
                time.sleep(self._min_interval + 2.0 * (attempt + 1))
                last_exc = OpenFigiError("rate limited (429)")
                continue
            if resp.status_code != 200:
                raise OpenFigiError(f"OpenFIGI returned HTTP {resp.status_code}")
            return resp.json()
        raise OpenFigiError(f"OpenFIGI unreachable after {self._max_retries} attempts: {last_exc}")

    def map_identifiers(self, inputs: Sequence[ResolutionInput]) -> list[list[FigiRecord]]:
        results: list[list[FigiRecord]] = []
        for start in range(0, len(inputs), self._batch_size):
            batch = inputs[start : start + self._batch_size]
            response = self._post([self._job(i) for i in batch])
            if len(response) != len(batch):
                raise OpenFigiError(
                    f"OpenFIGI returned {len(response)} items for {len(batch)} jobs"
                )
            results.extend(self._parse_item(item) for item in response)
        return results


def classify(
    seed: SeedSecurity, query: ResolutionInput, records: Sequence[FigiRecord]
) -> Resolution:
    """Classify one security's OpenFIGI records into an outcome.

    Records for a single listing-scoped query share a CompositeFIGI; more than
    one *distinct* CompositeFIGI means the input is ambiguous (no auto-assign).
    """
    by_composite: dict[str, FigiRecord] = {}
    for rec in records:
        by_composite.setdefault(rec.composite_figi, rec)

    if not by_composite:
        return Resolution(seed, NO_FIGI_FOUND, query, detail="OpenFIGI returned no match")

    if len(by_composite) > 1:
        return Resolution(
            seed,
            AMBIGUOUS_FIGI,
            query,
            candidates=[r.as_candidate() for r in by_composite.values()],
            detail=f"{len(by_composite)} distinct CompositeFIGIs matched",
        )

    (rec,) = by_composite.values()
    return Resolution(
        seed,
        ASSIGNED,
        query,
        composite_figi=rec.composite_figi,
        share_class_figi=rec.share_class_figi,
        name=rec.name,
    )


def detect_share_class_conflicts(resolutions: Sequence[Resolution]) -> None:
    """Demote assignments that collide on a CompositeFIGI to ``share_class_conflict``.

    Distinct seed inputs must each own a distinct CompositeFIGI (the PK of
    ``securities``). If two resolve to the same one, assigning both would either
    collide on the PK or silently merge two securities — a survivorship/identity
    hazard — so both are routed to review instead. Mutates ``resolutions`` in place.
    """
    claimants: dict[str, list[Resolution]] = defaultdict(list)
    for res in resolutions:
        if res.outcome == ASSIGNED and res.composite_figi:
            claimants[res.composite_figi].append(res)

    for composite, group in claimants.items():
        if len(group) < 2:
            continue
        names = sorted(r.seed.name for r in group)
        for res in group:
            res.outcome = SHARE_CLASS_CONFLICT
            res.candidates = [{"composite_figi": composite, "name": n} for n in names]
            res.detail = (
                f"CompositeFIGI {composite} claimed by {len(group)} inputs: {', '.join(names)}"
            )
            res.composite_figi = None
            res.share_class_figi = None


def _narrow_to_home_listing(
    records: Sequence[FigiRecord], home_exch_code: str | None
) -> list[FigiRecord]:
    """Prefer the records on the seed's home exchange (for a broad ISIN result).

    An ISIN matches a security across *every* listing — one CompositeFIGI per
    venue — so a raw ISIN result is usually ambiguous. When the seed names a home
    listing (MIC -> ``home_exch_code``) we keep only the records on that exchange,
    so a unique home listing still auto-assigns. If none match (e.g. the home
    listing was delisted and dropped from OpenFIGI), keep the full set so
    ``classify`` surfaces the candidates for review rather than discarding them.
    """
    if not home_exch_code:
        return list(records)
    on_home = [r for r in records if r.exch_code == home_exch_code]
    return on_home or list(records)


def plan_resolutions(
    securities: Sequence[SeedSecurity],
    client: OpenFigiClient,
    exch_codes: dict[str, str] | None = None,
) -> list[Resolution]:
    """Resolve every seed security to an outcome (no DB writes).

    Each security is queried by its primary resolution input (ticker+MIC when
    present, else ISIN), the ticker stamped with its OpenFIGI ``exch_code`` from
    ``exch_codes`` (MIC -> exchCode) for listing disambiguation. **ISIN fallback:**
    OpenFIGI only ticker-maps *active* listings, so a delisted or renamed name
    misses by ticker; any such no-match that also carries an ISIN is retried by
    that (durable) ISIN in a second pass. ISIN results — primary or fallback — are
    narrowed to the home listing via ``exch_code`` so a broad cross-venue match
    still assigns a unique security (else its candidates are surfaced for review).

    A single name failing to resolve never halts the run — a no-match or ambiguous
    match is an *outcome* (routed to review), not an exception. Only a true
    OpenFIGI outage raises :class:`OpenFigiError`, deliberately loud so the whole
    run is not silently mis-marked.
    """
    exch_codes = exch_codes or {}
    planned: list[SeedSecurity] = []
    inputs_by_seed: list[list[ResolutionInput]] = []
    queries: list[ResolutionInput] = []
    for seed in securities:
        inputs = seed.resolution_inputs()
        if not inputs:
            continue
        query = inputs[0]
        if query.symbol_type == TICKER and query.mic:
            query = replace(query, exch_code=exch_codes.get(query.mic))
        planned.append(seed)
        inputs_by_seed.append(inputs)
        queries.append(query)

    records = list(client.map_identifiers(queries))

    # Narrow any primary ISIN query to the seed's home listing.
    for i, query in enumerate(queries):
        if query.symbol_type == ISIN:
            records[i] = _narrow_to_home_listing(records[i], exch_codes.get(planned[i].mic))

    # ISIN fallback: retry primary no-matches that carry a secondary ISIN input.
    fallback = [
        i
        for i, recs in enumerate(records)
        if not recs and len(inputs_by_seed[i]) > 1 and inputs_by_seed[i][1].symbol_type == ISIN
    ]
    if fallback:
        fb_records = client.map_identifiers([inputs_by_seed[i][1] for i in fallback])
        for i, recs in zip(fallback, fb_records, strict=True):
            if not recs:
                continue  # ISIN also missed -> keep the ticker no-match (accurate)
            queries[i] = inputs_by_seed[i][1]
            records[i] = _narrow_to_home_listing(recs, exch_codes.get(planned[i].mic))

    resolutions = [
        classify(seed, query, recs)
        for seed, query, recs in zip(planned, queries, records, strict=True)
    ]
    detect_share_class_conflicts(resolutions)
    return resolutions


@dataclass
class ResolutionSummary:
    """Counts of what a resolution run did."""

    assigned: int = 0
    no_figi_found: int = 0
    ambiguous_figi: int = 0
    share_class_conflict: int = 0
    securities_created: int = 0
    names_written: int = 0
    review_enqueued: int = 0


def apply_resolutions(
    conn: psycopg.Connection, resolutions: Sequence[Resolution]
) -> ResolutionSummary:
    """Persist classified resolutions: one transaction per security.

    Assignments write ``securities`` + ``security_symbology``; every other
    outcome enqueues a review row. Each security commits independently so one
    bad row never rolls back the whole run.
    """
    summary = ResolutionSummary()
    for res in resolutions:
        with conn.transaction():
            if res.outcome == ASSIGNED:
                assert res.composite_figi is not None
                created = write_security(
                    conn,
                    seed=res.seed,
                    composite_figi=res.composite_figi,
                    share_class_figi=res.share_class_figi,
                )
                summary.assigned += 1
                if created:
                    summary.securities_created += 1
                if res.name:
                    write_name(conn, res.composite_figi, res.name)
                    summary.names_written += 1
            else:
                source_input = {
                    "name": res.seed.name,
                    "category": res.seed.category,
                    "symbol_type": res.query.symbol_type,
                    "symbol_value": res.query.symbol_value,
                    "mic": res.query.mic,
                }
                enqueued = enqueue_review(
                    conn,
                    query=res.query,
                    status=res.outcome,
                    candidates=res.candidates,
                    detail=res.detail,
                    source_input=source_input,
                )
                setattr(summary, res.outcome, getattr(summary, res.outcome) + 1)
                if enqueued:
                    summary.review_enqueued += 1
    return summary


def read_exch_codes(conn: psycopg.Connection) -> dict[str, str]:
    """Map each MIC to its OpenFIGI exchange code (the ticker disambiguator)."""
    rows = conn.execute(
        "SELECT mic, exch_code FROM exchange WHERE exch_code IS NOT NULL"
    ).fetchall()
    return {mic.strip(): code for mic, code in rows}


def resolve_universe(
    conn: psycopg.Connection,
    client: OpenFigiClient,
    securities: Sequence[SeedSecurity],
) -> ResolutionSummary:
    """Resolve seed securities via OpenFIGI and persist the outcomes."""
    exch_codes = read_exch_codes(conn)
    return apply_resolutions(conn, plan_resolutions(securities, client, exch_codes))


@dataclass
class NameBackfillSummary:
    """Counts of a company-name backfill run."""

    attempted: int = 0
    named: int = 0
    skipped_mismatch: int = 0  # ticker now resolves to a different FIGI (recycled) -> not named
    skipped_unresolved: int = 0  # no / ambiguous OpenFIGI match


def unnamed_securities(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    """Securities with no ``security_names`` row + their current ticker/MIC."""
    rows = conn.execute(
        """
        SELECT s.composite_figi, y.symbol_value, s.mic
          FROM securities s
          JOIN security_symbology y
            ON y.composite_figi = s.composite_figi
           AND y.symbol_type = 'ticker' AND y.valid_to IS NULL
         WHERE NOT EXISTS (SELECT 1 FROM security_names n WHERE n.composite_figi = s.composite_figi)
         ORDER BY s.composite_figi
        """
    ).fetchall()
    return [
        (figi, ticker, mic.strip() if isinstance(mic, str) else mic)
        for figi, ticker, mic in rows
    ]


def backfill_names(
    conn: psycopg.Connection,
    client: OpenFigiClient,
    *,
    limit: int | None = None,
    chunk_size: int = 100,
) -> NameBackfillSummary:
    """Fill ``security_names`` for securities created without a name (e.g. via the
    universe bridge), resolving the company name from OpenFIGI by current ticker.

    A name is written **only** when OpenFIGI resolves the ticker to the *same*
    CompositeFIGI the security already holds — so a recycled ticker that now points
    elsewhere never mislabels an existing security. Idempotent and resumable
    (autocommit + chunked): a re-run only touches still-unnamed securities, so it
    also fills any names a later population adds.
    """
    conn.autocommit = True
    rows = unnamed_securities(conn)
    if limit is not None:
        rows = rows[:limit]
    exch_codes = read_exch_codes(conn)
    summary = NameBackfillSummary()
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        seeds = [SeedSecurity(t, "name_backfill", t, mic, None, None) for _f, t, mic in chunk]
        resolutions = plan_resolutions(seeds, client, exch_codes)
        for (figi, _ticker, _mic), res in zip(chunk, resolutions, strict=True):
            summary.attempted += 1
            if res.outcome == ASSIGNED and res.composite_figi == figi and res.name:
                write_name(conn, figi, res.name)
                summary.named += 1
            elif res.outcome == ASSIGNED and res.composite_figi != figi:
                summary.skipped_mismatch += 1
            else:
                summary.skipped_unresolved += 1
    return summary
