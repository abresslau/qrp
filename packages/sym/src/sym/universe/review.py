"""`universe review` operator digest (Story U3.4, FR9).

One surface for everything that needs the operator's attention, so gated changes,
stale monitors, aging-unresolved members, and accuracy alarms never pile up
unseen. Assembles from the U3.1–U3.3 building blocks; the confirm/reject actions
are the gating module's (appended events, never mutations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import psycopg

from sym.universe.accuracy import accuracy_alarms
from sym.universe.gating import pending_proposals
from sym.universe.monitor import DEFAULT_STALE_AFTER, stale_monitors

DEFAULT_UNRESOLVED_AGE = timedelta(days=14)


@dataclass
class Digest:
    pending_changes: list[dict] = field(default_factory=list)
    stale_monitors: list[tuple] = field(default_factory=list)
    aging_unresolved: list[dict] = field(default_factory=list)
    accuracy_alarms: list[dict] = field(default_factory=list)
    incomplete_members: dict[str, int] = field(default_factory=dict)

    @property
    def is_clear(self) -> bool:
        return not (
            self.pending_changes
            or self.stale_monitors
            or self.aging_unresolved
            or self.accuracy_alarms
            or self.incomplete_members.get("fail", 0)
        )


def aging_unresolved(
    conn: psycopg.Connection,
    *,
    min_age: timedelta = DEFAULT_UNRESOLVED_AGE,
    now: datetime | None = None,
) -> list[dict]:
    """Per-universe counts of members unresolved longer than ``min_age``.

    Unresolved members are *retained* (survivorship), but one that has been
    unresolved a long time is worth an operator's eyes (a fixable identifier, or a
    genuinely dead name to accept).
    """
    from datetime import UTC

    now = now or datetime.now(UTC)
    cutoff = now - min_age
    rows = conn.execute(
        """
        SELECT universe_id, count(*) AS unresolved, min(resolved_at) AS oldest
          FROM universe_member_resolution
         WHERE resolution_status = 'unresolved' AND resolved_at <= %s
         GROUP BY universe_id
         ORDER BY universe_id
        """,
        (cutoff,),
    ).fetchall()
    return [
        {"universe_id": uid, "unresolved": n, "oldest": oldest} for uid, n, oldest in rows
    ]


def build_digest(
    conn: psycopg.Connection,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    unresolved_age: timedelta = DEFAULT_UNRESOLVED_AGE,
    now: datetime | None = None,
) -> Digest:
    """Assemble the operator review digest from every attention source."""
    from sym.validate.completeness import completeness_summary

    return Digest(
        pending_changes=pending_proposals(conn),
        stale_monitors=stale_monitors(conn, stale_after=stale_after, now=now),
        aging_unresolved=aging_unresolved(conn, min_age=unresolved_age, now=now),
        accuracy_alarms=accuracy_alarms(conn),
        incomplete_members=completeness_summary(conn),
    )


def format_digest(digest: Digest) -> str:
    """Render a digest as an operator-readable text block (pure)."""
    if digest.is_clear:
        return "universe review: all clear — nothing needs attention."
    lines: list[str] = ["universe review:"]

    lines.append(f"\n  pending changes (gated): {len(digest.pending_changes)}")
    for p in digest.pending_changes[:20]:
        lines.append(
            f"    [{p['proposal_id']}] {p['universe_id']} {p['change']} "
            f"{p['raw_identifier']} @ {p['effective_date']} "
            f"(reason={p['reason']}, seen={p['seen_count']})"
        )

    lines.append(f"\n  stale monitors: {len(digest.stale_monitors)}")
    for uid, last in digest.stale_monitors:
        lines.append(f"    {uid}: last success {last or 'never'}")

    lines.append(f"\n  aging-unresolved members: {len(digest.aging_unresolved)} universe(s)")
    for a in digest.aging_unresolved:
        lines.append(f"    {a['universe_id']}: {a['unresolved']} unresolved (oldest {a['oldest']})")

    lines.append(f"\n  accuracy alarms: {len(digest.accuracy_alarms)}")
    for al in digest.accuracy_alarms:
        lines.append(
            f"    {al['universe_id']}: divergence {al['divergence']:.3f} "
            f"> {al['threshold']:.3f} vs {al['reference_source']}"
        )

    if digest.incomplete_members:
        c = digest.incomplete_members
        lines.append(
            f"\n  incomplete members: {c.get('fail', 0)} fail, {c.get('warn', 0)} warn "
            f"(see `sym validate`)"
        )
    return "\n".join(lines)
