"""FX-rate layer (Epic FX) — USD-centered star storage + derived conversion.

Observed rates live in ``fx_rate`` (USD-base preferred, immutable, source-tagged);
inverses, crosses, the dense weekday series, and conversion are all *derived*
(``v_fx`` / ``v_fx_daily`` / ``convert``), never stored. See ``epics-fx.md``.
"""

from __future__ import annotations

from fx.model import USD, canonical_pair, is_canonical_direction

__all__ = ["USD", "canonical_pair", "is_canonical_direction"]
