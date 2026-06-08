"""Index universe provider with per-index source preference + fallback — Story U2.4.

A single provider registered under the ``index`` kind. It does not itself know
how to read any index — it selects between the archetype sources (FMP, ETF,
Wikipedia) by an **ordered preference**, trying each in turn and **falling back to
the next on failure**, so the layer always uses the best available source and
degrades rather than breaks. Which source produced an event is recorded in the
event's ``source`` field (provenance). If every configured source fails, the
provider raises loudly (per-index) — it never silently records "no members".
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sym.universe.providers import (  # noqa: F401  (self-register)
    b3,
    etf_holdings,
    fmp,
    wikipedia,
)
from sym.universe.providers.index_source import (
    ARCHETYPE_ETF,
    ARCHETYPE_FMP,
    ARCHETYPE_WIKIPEDIA,
    IndexSource,
    IndexSourceError,
    UnknownArchetypeError,
    get_index_source,
)
from sym.universe.registry import INDEX, MembershipChange, register_provider

# API-first default (NFR4); a universe overrides via its source_pref. Wikipedia
# is last because it is the scraped fallback/corroboration source.
DEFAULT_SOURCE_PREF: tuple[str, ...] = (ARCHETYPE_FMP, ARCHETYPE_ETF, ARCHETYPE_WIKIPEDIA)


class IndexProvider:
    """Resolve an index's membership via an ordered source preference with fallback."""

    kind = INDEX

    def __init__(
        self,
        index: str | None = None,
        source_pref: Iterable[str] | None = None,
        *,
        sources: dict[str, IndexSource] | None = None,
        **source_config: object,
    ) -> None:
        if not index:
            raise IndexSourceError("an index universe requires config.index (the index key)")
        self._index = index
        self._pref = tuple(source_pref) if source_pref else DEFAULT_SOURCE_PREF
        self._prebuilt = sources or {}
        self._source_config = source_config

    def _source(self, archetype: str) -> IndexSource:
        if archetype in self._prebuilt:
            return self._prebuilt[archetype]
        cfg = self._source_config.get(archetype) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        return get_index_source(archetype, **cfg)

    def members(self, start: date, end: date) -> list[MembershipChange]:
        attempts: list[str] = []
        for archetype in self._pref:
            try:
                changes = list(self._source(archetype).fetch(self._index, start, end))
            except (IndexSourceError, UnknownArchetypeError) as exc:
                attempts.append(f"{archetype}: {exc}")
                continue
            if not changes:
                attempts.append(f"{archetype}: produced no changes")
                continue
            return changes
        raise IndexSourceError(
            f"all sources failed for index {self._index!r} "
            f"(tried {', '.join(self._pref)}): {' | '.join(attempts)}"
        )


def _build_from_config(**config: object) -> IndexProvider:
    index = config.pop("index", None)
    source_pref = config.pop("source_pref", None)
    return IndexProvider(index, source_pref, **config)  # type: ignore[arg-type]


register_provider(INDEX, _build_from_config)
