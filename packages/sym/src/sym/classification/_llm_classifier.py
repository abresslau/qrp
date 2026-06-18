"""Shared scaffold for web-grounded LLM classification sources (Perplexity, Google Gemini).

Both ask an LLM "what GICS sector is this security?" and map the free-text answer onto one
of the 11 GICS sectors. They are LOW-TRUST (an LLM's guess, like the existing ``llm``
artifact source) and KEYED — dormant without their API key. This base owns the per-symbol
loop, GICS-answer validation (an off-taxonomy / hallucinated answer is recorded unmapped,
never written as a sector), per-symbol error isolation, and a consecutive-failure
circuit-breaker (a key/quota outage must fail fast, not walk all N names). Each concrete
source supplies a tiny HTTP client and its ``source`` tag.

Stdlib ``urllib`` only — no new dependency. NOT live-verified in-env (no keys); shipped
production-ready + unit-tested against a fake client (the FMP precedent).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sym.classification.gics import GicsClassification, SecurityIdentity
from sym.classification.llm import GICS_SECTORS

MAX_CONSECUTIVE_ERRORS = 5

# Longest-first so "Consumer Discretionary" matches before a bare "Consumer ...".
_SECTORS_BY_LEN = sorted(GICS_SECTORS, key=len, reverse=True)


def map_answer_to_sector(text: str | None) -> str | None:
    """Find a canonical GICS sector named anywhere in the model's answer, or None."""
    if not text:
        return None
    low = text.strip().lower()
    for sector in _SECTORS_BY_LEN:
        if sector.lower() in low:
            return sector
    return None


class LlmClassifierError(RuntimeError):
    """The LLM endpoint was unreachable or returned an unusable response."""


class LlmClassifierClient(Protocol):
    """One lookup: the model's raw sector answer for a security (injectable for testing)."""

    def sector_answer(self, ticker: str, mic: str | None, name: str | None) -> str | None: ...


class LlmGicsSourceBase:
    """GICS *sector* opinions from an LLM classifier client.

    Implements the :class:`sym.classification.gics.GicsSource` protocol. Concrete subclasses
    set ``source`` and pass a :class:`LlmClassifierClient`. Side-channels (reset per
    ``fetch``): ``last_unmapped`` (ticker -> raw answer outside the 11 sectors),
    ``last_unmatched`` (no answer), ``last_errors`` (ticker -> message), ``last_short_circuited``.
    """

    source = "llm-base"

    def __init__(self, client: LlmClassifierClient) -> None:
        self._client = client
        self.last_unmapped: dict[str, str] = {}
        self.last_unmatched: list[str] = []
        self.last_errors: dict[str, str] = {}
        self.last_short_circuited: list[str] = []

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        self.last_unmapped = {}
        self.last_unmatched = []
        self.last_errors = {}
        self.last_short_circuited = []

        found: dict[str, GicsClassification] = {}
        securities = list(securities)
        consecutive_errors = 0
        for i, s in enumerate(securities):
            if not s.ticker:
                continue
            try:
                answer = self._client.sector_answer(s.ticker, s.mic, None)
            except Exception as exc:  # noqa: BLE001 — per-symbol isolation
                self.last_errors[s.ticker.upper()] = f"{type(exc).__name__}: {exc}"
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    for rest in securities[i + 1 :]:
                        if rest.ticker:
                            self.last_short_circuited.append(rest.ticker.upper())
                    break
                continue
            consecutive_errors = 0
            if not answer:
                self.last_unmatched.append(s.ticker.upper())
                continue
            sector = map_answer_to_sector(answer)
            if sector is None:
                self.last_unmapped[s.ticker.upper()] = answer.strip()[:80]
                continue
            found[s.composite_figi] = GicsClassification(
                composite_figi=s.composite_figi,
                sector_name=sector,
                industry_group_name=None,
                industry_name=None,
                source=self.source,
            )
        return found
