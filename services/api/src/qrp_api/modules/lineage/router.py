"""/api/lineage — surfaces the Dagster lineage layer (packages/lineage) in the QRP console.

Gateway-resident (like sym) so the `lineage` package stays a pure Dagster code location. The
`lineage.*` imports (which pull in dagster) are **lazy** — done inside handlers — so they don't
burden API startup unless a lineage endpoint is actually hit. The rich interactive graph lives in
the Dagster UI (`dagster_url`); this exposes the table-level edges + the field-flow for the console.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/lineage", tags=["lineage"])

# Where the OSS Dagster UI serves (the console links out for the interactive graph).
DAGSTER_URL = "http://127.0.0.1:3333"


class LineageEdge(BaseModel):
    source: str
    target: str
    basis: str
    source_group: str | None = None
    target_group: str | None = None


class LineageStats(BaseModel):
    assets: int
    edges: int
    by_basis: dict[str, int]


class LineageGraph(BaseModel):
    edges: list[LineageEdge]
    stats: LineageStats
    dagster_url: str


class FieldFlow(BaseModel):
    key: str
    mermaid: str


class FieldFlows(BaseModel):
    flows: list[FieldFlow]
    dagster_url: str


def _name_group() -> dict[str, str]:
    from lineage.assets import SCHEMAS
    groups = {table: db for (db, table) in SCHEMAS}
    groups["(computed)"] = "analytics"  # analytics/metrics is computed, not a table
    return groups


@router.get("/graph", response_model=LineageGraph)
def graph() -> LineageGraph:
    """Table-level lineage edges (declared + auto-derived + FK referential) with group + stats."""
    from lineage.assets import SCHEMAS, edges as asset_edges

    groups = _name_group()
    edges = [
        LineageEdge(source=f, target=t, basis=b,
                    source_group=groups.get(f), target_group=groups.get(t))
        for (f, t, b) in asset_edges()
    ]
    by_basis: dict[str, int] = {}
    for e in edges:
        by_basis[e.basis] = by_basis.get(e.basis, 0) + 1
    stats = LineageStats(assets=len(SCHEMAS) + 1, edges=len(edges), by_basis=by_basis)
    return LineageGraph(edges=edges, stats=stats, dagster_url=DAGSTER_URL)


@router.get("/field-flow", response_model=FieldFlows)
def field_flow() -> FieldFlows:
    """Mermaid `flowchart` source for each join key's propagation (composite_figi, sym_id)."""
    from lineage.diagram import mermaid_for

    flows = [FieldFlow(key=k, mermaid=mermaid_for(k)) for k in ("composite_figi", "sym_id")]
    return FieldFlows(flows=flows, dagster_url=DAGSTER_URL)
