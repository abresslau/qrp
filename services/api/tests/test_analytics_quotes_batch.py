"""Bounded quote fan-out ported into the analytics twin (portfolios-live-heatmap-and-pizza).

Mirrors the sym twin's `fetch_quotes_batch` tests — the two copies must stay in lock-step:
de-dup + honest partial coverage, the whole-source 503 raise, an empty input, and the
wall-clock budget (a hung symbol must not block past `budget`). DB-free, monkeypatched fetch.
"""

from __future__ import annotations

import threading
import time

import pytest

from analytics import quotes
from analytics.quotes import QuoteSourceUnreachable, RawQuote


def test_fetch_quotes_batch_partial_and_dedup(monkeypatch):
    def fake(sym, **kw):
        if sym == "AAA":
            return RawQuote(10.0, 9.0, "USD", 1)
        if sym == "BBB":
            return None  # reachable, no data -> per-symbol miss
        raise QuoteSourceUnreachable("net")  # CCC network-errors

    monkeypatch.setattr(quotes, "fetch_raw_quote", fake)
    out = quotes.fetch_quotes_batch(["AAA", "BBB", "CCC", "AAA"])  # duplicate AAA de-duped
    assert set(out) == {"AAA", "BBB", "CCC"}
    assert out["AAA"] == RawQuote(10.0, 9.0, "USD", 1)
    assert out["BBB"] is None and out["CCC"] is None  # a mix is honest partial coverage


def test_fetch_quotes_batch_all_network_error_raises(monkeypatch):
    def boom(sym, **kw):
        raise QuoteSourceUnreachable("down")

    monkeypatch.setattr(quotes, "fetch_raw_quote", boom)
    with pytest.raises(QuoteSourceUnreachable):
        quotes.fetch_quotes_batch(["AAA", "BBB"])


def test_fetch_quotes_batch_empty_is_empty():
    assert quotes.fetch_quotes_batch([]) == {}


def test_fetch_quotes_batch_honors_budget(monkeypatch):
    # A hung symbol must NOT make the call block past the budget — shutdown(wait=False).
    release = threading.Event()

    def fake(sym, **kw):
        if sym == "SLOW":
            release.wait(timeout=5)  # simulate a provider that hangs
            return None
        return RawQuote(10.0, 9.0, "USD", 1)

    monkeypatch.setattr(quotes, "fetch_raw_quote", fake)
    t0 = time.monotonic()
    out = quotes.fetch_quotes_batch(["FAST", "SLOW"], budget=0.3)
    elapsed = time.monotonic() - t0
    release.set()  # let the lingering worker finish

    assert elapsed < 2.0  # returned at ~budget, did not block ~5s on the hung future
    assert out["FAST"] == RawQuote(10.0, 9.0, "USD", 1)
    assert out["SLOW"] is None  # not finished within budget -> unavailable
