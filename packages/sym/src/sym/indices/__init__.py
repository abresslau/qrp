"""Index levels + returns (Index epic).

Stores index level series (S&P 500, S&P 500 TR, MSCI World, IBOVESPA, …)
under the universal ``sym_id`` identity, level-only and variant-tagged
(PR/NTR/GTR), so universe/security returns can be compared and alpha computed.
"""

from __future__ import annotations
