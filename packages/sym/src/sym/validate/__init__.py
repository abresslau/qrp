"""Cross-layer validation & reconciliation (Epic V).

A standing suite of integrity invariants spanning identity ↔ symbology ↔ prices ↔
calendar ↔ universe ↔ returns. Each check is a pure function over fetched rows
(DB-free testable) plus a thin live query; findings are classified
``pass``/``warn``/``fail`` (expected gaps are warnings with a reason), never a
silent boolean. ``sym validate`` (Story V7) runs them all.
"""

from __future__ import annotations
