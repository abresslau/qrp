"""Membership identifier tokens + snapshot set-diff (Epic U2/U3).

Two pure helpers shared by the snapshot archetypes (ETF holdings, Wikipedia
current table) and the daily monitor (U3):

* token builders — turn a ticker+MIC or ISIN into the resolver token shape
  (``ticker:T@MIC`` / ``isin:XXX``) the resolution bridge (U1.3) parses, with a
  normalisation step so format drift (``BRK.B`` vs ``BRK-B``) can't fake a
  leave+rejoin;
* :func:`diff_identifier_sets` — diff two membership snapshots on the identifier
  **set** (never weights) into join/leave change-events.
"""

from __future__ import annotations

from datetime import date

from universe.registry import JOIN, LEAVE, POLL_BOUNDED, MembershipChange


def normalize_ticker(ticker: str) -> str:
    """Canonicalise a ticker so format drift can't fake a membership change.

    Uppercases, trims, and unifies share-class separators to ``.`` (``BRK-B`` and
    ``BRK.B`` and ``BRK B`` all normalise to ``BRK.B``). The OpenFIGI resolver
    later maps ``.`` to ``/`` for Bloomberg convention — this is only about a
    *stable* identifier for diffing and dedupe.
    """
    t = ticker.strip().upper()
    for sep in ("-", " "):
        t = t.replace(sep, ".")
    return t


def ticker_token(ticker: str, mic: str) -> str:
    """The resolver token for a listed ticker (normalised)."""
    return f"ticker:{normalize_ticker(ticker)}@{mic.strip().upper()}"


def isin_token(isin: str) -> str:
    """The resolver token for an ISIN."""
    return f"isin:{isin.strip().upper()}"


def figi_token(composite_figi: str) -> str:
    """The resolver token for a CompositeFIGI (criteria screens resolve directly)."""
    return f"figi:{composite_figi.strip().upper()}"


def diff_identifier_sets(
    previous: set[str],
    current: set[str],
    effective_date: date,
    source: str,
    *,
    precision: str = POLL_BOUNDED,
) -> list[MembershipChange]:
    """Change-events that turn snapshot ``previous`` into ``current``.

    A token in ``current`` but not ``previous`` is a ``join``; one in
    ``previous`` but not ``current`` is a ``leave`` — both effective on
    ``effective_date``. Diffing the *set* means a constituent whose weight moved
    but membership didn't is correctly NOT a change. Precision defaults to
    ``poll_bounded`` (a snapshot only bounds the date to the polling interval).
    """
    changes = [
        MembershipChange(tok, JOIN, effective_date, source, precision)
        for tok in sorted(current - previous)
    ]
    changes += [
        MembershipChange(tok, LEAVE, effective_date, source, precision)
        for tok in sorted(previous - current)
    ]
    return changes
