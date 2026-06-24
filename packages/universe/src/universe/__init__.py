"""QRP universe package — research-universe registry + membership.

Event-log truth (``membership_event``) + point-in-time projection (``universe_membership``),
multi-source monitors with a two-stage proposal gate, and an accuracy gate vs an independent
reference. Owns its own ``universe`` database. Identity resolution (token -> CompositeFIGI, writing
securities) is INJECTED via the ``Resolver`` protocol so universe imports nothing from sym — the
dependency edge is one-way ``sym -> universe``.
"""
