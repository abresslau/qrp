"""Seed-universe TOML loader for the custom_list provider (universe-local; no sym import).

Parses ``benchmark/seed_universe.toml`` (the adversarial MVP name set) into lightweight ``Seed``
records carrying just what the custom_list provider needs to mint a resolution token (ticker+mic or
isin). This is a minimal, faithful copy of what ``sym.identity.universe.load_seed_universe`` did
— kept here so the universe package stays sym-import-free. The token→FIGI resolution itself still
happens in sym (the injected Resolver); this only reads the membership name list.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class SeedUniverseError(Exception):
    """Malformed or missing seed-universe file."""


@dataclass(frozen=True)
class Seed:
    name: str
    category: str
    ticker: str | None = None
    mic: str | None = None
    isin: str | None = None

    def has_resolution_input(self) -> bool:
        return bool((self.ticker and self.mic) or self.isin)


def default_seed_path() -> Path:
    """Locate ``benchmark/seed_universe.toml`` by walking up from this module."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "benchmark" / "seed_universe.toml"
        if candidate.is_file():
            return candidate
    raise SeedUniverseError("benchmark/seed_universe.toml not found above this module")


def load_seed_universe(path: Path | str | None = None) -> list[Seed]:
    """Parse the seed universe file into ``Seed`` records (each must yield a resolution input)."""
    seed_path = Path(path) if path is not None else default_seed_path()
    if not seed_path.is_file():
        raise SeedUniverseError(f"seed universe file not found: {seed_path}")
    with seed_path.open("rb") as fh:
        data = tomllib.load(fh)
    raw_entries = data.get("security", [])
    if not raw_entries:
        raise SeedUniverseError(f"no [[security]] entries in {seed_path}")
    seeds: list[Seed] = []
    for index, entry in enumerate(raw_entries):
        name = entry.get("name")
        category = entry.get("category")
        if not name:
            raise SeedUniverseError(f"entry #{index} is missing required 'name'")
        if not category:
            raise SeedUniverseError(f"entry {name!r} is missing required 'category'")
        seed = Seed(
            name=name, category=category,
            ticker=entry.get("ticker"), mic=entry.get("mic"), isin=entry.get("isin"),
        )
        if not seed.has_resolution_input():
            raise SeedUniverseError(
                f"entry {name!r} yields no resolution input (needs ticker+mic and/or isin)"
            )
        seeds.append(seed)
    return seeds
