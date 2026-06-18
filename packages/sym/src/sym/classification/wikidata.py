"""Wikidata ``industry`` (P452) → GICS-sector classification (multi-source matrix).

A FREE, KEYLESS, *structured* opinion source (probed reachable 2026-06-18). Matches a
security to its Wikidata entity by ISIN (P946) and reads the entity's ``industry`` (P452)
claims, mapping them onto the 11 GICS sectors via a documented crosswalk. A company carries
several industry claims (Apple → software / electronics / consumer-electronics / IT); the
source maps each and picks the **most common** mapped sector (mode), so the dominant
classification wins and a single tangential claim can't flip it. An industry no rule covers
is recorded unmapped — never guessed.

Chosen over scraping Google/Perplexity: those are LLM answer engines (an AI's guess = the
existing ``llm`` source, but brittle + ToS-fraught to scrape). Wikidata is structured data
with a real query API, so it adds genuinely independent signal. Sector-only
(``source='wikidata'``); Wikidata industries are not GICS industries → industry levels NULL.
Stdlib ``urllib`` only — no new dependency.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

from sym.classification._http import RequestThrottle
from sym.classification.gics import GicsClassification, SecurityIdentity

_SPARQL_URL = "https://query.wikidata.org/sparql"
_UA = {
    "User-Agent": "qrp-sym/1.0 (research; codex@gladstone-management.com)",
    "Accept": "application/sparql-results+json",
}
_HTTP_TIMEOUT = 30
_BATCH = 50  # ISINs per SPARQL query (VALUES clause)
MAX_CONSECUTIVE_ERRORS = 5  # circuit-breaker on a SPARQL outage (mirrors yahoo_profile)

# ---------------------------------------------------------------------------
# Wikidata industry label → GICS sector crosswalk
# ---------------------------------------------------------------------------
# Keyed on substrings of the lower-cased Wikidata industry label. Checked in order; the
# FIRST matching keyword wins for a given industry. A company's sector is then the mode of
# its mapped industries. Labels kept identical to the 11 GICS sector strings the other
# sources emit so the heatmap/validate group cleanly.
_INDUSTRY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("semiconductor", "Information Technology"),
    ("software", "Information Technology"),
    ("information technology", "Information Technology"),
    ("computer", "Information Technology"),
    ("internet", "Information Technology"),
    ("cloud", "Information Technology"),
    ("electronics", "Information Technology"),
    ("mobile phone", "Information Technology"),
    ("pharmaceutic", "Health Care"),
    ("biotechnolog", "Health Care"),
    ("health", "Health Care"),
    ("medical", "Health Care"),
    ("hospital", "Health Care"),
    ("bank", "Financials"),
    ("insurance", "Financials"),
    ("financial", "Financials"),
    ("investment", "Financials"),
    ("asset management", "Financials"),
    ("real estate", "Real Estate"),
    ("petroleum", "Energy"),
    ("oil and gas", "Energy"),
    ("oil & gas", "Energy"),
    ("natural gas", "Energy"),
    ("coal", "Energy"),
    ("mining", "Materials"),
    ("steel", "Materials"),
    ("metal", "Materials"),
    ("chemical", "Materials"),
    ("paper", "Materials"),
    ("forestry", "Materials"),
    ("cement", "Materials"),
    ("telecommunication", "Communication Services"),
    ("telecom", "Communication Services"),
    ("media", "Communication Services"),
    ("broadcast", "Communication Services"),
    ("publishing", "Communication Services"),
    ("entertainment", "Communication Services"),
    ("advertising", "Communication Services"),
    ("digital distribution", "Communication Services"),
    ("automotive", "Consumer Discretionary"),
    ("automobile", "Consumer Discretionary"),
    ("retail", "Consumer Discretionary"),
    ("apparel", "Consumer Discretionary"),
    ("clothing", "Consumer Discretionary"),
    ("hotel", "Consumer Discretionary"),
    ("restaurant", "Consumer Discretionary"),
    ("hospitality", "Consumer Discretionary"),
    ("gambling", "Consumer Discretionary"),
    ("consumer electronics", "Consumer Discretionary"),
    ("food", "Consumer Staples"),
    ("beverage", "Consumer Staples"),
    ("tobacco", "Consumer Staples"),
    ("brewing", "Consumer Staples"),
    ("grocery", "Consumer Staples"),
    ("household", "Consumer Staples"),
    ("electric utility", "Utilities"),
    ("water utility", "Utilities"),
    ("utility", "Utilities"),
    ("aerospace", "Industrials"),
    ("airline", "Industrials"),
    ("defense", "Industrials"),
    ("construction", "Industrials"),
    ("machinery", "Industrials"),
    ("transport", "Industrials"),
    ("logistics", "Industrials"),
    ("engineering", "Industrials"),
    ("manufacturing", "Industrials"),
)


def industry_to_gics(label: str | None) -> str | None:
    """Map one Wikidata industry label to a GICS sector, or None if unmatched."""
    if not label:
        return None
    low = label.strip().lower()
    for kw, sector in _INDUSTRY_KEYWORDS:
        if kw in low:
            return sector
    return None


def dominant_sector(industries: Sequence[str]) -> str | None:
    """The most-common mapped GICS sector across a company's industries (deterministic ties).

    Returns None if no industry maps. Ties broken by GICS-sector name order so the result
    is stable run-to-run regardless of claim ordering.
    """
    mapped = [s for s in (industry_to_gics(i) for i in industries) if s]
    if not mapped:
        return None
    counts = Counter(mapped)
    top = max(counts.values())
    return sorted(s for s, n in counts.items() if n == top)[0]


class WikidataClient(Protocol):
    """The one lookup the source needs (injectable for DB-free testing)."""

    def industries_for_isins(self, isins: Sequence[str]) -> dict[str, list[str]]:
        """Map each ISIN to the list of its Wikidata industry labels (absent ISINs omitted)."""
        ...


class HttpWikidataClient:
    """Live :class:`WikidataClient` over the Wikidata SPARQL endpoint (stdlib ``urllib``)."""

    def __init__(self, min_interval: float = 0.2) -> None:
        self._throttle = RequestThrottle(min_interval)

    def industries_for_isins(self, isins: Sequence[str]) -> dict[str, list[str]]:
        values = " ".join(f'"{i}"' for i in isins if i)
        if not values:
            return {}
        query = (
            "SELECT ?isin ?industryLabel WHERE { "
            f"VALUES ?isin {{ {values} }} "
            "?company wdt:P946 ?isin. ?company wdt:P452 ?industry. "
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }'
        )
        self._throttle.wait()
        data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
        req = urllib.request.Request(_SPARQL_URL, data=data, headers=_UA)  # POST (large VALUES)
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out: dict[str, list[str]] = {}
        for b in payload.get("results", {}).get("bindings", []):
            isin = b.get("isin", {}).get("value")
            label = b.get("industryLabel", {}).get("value")
            if isin and label:
                out.setdefault(isin, []).append(label)
        return out


class WikidataGicsSource:
    """GICS *sector* opinions from Wikidata industry (P452) claims, matched by ISIN.

    Implements the :class:`sym.classification.gics.GicsSource` protocol. Side-channels
    (reset per ``fetch``): ``last_unmatched`` (figis with no ISIN / no Wikidata entity /
    no industry), ``last_unmapped`` (figi -> industries none of which mapped),
    ``last_short_circuited`` (ISINs not queried after the breaker tripped),
    ``last_errors`` (batch -> message).
    """

    def __init__(self, client: WikidataClient | None = None) -> None:
        self._client = client or HttpWikidataClient()
        self.last_unmatched: list[str] = []
        self.last_unmapped: dict[str, list[str]] = {}
        self.last_short_circuited: list[str] = []
        self.last_errors: dict[str, str] = {}

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        self.last_unmatched = []
        self.last_unmapped = {}
        self.last_short_circuited = []
        self.last_errors = {}

        by_isin: dict[str, list[SecurityIdentity]] = {}
        for s in securities:
            if s.isin:
                by_isin.setdefault(s.isin, []).append(s)
            else:
                self.last_unmatched.append(s.composite_figi)

        isins = list(by_isin)
        industries: dict[str, list[str]] = {}
        consecutive_errors = 0
        for i in range(0, len(isins), _BATCH):
            batch = isins[i : i + _BATCH]
            try:
                industries.update(self._client.industries_for_isins(batch))
                consecutive_errors = 0
            except Exception as exc:  # noqa: BLE001 — a batch failure is isolated
                self.last_errors[f"batch@{i}"] = f"{type(exc).__name__}: {exc}"
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    self.last_short_circuited.extend(isins[i + _BATCH :])
                    break

        found: dict[str, GicsClassification] = {}
        for isin, ids in by_isin.items():
            labels = industries.get(isin)
            if not labels:
                self.last_unmatched.extend(s.composite_figi for s in ids)
                continue
            sector = dominant_sector(labels)
            if sector is None:
                for s in ids:
                    self.last_unmapped[s.composite_figi] = labels
                continue
            for s in ids:
                found[s.composite_figi] = GicsClassification(
                    composite_figi=s.composite_figi,
                    sector_name=sector,
                    industry_group_name=None,
                    industry_name=None,
                    source="wikidata",
                )
        return found
