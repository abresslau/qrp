"""B3 sector classification source — fills the Brazil GICS gap (Story QH.1).

B3 publishes a "setor de atuação" view of each index's theoretical portfolio
(``GetPortfolioDay`` with ``segment=2``): every constituent row carries an abbreviated
"Setor / Subsetor" string. That taxonomy is B3's own, NOT GICS — this module maps it to
the canonical GICS **sector** labels through an explicit, reviewable table below.

Honesty notes:

* The mapping is a deliberate cross-taxonomy approximation, recorded as such by writing
  ``source='b3'`` on every row it produces. Only the SECTOR level is populated —
  industry-group/industry/sub-industry stay NULL (B3's subsectors do not line up with
  GICS industry groups; same depth-honesty rule as the financedatabase source).
* An unmapped segment string is reported (``last_unmapped``) and skipped, never guessed.
* ``Diversos`` maps to Consumer Discretionary on B3's own authority: *Diversos* is a
  subsector B3 places under its *Consumo Cíclico* sector (the abbreviated segment view
  drops the sector prefix for it).
* The payload is clean UTF-8; mojibake seen in Windows consoles is cp1252 rendering.

The mapping is keyed on NORMALISED strings (accents stripped, casefolded, whitespace
collapsed) because B3's abbreviations are inconsistent ("Cons N Cíclico" vs
"Cons N Ciclico", double spaces). Full-string exceptions are checked before the
sector-prefix rule — "Financ e Outros / Explor Imóveis" is GICS Real Estate, not
Financials.
"""

from __future__ import annotations

import base64
import json
import time
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Protocol

import requests

from sym.classification.gics import GicsClassification, SecurityIdentity

B3_PORTFOLIO_URL = (
    "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{token}"
)
_SECTOR_VIEW = "2"  # GetPortfolioDay segment=2 = the "setor de atuação" view
# IBOV + IBXX cover the BVMF universe (it was seeded from these two indexes).
DEFAULT_INDEX_CODES = ("IBOV", "IBXX")
SOURCE_NAME = "b3"


class B3ClassificationError(RuntimeError):
    """Loud failure for the B3 sector fetch — empty/garbled is an error, never data."""


def normalise_segment(segment: str) -> str:
    """Normalise a B3 segment string for mapping: strip accents, casefold, collapse
    spaces, and canonicalise "/" spacing.

    B3's abbreviated labels are inconsistent across rows ("Cíclico"/"Ciclico", double
    spaces, "X / Y" vs "X/Y") — the mapping table is keyed on this normal form so one
    entry covers all observed spellings. Slash canonicalisation matters most for the
    full-string exceptions: an uncovered spacing variant would otherwise fall through
    to the sector-prefix rule and be classified WRONG rather than reported unmapped.
    """
    decomposed = unicodedata.normalize("NFD", segment)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    collapsed = " ".join(stripped.casefold().split())
    return "/".join(part.strip() for part in collapsed.split("/"))


# Full normalised "Setor / Subsetor" strings that must NOT follow their sector prefix.
# Both the abbreviated and long-form sector spellings are covered (the feed mixes them).
_FULL_STRING_MAP: dict[str, str] = {
    # B3 files property companies under "Financeiro e Outros"; GICS split Real Estate
    # out of Financials in 2016.
    "financ e outros/explor imoveis": "Real Estate",
    "financeiro e outros/explor imoveis": "Real Estate",
}

# Normalised B3 sector prefix (the part before "/") -> GICS sector label. Bare
# subsector-only segments observed in the live feed (Diversos, Comput e Equips,
# Telecomunicação) get entries of their own.
_PREFIX_MAP: dict[str, str] = {
    "bens indls": "Industrials",
    "cons n basico": "Consumer Staples",  # observed only as ".../ Alimentos Processados"
    "cons n ciclico": "Consumer Staples",  # B3 "Consumo não Cíclico"
    "consumo ciclico": "Consumer Discretionary",
    "diversos": "Consumer Discretionary",  # B3 subsector of Consumo Cíclico (see docstring)
    "financ e outros": "Financials",
    "financeiro e outros": "Financials",
    "mats basicos": "Materials",
    "petroleo, gas e biocombustiveis": "Energy",
    "saude": "Health Care",
    "tec.informacao": "Information Technology",
    "comput e equips": "Information Technology",  # bare TI subsector
    "telecomunicacao": "Communication Services",
    "utilidade publ": "Utilities",
}


def map_segment_to_gics(segment: str) -> str | None:
    """B3 "Setor / Subsetor" string -> canonical GICS sector label, or None if unmapped."""
    norm = normalise_segment(segment)
    if not norm:
        return None
    full = _FULL_STRING_MAP.get(norm)
    if full is not None:
        return full
    prefix = norm.split("/", 1)[0].strip()
    return _PREFIX_MAP.get(prefix)


def parse_sector_rows(results: Iterable[dict]) -> dict[str, str]:
    """GetPortfolioDay(segment=2) ``results`` -> ``{ticker: segment}`` (pure).

    Rows without a usable ``cod`` or ``segment`` are skipped — absent data is absent,
    never invented.
    """
    out: dict[str, str] = {}
    for row in results:
        cod = (row.get("cod") or "").strip()
        seg = (row.get("segment") or "").strip()
        if cod and seg:
            out[cod.upper()] = seg
    return out


def _portfolio_token(index_code: str, page_size: int = 500) -> str:
    """Base64 of the GetPortfolioDay request params (segment=2 = sector view)."""
    params = {
        "language": "pt-br",
        "pageNumber": 1,
        "pageSize": page_size,
        "index": index_code,
        "segment": _SECTOR_VIEW,
    }
    return base64.b64encode(json.dumps(params).encode("utf-8")).decode("ascii")


class B3SectorClient(Protocol):
    """Returns the ``results`` rows of the sector view for a B3 index code."""

    def portfolio_sectors(self, index_code: str) -> list[dict]: ...


class HttpB3SectorClient:
    """Fetches the sector view from B3's listed-systems endpoint.

    Mirrors the universe provider's ``HttpB3Client`` conventions (retries, loud
    non-200/non-JSON/missing-results errors, single-page guard) for the segment=2 view.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 25.0,
        max_retries: int = 3,
        user_agent: str = "sym-classification/1.0 (personal research)",
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries
        self._user_agent = user_agent

    def portfolio_sectors(self, index_code: str) -> list[dict]:
        url = B3_PORTFOLIO_URL.format(token=_portfolio_token(index_code))
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.get(
                    url,
                    timeout=self._timeout,
                    headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                )
            except requests.RequestException as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise B3ClassificationError(
                    f"B3 returned HTTP {resp.status_code} for index {index_code!r}"
                )
            try:
                payload = resp.json()
            except ValueError as exc:
                raise B3ClassificationError(
                    f"B3 returned non-JSON for {index_code!r}: {exc}"
                ) from exc
            results = payload.get("results")
            if results is None:
                raise B3ClassificationError(f"B3 response for {index_code!r} has no 'results'")
            page = payload.get("page") or {}
            total_pages = page.get("totalPages")
            if isinstance(total_pages, int) and total_pages > 1:
                raise B3ClassificationError(
                    f"B3 sector view for {index_code!r} spans {total_pages} pages "
                    "(pageSize=500 exceeded) — pagination not implemented"
                )
            return results
        raise B3ClassificationError(f"B3 unreachable after {self._max_retries}: {last}")


class B3GicsSource:
    """GICS sector classifications from B3's published sector taxonomy.

    Implements the :class:`sym.classification.gics.GicsSource` protocol. Matches the
    given securities by ticker against the union of the configured indexes' sector
    views; every produced classification is SECTOR-ONLY with ``source='b3'``.

    Matching is BVMF-scoped: an identity that carries a ``mic`` is matched only when
    it is ``BVMF`` — B3 tickers are exchange-local strings, and a foreign security
    sharing one must never receive a Brazilian sector. Identities without a ``mic``
    are trusted ticker-only (test fakes / legacy callers).

    Attribution side-channels (reset per fetch, reported by the caller, never guessed):

    * ``last_unmapped`` (ticker -> raw segment): segment did not map — recorded for
      EVERY constituent, classified or not, so an abbreviation drift after a B3
      rebalance surfaces even when financedatabase already covers the name;
    * ``last_conflicts`` (ticker -> (segment_a, segment_b)): the index views disagree
      AND map to different GICS sectors — skipped, never last-wins;
    * ``last_unmatched`` (tickers): in-scope identities the fetch produced no
      classification for (no B3 row, unmapped, or conflicted).
    """

    def __init__(
        self,
        client: B3SectorClient | None = None,
        index_codes: Sequence[str] = DEFAULT_INDEX_CODES,
    ) -> None:
        self._client = client or HttpB3SectorClient()
        self._index_codes = tuple(index_codes)
        self.last_unmapped: dict[str, str] = {}
        self.last_conflicts: dict[str, tuple[str, str]] = {}
        self.last_unmatched: list[str] = []

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        self.last_unmapped = {}
        self.last_conflicts = {}
        self.last_unmatched = []
        sectors_by_ticker: dict[str, str] = {}
        for code in self._index_codes:
            for ticker, segment in parse_sector_rows(self._client.portfolio_sectors(code)).items():
                prev = sectors_by_ticker.get(ticker)
                if (
                    prev is not None
                    and normalise_segment(prev) != normalise_segment(segment)
                    and map_segment_to_gics(prev) != map_segment_to_gics(segment)
                ):
                    # The views genuinely disagree on the GICS outcome — never last-wins.
                    self.last_conflicts[ticker] = (prev, segment)
                sectors_by_ticker[ticker] = segment
        if not sectors_by_ticker:
            # Both portfolios parsing to nothing is an outage/shape break, not
            # "no Brazilian company has a sector".
            raise B3ClassificationError(
                f"B3 sector views for {self._index_codes} parsed to zero constituents"
            )
        by_ticker = {
            s.ticker.upper(): s
            for s in securities
            if s.ticker and (s.mic is None or s.mic == "BVMF")
        }
        found: dict[str, GicsClassification] = {}
        for ticker, segment in sectors_by_ticker.items():
            sector = map_segment_to_gics(segment)
            if sector is None:
                # Recorded BEFORE the identity check: drift must surface even for
                # constituents another source already classified.
                self.last_unmapped[ticker] = segment
                continue
            if ticker in self.last_conflicts:
                continue
            identity = by_ticker.get(ticker)
            if identity is None:
                continue  # constituent outside the requested set — not ours to classify
            found[identity.composite_figi] = GicsClassification(
                composite_figi=identity.composite_figi,
                sector_name=sector,
                industry_group_name=None,
                industry_name=None,
                source=SOURCE_NAME,
            )
        self.last_unmatched = sorted(
            ticker
            for ticker, identity in by_ticker.items()
            if identity.composite_figi not in found
        )
        return found
