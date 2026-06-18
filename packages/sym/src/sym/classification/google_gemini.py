"""Google Gemini → GICS-sector classification (multi-source matrix, keyed/dormant).

A web-grounded LLM opinion source via Google's Gemini ``generateContent`` API. KEYED —
gated on ``GOOGLE_API_KEY`` / ``GEMINI_API_KEY``; dormant without one (probed 2026-06-18:
``generativelanguage.googleapis.com`` reachable, HTTP 403 without a key). This is Google's
**LLM**, NOT a structured sector feed — Google publishes no GICS feed, and Google-Finance /
search-UI scraping is brittle + ToS-fraught and out of scope. Low-trust; the answer is
validated against the 11 GICS sectors by the shared base. Stdlib ``urllib`` only. NOT
live-verified in-env (no key) — built + unit-tested against a fake client (FMP precedent).
"""

from __future__ import annotations

import json
import os
import urllib.request

from sym.classification._http import RequestThrottle
from sym.classification._llm_classifier import LlmClassifierError, LlmGicsSourceBase

_MODEL = "gemini-2.0-flash"
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
_HTTP_TIMEOUT = 30

_PROMPT = (
    "Which single GICS sector best classifies the company with ticker {ticker}"
    "{venue}? Answer with exactly one of: Energy, Materials, Industrials, "
    "Consumer Discretionary, Consumer Staples, Health Care, Financials, "
    "Information Technology, Communication Services, Utilities, Real Estate. "
    "Reply with only the sector name."
)


def google_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))


class HttpGeminiClient:
    """Live Gemini client (stdlib ``urllib``); reads ``GOOGLE_API_KEY``/``GEMINI_API_KEY``."""

    def __init__(self, min_interval: float = 0.5) -> None:
        self._throttle = RequestThrottle(min_interval)
        self._key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""

    def sector_answer(self, ticker: str, mic: str | None, name: str | None) -> str | None:
        if not self._key:
            raise LlmClassifierError("GOOGLE_API_KEY / GEMINI_API_KEY not set")
        venue = f" listed on MIC {mic}" if mic else ""
        body = json.dumps(
            {"contents": [{"parts": [{"text": _PROMPT.format(ticker=ticker, venue=venue)}]}]}
        ).encode()
        self._throttle.wait()
        req = urllib.request.Request(
            _URL.format(model=_MODEL, key=self._key),
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise LlmClassifierError(f"Gemini request failed for {ticker}: {exc}") from exc
        try:
            return payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return None


class GoogleGeminiGicsSource(LlmGicsSourceBase):
    source = "google"

    def __init__(self, client=None) -> None:
        super().__init__(client or HttpGeminiClient())
