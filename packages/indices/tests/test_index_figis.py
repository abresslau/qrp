"""Canonical index FIGI static map + seeder (B6). DB-free."""

from __future__ import annotations

from indices.figis import INDEX_FIGIS, attach_index_figis


def test_figis_are_well_formed_bbg_ids():
    # Every entry is a Bloomberg FIGI (BBG + 9 alnum) keyed by a Yahoo index symbol.
    assert INDEX_FIGIS
    for sym, figi in INDEX_FIGIS.items():
        assert sym.startswith("^") or "." in sym, sym
        assert figi.startswith("BBG") and len(figi) == 12, figi
    assert len(set(INDEX_FIGIS.values())) == len(INDEX_FIGIS)  # no dup FIGIs


class _FakeConn:
    """Minimal psycopg-like stand-in: yahoo xref resolves, records figi inserts."""

    def __init__(self, known):
        self.known = known  # yahoo_symbol -> sym_id
        self.attached = []
        self.autocommit = False

    def execute(self, sql, params):
        if "SELECT sym_id FROM instrument_xref" in sql:
            source, value = params
            sym_id = self.known.get(value) if source == "yahoo" else None
            return _Cur((sym_id,) if sym_id is not None else None)
        if "INSERT INTO instrument_xref" in sql:
            sym_id, source, value = params
            self.attached.append((sym_id, source, value))
            return _Cur(None)
        raise AssertionError(sql)


class _Cur:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


def test_attach_only_known_instruments():
    # ^GDAXI exists (sym_id 7); the rest don't -> attached=1, missing=3.
    conn = _FakeConn({"^GDAXI": 7})
    attached, missing = attach_index_figis(conn)
    assert attached == 1 and missing == len(INDEX_FIGIS) - 1
    assert (7, "figi", INDEX_FIGIS["^GDAXI"]) in conn.attached
