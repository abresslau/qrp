"""Seed universe loading (Story 1.5).

Parses ``benchmark/seed_universe.toml`` — the adversarial MVP name set that
doubles as the corporate-action fixture set and the SM-6 benchmark set — into
typed records, and turns each record into the resolution inputs the identity
layer (Story 1.6, ``identity/figi.py``) feeds to OpenFIGI.

A *resolution input* is the minimal identifier OpenFIGI can resolve to a
CompositeFIGI: either a ticker scoped to a listing (``ticker`` + ``mic``) or an
exchange-independent ``isin``. The TOML schema and the per-category adversarial
rationale are documented inline in the file itself.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# The symbology types this seed file expresses. These are the subset of
# security_symbology.symbol_type values (see migrations/deploy/security_symbology.sql)
# that an OpenFIGI lookup can be keyed on.
TICKER = "ticker"
ISIN = "isin"


class SeedUniverseError(ValueError):
    """Raised when the seed universe file is malformed or an entry is unresolvable."""


@dataclass(frozen=True)
class ResolutionInput:
    """A single identifier handed to OpenFIGI to resolve a CompositeFIGI.

    ``mic`` is required for ``ticker`` (a bare ticker is ambiguous across
    exchanges) and unused for ``isin``. ``exch_code`` is the OpenFIGI/Bloomberg
    exchange code for the listing (e.g. ``US``/``LN``), filled in from the
    exchange reference table at resolution time — it, not ``mic``, is what
    OpenFIGI disambiguates a ticker by.
    """

    symbol_type: str
    symbol_value: str
    mic: str | None = None
    exch_code: str | None = None

    def __post_init__(self) -> None:
        if self.symbol_type not in (TICKER, ISIN):
            raise SeedUniverseError(
                f"unsupported symbol_type {self.symbol_type!r} (expected {TICKER!r} or {ISIN!r})"
            )
        if not self.symbol_value:
            raise SeedUniverseError(f"empty symbol_value for {self.symbol_type!r}")
        if self.symbol_type == TICKER and not self.mic:
            raise SeedUniverseError(f"ticker {self.symbol_value!r} requires a mic")


@dataclass(frozen=True)
class SeedSecurity:
    """One ``[[security]]`` entry from the seed universe file."""

    name: str
    category: str
    ticker: str | None
    mic: str | None
    isin: str | None
    note: str | None

    def resolution_inputs(self) -> list[ResolutionInput]:
        """Every valid OpenFIGI resolution input this entry expresses.

        A ticker is only emitted when paired with a mic; the isin is emitted on
        its own. Order is ticker-then-isin so the listing-scoped lookup (more
        precise) is tried first by callers that take the head.
        """
        inputs: list[ResolutionInput] = []
        if self.ticker and self.mic:
            inputs.append(ResolutionInput(TICKER, self.ticker, self.mic))
        if self.isin:
            inputs.append(ResolutionInput(ISIN, self.isin))
        return inputs


def default_seed_path() -> Path:
    """Locate ``benchmark/seed_universe.toml`` by walking up to the repo root."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "benchmark" / "seed_universe.toml"
        if candidate.is_file():
            return candidate
    raise SeedUniverseError("benchmark/seed_universe.toml not found above this module")


def load_seed_universe(path: Path | str | None = None) -> list[SeedSecurity]:
    """Parse the seed universe file into ``SeedSecurity`` records.

    Each entry is validated to yield at least one resolution input (it must
    carry ticker+mic and/or an isin); a name that resolves to nothing is a
    defect in the file, not a runtime condition, so we fail loudly here.
    """
    seed_path = Path(path) if path is not None else default_seed_path()
    if not seed_path.is_file():
        raise SeedUniverseError(f"seed universe file not found: {seed_path}")
    with seed_path.open("rb") as fh:
        data = tomllib.load(fh)

    raw_entries = data.get("security", [])
    if not raw_entries:
        raise SeedUniverseError(f"no [[security]] entries in {seed_path}")

    securities: list[SeedSecurity] = []
    for index, entry in enumerate(raw_entries):
        name = entry.get("name")
        category = entry.get("category")
        if not name:
            raise SeedUniverseError(f"entry #{index} is missing required 'name'")
        if not category:
            raise SeedUniverseError(f"entry {name!r} is missing required 'category'")

        security = SeedSecurity(
            name=name,
            category=category,
            ticker=entry.get("ticker"),
            mic=entry.get("mic"),
            isin=entry.get("isin"),
            note=entry.get("note"),
        )
        if not security.resolution_inputs():
            raise SeedUniverseError(
                f"entry {name!r} yields no resolution input (needs ticker+mic and/or isin)"
            )
        securities.append(security)

    return securities
