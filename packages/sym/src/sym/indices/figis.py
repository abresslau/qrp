"""Canonical index FIGIs — a committed static map (Index epic, B6).

FIGI is an **optional** cross-reference for index instruments; the spine is
``sym_id`` + the Yahoo/MSCI xref. We attach the *canonical* OpenFIGI identifier
(Bloomberg ``<TICKER> Index``, ``securityType2='Index'``) where it can be pinned
unambiguously, so an index here shares one id with other systems.

Why a static map and not a live OpenFIGI scrape: **reconstructability** — the
repo must be able to rebuild every byte deterministically, and the unkeyed
OpenFIGI *search* endpoint is both rate-limited (429 storms) and noisy (a name
returns ~100 look-alikes; ``SPX``/``UKX`` canonicals sit beyond the first page).
So each FIGI below was verified once by exact-ticker match and is now frozen
here. The seeder attaches them via ``instrument_xref(source='figi')``.

Coverage is partial **by design**: only entries that pinned cleanly are listed.
The rest (S&P family, FTSE 100, Nikkei, Dow, SMI, EURO STOXX 50, …) need a keyed
OpenFIGI account or a manually-verified id — add them here as ``yahoo_symbol:
figi`` and re-run ``sym indices --attach-figis``; nothing else changes.
"""

from __future__ import annotations

import psycopg

from sym.identity.instrument import SRC_FIGI, SRC_YAHOO, add_xref, sym_id_for

# yahoo_symbol -> canonical OpenFIGI (share class FIGI of the "<TICKER> Index"
# Bloomberg security). Verified by exact-ticker match against OpenFIGI /v3/search
# (securityType2='Index'); see module docstring for why these and not others.
INDEX_FIGIS: dict[str, str] = {
    "^GDAXI": "BBG000HY4HW9",  # DAX INDEX
    "^AEX": "BBG000KHVFM7",  # AEX-Index
    "^FCHI": "BBG000HY2S75",  # CAC 40 INDEX
    "^IBEX": "BBG000JD3ZR0",  # IBEX 35 INDEX
}


def attach_index_figis(conn: psycopg.Connection) -> tuple[int, int]:
    """Attach canonical FIGIs from the static map to their index instruments.

    Resolves each entry's instrument by its Yahoo xref and attaches the ``figi``
    xref (idempotent). Returns ``(attached, missing)`` where *missing* counts
    map entries whose index instrument doesn't exist yet (load levels first).
    """
    conn.autocommit = True
    attached = missing = 0
    for yahoo_symbol, figi in INDEX_FIGIS.items():
        sym_id = sym_id_for(conn, SRC_YAHOO, yahoo_symbol)
        if sym_id is None:
            missing += 1
            continue
        add_xref(conn, sym_id, SRC_FIGI, figi)
        attached += 1
    return attached, missing
