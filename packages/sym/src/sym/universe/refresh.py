"""Universe refresh orchestration (Story U1.7).

`refresh_universe` makes a universe live end-to-end: run its provider to discover
membership changes → append them to the event log → resolve members → rebuild the
point-in-time projection. One command ties the U1.1–U1.6 spine together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

from sym.universe.events import append_changes
from sym.universe.projection import rebuild_projection
from sym.universe.registry import (
    CRITERIA,
    CUSTOM_LIST,
    LEAVE,
    UnknownUniverseError,
    get_provider,
)
from sym.universe.resolution import (
    make_local_resolve_fn,
    make_openfigi_resolve_fn,
    resolve_universe_members,
)

# Index universes pull full history from this floor (constituent "date added"
# values reach back to the 1970s); the honest queryable boundary is set separately
# from the earliest dated leave (the survivorship floor).
DEFAULT_HISTORY_FLOOR = date(1990, 1, 1)


@dataclass
class RefreshSummary:
    appended: int = 0
    resolved: int = 0
    unresolved: int = 0
    figis: int = 0
    intervals: int = 0


def refresh_universe(
    conn: psycopg.Connection,
    universe_id: str,
    *,
    client: object | None = None,
    today: date | None = None,
) -> RefreshSummary:
    """Provider → append → resolve → project, for one universe.

    Custom-list universes resolve against existing securities (no network);
    other kinds resolve via OpenFIGI (a default client is built if not supplied).

    ``pit_valid_from`` (the honesty boundary) is set on first refresh if unset and
    not pinned at ``add`` time. A **custom list** has no history → its inception is
    today. An **index** pulls full history from a far-past floor; its honest
    boundary is the *earliest dated leave* it can see (before that, the source
    cannot tell us who left, so membership would be survivorship-biased — we refuse
    rather than back-project). When an index has no dated leaves yet, the boundary
    is today (build-forward), like a current snapshot.
    """
    import sym.universe.providers  # noqa: F401  (ensure providers self-register)

    # Durable per-step commits (idempotent appends/resolutions + an atomic
    # projection rebuild) so a long live index refresh is resumable, not
    # all-or-nothing — mirrors the ingestion pipeline's autocommit discipline.
    conn.autocommit = True
    today = today or date.today()
    row = conn.execute(
        "SELECT kind, config, pit_valid_from, source_pref FROM universe WHERE universe_id = %s",
        (universe_id,),
    ).fetchone()
    if row is None:
        raise UnknownUniverseError(f"unknown universe {universe_id!r}")
    kind, config, pit, source_pref = row
    config = dict(config or {})
    # The dedicated source_pref column (U1.1) feeds the provider's ordered
    # archetype preference (U2.4) without the caller having to duplicate it in config.
    provider_config = dict(config)
    if source_pref is not None and "source_pref" not in provider_config:
        provider_config["source_pref"] = source_pref

    # Fetch window: a custom list "starts" at its inception (set on first refresh);
    # an index/criteria universe pulls full history from a configurable floor.
    if kind == CUSTOM_LIST:
        if pit is None:
            pit = today
            conn.execute(
                "UPDATE universe SET pit_valid_from = %s WHERE universe_id = %s", (pit, universe_id)
            )
        fetch_start = pit
    else:
        floor = config.get("history_floor")
        fetch_start = date.fromisoformat(floor) if floor else DEFAULT_HISTORY_FLOOR

    # A criteria provider evaluates a rule against the DB, so it needs the connection.
    if kind == CRITERIA:
        provider_config["conn"] = conn
    provider = get_provider(kind, **provider_config)
    changes = list(provider.members(fetch_start, today))
    appended = append_changes(conn, universe_id, changes)

    # Derive the index honesty boundary from the data on first refresh (unless
    # pinned at add time): the earliest dated leave is the survivorship floor.
    if kind != CUSTOM_LIST and pit is None:
        leave_dates = [c.effective_date for c in changes if c.change == LEAVE]
        pit = min(leave_dates) if leave_dates else today
        conn.execute(
            "UPDATE universe SET pit_valid_from = %s WHERE universe_id = %s", (pit, universe_id)
        )

    if kind in (CUSTOM_LIST, CRITERIA):
        # Both resolve against existing securities (custom list reuses the master;
        # criteria screens are computed over securities already present), no network.
        resolve_fn = make_local_resolve_fn(conn)
    else:
        if client is None:
            import os

            from sym.identity.figi import HttpOpenFigiClient

            # More retries for a large live universe resolution (throttled client
            # rides out the public rate limit; chunked resolution stays resumable).
            client = HttpOpenFigiClient(
                api_key=os.environ.get("OPENFIGI_API_KEY"), max_retries=6
            )
        resolve_fn = make_openfigi_resolve_fn(conn, client)

    res = resolve_universe_members(conn, universe_id, resolve_fn)
    proj = rebuild_projection(conn, universe_id)
    return RefreshSummary(
        appended=appended,
        resolved=res.resolved,
        unresolved=res.unresolved,
        figis=proj.figis,
        intervals=proj.intervals,
    )
