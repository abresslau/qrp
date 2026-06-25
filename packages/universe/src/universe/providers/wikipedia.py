"""Wikipedia index source + revision-diff engine — Story U2.3.

The fallback/corroboration archetype, and the only *free* multi-year point-in-time
history for the S&P family. Two mechanisms:

* the current **constituents table** (with each member's "Date added") → join
  events with real, dated joins where the table records them;
* the **"Selected changes" table** → dated add/remove events (leavers, the part a
  current snapshot can't give); and
* a reusable, pure **revision-diff engine** (:func:`revision_diff`) that turns a
  sequence of dated membership snapshots (e.g. fetched page revisions) into
  change events — ``poll_bounded`` (the date is only bounded by when the revision
  was taken).

Identifiers are normalised (``ticker_token``) before diffing so format drift
(``BRK.B`` vs ``BRK-B``) can't fake a leave+rejoin. An empty/garbled parse is a
loud :class:`IndexSourceError` (never wipes a universe).
"""

from __future__ import annotations

import time
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Protocol

import requests

from universe.membership_diff import diff_identifier_sets, ticker_token
from universe.providers.index_source import (
    ARCHETYPE_WIKIPEDIA,
    IndexSourceError,
    register_index_source,
)
from universe.registry import EXACT, JOIN, LEAVE, POLL_BOUNDED, MembershipChange

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


# --- HTML table parsing (stdlib only) ---------------------------------------


class _TableParser(HTMLParser):
    """Collect ``wikitable`` rows as lists of cell-text (handles th/td, strips refs)."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_wikitable = 0
        self._table_depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip = 0  # inside a <sup> reference / style we don't want text from

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table_depth += 1
            classes = dict(attrs).get("class", "") or ""
            if "wikitable" in classes:
                self._in_wikitable = self._table_depth
                self.tables.append([])
        elif self._in_wikitable:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell = []
            elif tag in ("sup", "style", "span"):
                if tag == "sup":
                    self._skip += 1

    def handle_endtag(self, tag):
        if tag == "table":
            if self._in_wikitable == self._table_depth:
                self._in_wikitable = 0
            self._table_depth -= 1
        elif self._in_wikitable:
            if tag == "tr" and self._row is not None:
                if self._row:
                    self.tables[-1].append(self._row)
                self._row = None
            elif tag in ("td", "th") and self._cell is not None and self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()))
                self._cell = None
            elif tag == "sup" and self._skip:
                self._skip -= 1

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def parse_wikitables(html: str) -> list[list[list[str]]]:
    """All ``wikitable`` tables as lists of rows, each row a list of cell strings."""
    parser = _TableParser()
    parser.feed(html)
    return parser.tables


def _header_index(header: list[str], *names: str) -> int | None:
    """Index of the first header cell matching any of ``names`` (case-insensitive)."""
    low = [h.strip().lower() for h in header]
    for name in names:
        target = name.strip().lower()
        for i, h in enumerate(low):
            if h == target or target in h:
                return i
    return None


def _parse_wiki_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# --- index specs ------------------------------------------------------------

# Yahoo-style ticker suffix -> operating MIC. European Wikipedia tables list
# tickers like ``ADS.DE`` / ``AIR.PA`` / ``NESN.SW`` whose suffix encodes the
# listing exchange — so a pan-European index (EURO STOXX 50) resolves each name to
# its true home venue rather than a single forced MIC. (Only recognised exchange
# suffixes are stripped; a share-class dot like ``BT.A`` is left intact.)
SUFFIX_MIC: dict[str, str] = {
    "DE": "XETR", "F": "XFRA", "PA": "XPAR", "AS": "XAMS", "MI": "XMIL",
    "MC": "XMAD", "SW": "XSWX", "L": "XLON", "BR": "XBRU", "HE": "XHEL",
    "ST": "XSTO", "OL": "XOSL", "LS": "XLIS", "CO": "XCSE", "VI": "XWBO",
}


def split_yahoo_suffix(ticker: str, default_mic: str) -> tuple[str, str]:
    """Split a Yahoo-suffixed ticker into ``(base, mic)``.

    ``ADS.DE`` → ``('ADS', 'XETR')``; ``III`` → ``('III', default_mic)``;
    ``BT.A`` → ``('BT.A', default_mic)`` (``.A`` is a share class, not an exchange).
    """
    base, sep, suffix = ticker.rpartition(".")
    if sep and suffix.upper() in SUFFIX_MIC:
        return base, SUFFIX_MIC[suffix.upper()]
    return ticker, default_mic


# Built-in defaults; overridable via universe config. mic is the resolution
# default (US composite FIGIs are venue-independent, so XNYS resolves any US name).
# yahoo_suffix=True derives each member's MIC from its ticker suffix (European).
_BUILTIN_SPECS: dict[str, dict] = {
    "sp500": {"title": "List of S&P 500 companies", "mic": "XNYS"},
    "sp400": {"title": "List of S&P 400 companies", "mic": "XNYS"},
    "sp600": {"title": "List of S&P 600 companies", "mic": "XNYS"},
    # Nasdaq-100 (US, Nasdaq-listed). The article's "Components" table carries a Ticker column;
    # bare tickers map directly to XNAS (no yahoo suffix). Wikipedia is the keyless fallback for
    # FMP's "nasdaq" constituent endpoint (free tier needs a key).
    "nasdaq100": {"title": "Nasdaq-100", "mic": "XNAS"},
    # European flagships (current snapshot; build-forward PIT). Yahoo-suffixed.
    "dax": {"title": "DAX", "mic": "XETR", "yahoo_suffix": True},
    "cac40": {"title": "CAC 40", "mic": "XPAR", "yahoo_suffix": True},
    "ftse100": {"title": "FTSE 100", "mic": "XLON", "yahoo_suffix": True},
    "ibex35": {"title": "IBEX 35", "mic": "XMAD", "yahoo_suffix": True},
    "ftsemib": {"title": "FTSE MIB", "mic": "XMIL", "yahoo_suffix": True},
    "aex": {"title": "AEX index", "mic": "XAMS", "yahoo_suffix": True},
    "smi": {"title": "Swiss Market Index", "mic": "XSWX", "yahoo_suffix": True},
    "estoxx50": {"title": "EURO STOXX 50", "mic": "XETR", "yahoo_suffix": True},
}


class WikipediaClient(Protocol):
    """Returns the rendered HTML of a Wikipedia page title."""

    def page_html(self, title: str) -> str: ...


class HttpWikipediaClient:
    """Fetches rendered page HTML via the MediaWiki ``action=parse`` API."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        user_agent: str = "sym-universe/1.0 (personal research)",
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries
        self._user_agent = user_agent

    def page_html(self, title: str) -> str:
        params = {
            "action": "parse",
            "page": title,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        }
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.get(
                    WIKIPEDIA_API,
                    params=params,
                    timeout=self._timeout,
                    headers={"User-Agent": self._user_agent},
                )
            except requests.RequestException as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise IndexSourceError(f"Wikipedia returned HTTP {resp.status_code} for {title!r}")
            try:
                payload = resp.json()
            except ValueError as exc:
                raise IndexSourceError(f"Wikipedia returned non-JSON for {title!r}") from exc
            if "error" in payload:
                raise IndexSourceError(f"Wikipedia API error for {title!r}: {payload['error']}")
            text = payload.get("parse", {}).get("text")
            if not text:  # warnings-only / unexpected shape — must be a source error,
                raise IndexSourceError(  # not a KeyError that bypasses the fallback chain
                    f"Wikipedia response for {title!r} has no parse.text"
                )
            return text
        raise IndexSourceError(f"Wikipedia unreachable after {self._max_retries}: {last}")


def _constituent_changes(
    tables: list[list[list[str]]], mic: str, at: date, *, yahoo_suffix: bool = False
) -> list[MembershipChange]:
    """Current members from the constituents table (join at Date added, else poll).

    Of the tables carrying a Symbol/Ticker-ish column, the LARGEST is taken as the
    constituents table — the "Selected changes" table also has Ticker headers, and
    if it precedes the constituents table a first-match would return a handful of
    recent adds as the entire index (non-empty, so it would pass every guard).
    """
    candidates = [
        t for t in tables if t and _header_index(t[0], "Symbol", "Ticker") is not None
    ]
    if not candidates:
        raise IndexSourceError("no constituents table with a Symbol column found")
    table = max(candidates, key=len)
    header = table[0]
    sym_i = _header_index(header, "Symbol", "Ticker")
    date_i = _header_index(header, "Date added", "Date first added")
    changes: list[MembershipChange] = []
    for row in table[1:]:
        if sym_i >= len(row):
            continue
        symbol = row[sym_i].strip()
        if not symbol:
            continue
        has_date = date_i is not None and date_i < len(row)
        added = _parse_wiki_date(row[date_i]) if has_date else None
        if yahoo_suffix:
            base, row_mic = split_yahoo_suffix(symbol, mic)
        else:
            base, row_mic = symbol, mic
        if not base:
            continue  # garbled cell (e.g. '.DE') would mint a poison 'ticker:@MIC' token
        token = ticker_token(base, row_mic)
        if added is not None:
            changes.append(MembershipChange(token, JOIN, added, ARCHETYPE_WIKIPEDIA, EXACT))
        else:
            changes.append(MembershipChange(token, JOIN, at, ARCHETYPE_WIKIPEDIA, POLL_BOUNDED))
    if not changes:
        raise IndexSourceError("constituents table parsed to zero members")
    return changes


def _changes_table_events(
    tables: list[list[list[str]]], mic: str, start: date, end: date
) -> list[MembershipChange]:
    """Dated add/remove events from the 'Selected changes' table (positional).

    The S&P changes table has nested headers (Added/Removed → Ticker/Security):
    columns [Date, AddedTicker, AddedSecurity, RemovedTicker, RemovedSecurity,
    Reason]. We read positionally and tolerate short rows.
    """
    events: list[MembershipChange] = []
    for table in tables:
        if len(table) < 2:
            continue
        flat_header = " ".join(c.lower() for row in table[:2] for c in row)
        if "added" not in flat_header or "removed" not in flat_header:
            continue
        for row in table:
            if not row:
                continue
            on = _parse_wiki_date(row[0])
            if on is None or on < start or on > end:
                continue
            added = row[1].strip() if len(row) > 1 else ""
            removed = row[3].strip() if len(row) > 3 else ""
            if added:
                events.append(
                    MembershipChange(ticker_token(added, mic), JOIN, on, ARCHETYPE_WIKIPEDIA, EXACT)
                )
            if removed:
                events.append(
                    MembershipChange(
                        ticker_token(removed, mic), LEAVE, on, ARCHETYPE_WIKIPEDIA, EXACT
                    )
                )
    return events


def revision_diff(
    snapshots: list[tuple[date, set[str]]], source: str = ARCHETYPE_WIKIPEDIA
) -> list[MembershipChange]:
    """Dated change-events from a sequence of (date, member-token-set) snapshots.

    Snapshots are sorted ascending; each consecutive pair is diffed on the
    identifier set at the later date (``poll_bounded`` — the date is bounded by
    when the revision was taken). The first snapshot seeds joins at its own date.
    """
    ordered = sorted(snapshots, key=lambda s: s[0])
    changes: list[MembershipChange] = []
    previous: set[str] = set()
    for snap_date, members in ordered:
        changes.extend(
            diff_identifier_sets(previous, members, snap_date, source, precision=POLL_BOUNDED)
        )
        previous = members
    return changes


class WikipediaIndexSource:
    """Derives membership events for an index from its Wikipedia page."""

    archetype = ARCHETYPE_WIKIPEDIA
    # Full current-membership token set from the last fetch (U3.5): the constituents
    # table ONLY — its joins may carry EXACT dates, which is why snapshot-ness must be
    # declared here and never inferred from date precision. The "Selected changes"
    # table's dated events are not part of the snapshot.
    last_snapshot_tokens: set[str] | None = None

    def __init__(self, client: WikipediaClient, specs: dict[str, dict] | None = None) -> None:
        self._client = client
        self._specs = {**_BUILTIN_SPECS, **(specs or {})}

    def fetch(self, index_key: str, start: date, end: date) -> list[MembershipChange]:
        # Reset on entry: a raising fetch must not leak the previous call's snapshot.
        self.last_snapshot_tokens = None
        spec = self._specs.get(index_key)
        if spec is None:
            raise IndexSourceError(f"no Wikipedia spec for index {index_key!r}")
        html = self._client.page_html(spec["title"])
        tables = parse_wikitables(html)
        if not tables:
            raise IndexSourceError(f"no wikitable parsed for {index_key!r} (empty/garbled page)")
        mic = spec.get("mic", "XNYS")
        yahoo_suffix = bool(spec.get("yahoo_suffix"))
        changes = _constituent_changes(tables, mic, end, yahoo_suffix=yahoo_suffix)
        self.last_snapshot_tokens = {c.raw_identifier for c in changes}
        # The S&P "Selected changes" table is US-only; European pages rarely have a
        # parseable one, so this is a no-op there (current snapshot → build-forward).
        changes.extend(_changes_table_events(tables, mic, start, end))
        return changes


def _build_from_config(
    client: WikipediaClient | None = None, specs: dict[str, dict] | None = None, **_: object
):
    return WikipediaIndexSource(client or HttpWikipediaClient(), specs)


register_index_source(ARCHETYPE_WIKIPEDIA, _build_from_config)
