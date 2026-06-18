"""Perplexity Sonar → GICS-sector classification (multi-source matrix, keyed/dormant).

A web-grounded LLM opinion source via the Perplexity Sonar ``chat/completions`` API
(OpenAI-compatible). KEYED — gated on ``PERPLEXITY_API_KEY``; dormant without it (probed
2026-06-18: ``api.perplexity.ai`` reachable, HTTP 401 without a key). Low-trust (an LLM's
guess); the answer is validated against the 11 GICS sectors by the shared base. Stdlib
``urllib`` only. NOT live-verified in-env (no key) — built + unit-tested against a fake
client, the FMP precedent.

Chosen over scraping the Perplexity UI: scraping is brittle, bot-blocked, ToS-fraught, and
gives the same LLM signal this API call does, cleanly.
"""

from __future__ import annotations

import json
import os
import urllib.request

from sym.classification._http import RequestThrottle
from sym.classification._llm_classifier import (
    LlmClassifierError,
    LlmGicsSourceBase,
)

_URL = "https://api.perplexity.ai/chat/completions"
_MODEL = "sonar"
_HTTP_TIMEOUT = 30

_PROMPT = (
    "Which single GICS sector best classifies the company with ticker {ticker}"
    "{venue}? Answer with exactly one of: Energy, Materials, Industrials, "
    "Consumer Discretionary, Consumer Staples, Health Care, Financials, "
    "Information Technology, Communication Services, Utilities, Real Estate. "
    "Reply with only the sector name."
)


def perplexity_enabled() -> bool:
    return bool(os.environ.get("PERPLEXITY_API_KEY"))


class HttpPerplexityClient:
    """Live Sonar client (stdlib ``urllib``); reads ``PERPLEXITY_API_KEY`` from the env."""

    def __init__(self, min_interval: float = 0.5) -> None:
        self._throttle = RequestThrottle(min_interval)
        self._key = os.environ.get("PERPLEXITY_API_KEY", "")

    def sector_answer(self, ticker: str, mic: str | None, name: str | None) -> str | None:
        if not self._key:
            raise LlmClassifierError("PERPLEXITY_API_KEY not set")
        venue = f" listed on MIC {mic}" if mic else ""
        body = json.dumps(
            {
                "model": _MODEL,
                "messages": [
                    {"role": "user", "content": _PROMPT.format(ticker=ticker, venue=venue)}
                ],
                "temperature": 0,
            }
        ).encode()
        self._throttle.wait()
        req = urllib.request.Request(
            _URL,
            data=body,
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise LlmClassifierError(f"Perplexity request failed for {ticker}: {exc}") from exc
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None


class PerplexityGicsSource(LlmGicsSourceBase):
    source = "perplexity"

    def __init__(self, client=None) -> None:
        super().__init__(client or HttpPerplexityClient())
