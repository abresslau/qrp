"""Shared HTTP helpers for the classification sources.

Keeps the rate-limit politeness in one place: the sec_sic and yahoo_profile live
clients both issue one sequential request per name, so each holds a
:class:`RequestThrottle` rather than re-implementing the same ``time.monotonic``
spacing (a duplication the classification code review flagged).
"""

from __future__ import annotations

import time


class RequestThrottle:
    """Spaces sequential requests at least ``min_interval`` seconds apart.

    ``min_interval <= 0`` disables it (a no-op ``wait``). Not thread-safe — the
    classification sources fetch sequentially, which is the whole point of the
    spacing (politeness under a provider's per-second ceiling, e.g. SEC's 10/s).
    """

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._last_request = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()
