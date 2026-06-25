"""QRP commodities package — daily commodity prices, own database.

v1 stores Tier-A vendor **continuous front-month** series per commodity (raw OHLCV + volume),
across energy / precious metals / base metals / grains / softs / livestock. The dated-futures
matrix + roll/back-adjustment (Tier B) is a later phase. Standalone, library-first; mirrors the
`rates` peer package.
"""
