"""Daily-news source (Google News RSS) — DB-free, fixture XML + monkeypatched fetch."""

from __future__ import annotations

from qrp_api.modules.sym import news as news_mod
from qrp_api.modules.sym.gateway import DbSymGateway
from qrp_api.modules.sym.news import fetch_news, parse_news

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Comerica (CMA) Stock Is Up, What You Need To Know - Yahoo Finance</title>
    <link>https://news.example/1</link>
    <pubDate>Wed, 18 Jun 2026 14:30:00 GMT</pubDate>
    <source url="https://yahoo.com">Yahoo Finance</source>
  </item>
  <item>
    <title>Headline with no source tag</title>
    <link>https://news.example/2</link>
    <pubDate>not-a-date</pubDate>
  </item>
  <item>
    <title></title><link>https://news.example/blank</link>
  </item>
</channel></rss>
"""


def test_parse_news_strips_source_suffix_and_dates():
    items = parse_news(_RSS, limit=10)
    assert len(items) == 2  # the empty-title item is skipped
    a = items[0]
    assert a.title == "Comerica (CMA) Stock Is Up, What You Need To Know"  # " - Yahoo Finance" stripped
    assert a.source == "Yahoo Finance"
    assert a.link == "https://news.example/1"
    assert a.published == "2026-06-18T14:30:00+00:00"
    b = items[1]
    assert b.title == "Headline with no source tag" and b.source is None
    assert b.published is None  # unparseable pubDate → None, not a crash


def test_parse_news_limit_and_malformed():
    assert len(parse_news(_RSS, limit=1)) == 1
    assert parse_news("<not xml", limit=10) == []  # malformed → [] (defensive)


def test_fetch_news_empty_query_and_failure(monkeypatch):
    assert fetch_news("   ") == []  # blank query, no fetch
    monkeypatch.setattr(news_mod, "_http_get", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert fetch_news("Apple") == []  # feed outage → [] (news is best-effort, never raises)


def test_fetch_news_parses_live_shape(monkeypatch):
    monkeypatch.setattr(news_mod, "_http_get", lambda *a, **k: _RSS)
    items = fetch_news("Comerica", limit=5)
    assert items[0].source == "Yahoo Finance"


class _Cur:
    def __init__(self, one):
        self._one = one

    def fetchone(self):
        return self._one


class _Conn:
    """Serves the name/ticker lookups security_news() issues."""

    def execute(self, sql, params=None):
        if "FROM security_names" in sql:
            return _Cur(("Comerica Inc",))
        if "FROM security_symbology" in sql:
            return _Cur(("CMA",))
        return _Cur(None)


def test_gateway_security_news_queries_by_company_name(monkeypatch):
    captured = {}

    def _fake(query, **k):
        captured["q"] = query
        return [news_mod.NewsItem("H", "L", "S", None)]

    monkeypatch.setattr(news_mod, "fetch_news", _fake)
    out = DbSymGateway(_Conn()).security_news("F1")
    assert "Comerica Inc" in captured["q"]  # uses the company name, not the figi
    assert out == [{"title": "H", "link": "L", "source": "S", "published": None}]
