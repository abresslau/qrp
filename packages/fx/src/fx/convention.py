"""FX market quoting convention — which currency is the BASE in a pair.

The market quotes each pair in a conventional direction set by a currency-seniority ranking: the
higher-precedence currency is the base (the "1 unit of"). So EUR/USD, GBP/USD, AUD/USD, NZD/USD
(those outrank USD), but USD/JPY, USD/CAD, USD/CHF, USD/CNY, USD/BRL (USD outranks those). Lower
``QUOTE_RANK`` = higher precedence = base.

This is reference/convention data (not per-instance state), so it lives as config here rather than a
column on the `currency` table. Add or re-rank a currency in one place; an unknown currency sinks to
the lowest precedence (always the quote) deterministically.
"""

from __future__ import annotations

# Standard major-currency seniority (lower = base). Gaps left for inserting others later.
QUOTE_RANK: dict[str, int] = {
    "EUR": 10,
    "GBP": 20,
    "AUD": 30,
    "NZD": 40,
    "USD": 50,
    "CAD": 60,
    "CHF": 70,
    "NOK": 72,  # Scandies sit just below CHF (USD/NOK, EUR/NOK quote them)
    "SEK": 74,
    "DKK": 76,
    "CNY": 80,
    "HKD": 82,  # EM / minors below the Scandies (all quoted USD/XXX, EUR/XXX)
    "SGD": 84,
    "MXN": 86,
    "BRL": 90,
    "JPY": 100,
}
_UNRANKED = 10_000  # an unknown currency is always the quote (lowest precedence)


def quote_rank(currency: str) -> int:
    """Quoting precedence for a currency (lower = base); unknown → lowest precedence."""
    return QUOTE_RANK.get((currency or "").upper(), _UNRANKED)


def conventional_pair(a: str, b: str) -> tuple[str, str]:
    """The conventional ``(base, quote)`` for an unordered pair {a, b} — the higher-precedence
    (lower-rank) currency is the base. Ties / two-unknowns break alphabetically so the result is
    deterministic. e.g. GBP is the base in GBP/USD; USD is the base in USD/BRL."""
    a, b = a.upper(), b.upper()
    ra, rb = quote_rank(a), quote_rank(b)
    if ra < rb or (ra == rb and a <= b):
        return a, b
    return b, a
