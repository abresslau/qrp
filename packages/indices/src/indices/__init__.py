"""QRP indices package — benchmark index levels, index returns/extremes, universe→benchmark link.

Standalone peer package with its own ``indices`` database (the fx/equity/universe pattern). Imports
nothing from sym; reads sym identity (instrument/instrument_xref) and the universe membership roster
through injected read-only connections. Depends on ``equity`` for the shared return-window math.
"""
