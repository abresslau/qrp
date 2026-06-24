"""Custom-list universe provider (Story U1.7) — the first concrete UniverseProvider.

Emits a ``join`` membership-change per identifier in a user-supplied list. The
concrete instance here loads the seed universe (``benchmark/seed_universe.toml``)
and emits one token per name — ``ticker:<T>@<MIC>`` (preferred) or ``isin:<ISIN>``
— all at the universe's inception date (a custom list has no membership history,
so every member joins at the same start). Self-registers under ``custom_list``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from universe.registry import CUSTOM_LIST, JOIN, MembershipChange, register_provider
from universe.seeds import Seed, load_seed_universe

SOURCE = "custom_list"


def member_token(sec: Seed) -> str:
    """The resolution token for a seed entry: ticker:T@MIC preferred, else isin:X.

    A seed with neither (ticker+mic) nor isin is a hard error — falling through
    would mint a poison ``isin:None`` token into the append-only log.
    """
    if sec.ticker and sec.mic:
        return f"ticker:{sec.ticker}@{sec.mic}"
    if sec.isin:
        return f"isin:{sec.isin}"
    raise ValueError(
        f"seed entry {sec!r} needs ticker+mic or isin to form a resolution token"
    )


class CustomListProvider:
    """Yields a ``join`` per identifier in the list, at the inception date."""

    kind = CUSTOM_LIST

    def __init__(self, path: str | None = None, source: str = SOURCE, **_: object) -> None:
        self._path = path
        self._source = source

    def members(self, start: date, end: date) -> Iterator[MembershipChange]:
        # A custom list has no history: every member joins at the inception (start).
        for sec in load_seed_universe(self._path):
            yield MembershipChange(member_token(sec), JOIN, start, self._source)


register_provider(CUSTOM_LIST, CustomListProvider)
