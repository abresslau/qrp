"""Daily news for a security — Google News RSS, fetched at serve time, never persisted.

Leverages Google's public News RSS (``news.google.com/rss/search``) — a structured feed meant
for consumption (no API key, no scraping of rendered HTML, no ToS grey-area). For a company we
query its name + "stock" and return the recent headlines with source + timestamp. Best-effort
and supplementary: a fetch/parse failure returns ``[]`` (unlike live quotes, missing news is not
an error and must never 503 the detail page). Pure + injectable: ``_http_get`` is monkeypatched
in tests. Stdlib only (``urllib`` + ``xml.etree`` + ``email.utils``) — no new dependency.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; qrp-news/1.0)"}
_HTTP_TIMEOUT = 12


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str | None
    published: str | None  # ISO-8601, or None if unparseable


def _http_get(url: str, timeout: int = _HTTP_TIMEOUT) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _clean_title(title: str, source: str | None) -> str:
    # Google News appends " - <Source>" to each headline; drop it when it matches the source tag.
    if source and title.endswith(f" - {source}"):
        return title[: -(len(source) + 3)].strip()
    return title.strip()


def _to_iso(pubdate: str | None) -> str | None:
    if not pubdate:
        return None
    try:
        return parsedate_to_datetime(pubdate).isoformat()
    except (TypeError, ValueError):
        return None


def parse_news(xml_text: str, *, limit: int) -> list[NewsItem]:
    """Parse a Google News RSS document into items (defensive: malformed XML → [])."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[NewsItem] = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is None or not (title_el.text or "").strip():
            continue
        src_el = item.find("source")
        source = (src_el.text or "").strip() if src_el is not None else None
        items.append(
            NewsItem(
                title=_clean_title(title_el.text or "", source),
                link=(link_el.text or "").strip() if link_el is not None else "",
                source=source or None,
                published=_to_iso(item.findtext("pubDate")),
            )
        )
        if len(items) >= limit:
            break
    return items


def fetch_news(query: str, *, limit: int = 12) -> list[NewsItem]:
    """Recent headlines for ``query`` from Google News RSS. Best-effort → [] on any failure."""
    if not query.strip():
        return []
    url = _RSS.format(q=urllib.parse.quote(query))
    try:
        xml_text = _http_get(url)
    except (urllib.error.URLError, OSError, ValueError):
        return []  # news is supplementary — a feed outage must not surface as an error
    return parse_news(xml_text, limit=limit)
