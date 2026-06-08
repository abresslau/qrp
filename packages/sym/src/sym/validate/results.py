"""Shared result types for the validation suite (Epic V).

Every check returns a :class:`CheckResult` — a name, a tri-state status
(``pass``/``warn``/``fail``), counts, and a bounded sample of offending items.
A ``fail`` is a hard failure (non-zero exit / CI gate); a ``warn`` is an expected
gap with a reason (e.g. a delisted leaver with no vendor data). Pure, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

PASS = "pass"
WARN = "warn"
FAIL = "fail"
_ORDER = {PASS: 0, WARN: 1, FAIL: 2}

SAMPLE_LIMIT = 20


def status_for(failures: int, warnings: int) -> str:
    """The status implied by failure/warning counts (fail > warn > pass)."""
    if failures > 0:
        return FAIL
    if warnings > 0:
        return WARN
    return PASS


def worst(statuses: Iterable[str]) -> str:
    """The most severe status in ``statuses`` (pass if empty)."""
    return max(statuses, key=lambda s: _ORDER.get(s, 0), default=PASS)


@dataclass
class CheckResult:
    """The outcome of one validation check."""

    name: str
    status: str = PASS
    checked: int = 0
    failures: int = 0
    warnings: int = 0
    samples: list[str] = field(default_factory=list)
    detail: str | None = None

    @property
    def ok(self) -> bool:
        """True unless this is a hard ``fail``."""
        return self.status != FAIL

    @classmethod
    def from_items(
        cls,
        name: str,
        *,
        checked: int,
        failures: Sequence[str] = (),
        warnings: Sequence[str] = (),
        detail: str | None = None,
    ) -> CheckResult:
        """Build a result from offending-item lists (counts + bounded samples)."""
        status = status_for(len(failures), len(warnings))
        samples = [f"FAIL {s}" for s in failures[:SAMPLE_LIMIT]]
        if len(samples) < SAMPLE_LIMIT:
            samples += [f"WARN {s}" for s in warnings[: SAMPLE_LIMIT - len(samples)]]
        return cls(
            name=name,
            status=status,
            checked=checked,
            failures=len(failures),
            warnings=len(warnings),
            samples=samples,
            detail=detail,
        )
