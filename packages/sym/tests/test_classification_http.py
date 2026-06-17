"""RequestThrottle (shared classification HTTP helper) — no real sleeping."""

from __future__ import annotations

import sym.classification._http as http_mod
from sym.classification._http import RequestThrottle


def test_throttle_disabled_never_sleeps(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: slept.append(s))
    t = RequestThrottle(0)
    t.wait()
    t.wait()
    assert slept == []  # min_interval <= 0 disables it


def test_throttle_spaces_back_to_back_requests(monkeypatch):
    clock = {"t": 100.0}
    slept: list[float] = []
    monkeypatch.setattr(http_mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: slept.append(s))

    t = RequestThrottle(0.5)
    t.wait()  # first call: last_request=0.0 → huge elapsed → no sleep
    assert slept == []
    t.wait()  # immediate second call (clock unchanged) → must sleep the full interval
    assert len(slept) == 1
    assert abs(slept[0] - 0.5) < 1e-9
