"""The portfolios module — clients' portfolios as weights over time (QRP-own `qrp` schema).

Weights-first: a portfolio is a time series of effective-dated weight vectors over sym_id.
Returns/PnL are computed by weighting sym's constituent returns (EOD now; the same engine
takes a live price source later). QRP owns the `qrp` schema; sym is read-only.
"""
