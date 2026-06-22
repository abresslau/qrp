"""QRP `rates` package — fixed-income yield curves.

A standalone QRP peer package (alongside `sym`, `macro`, …) that owns its own Postgres
database (`rates`). v1 stores the Bank of England's daily-published UK yield curves
(gilt nominal/real/implied-inflation + SONIA/OIS) verbatim and derives on read.
"""
