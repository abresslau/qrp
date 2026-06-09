"""Capture the SQL statements a loader executes, for automatic lineage derivation.

Wrap a psycopg connection: every ``execute()`` / ``executemany()`` at the connection or cursor
level is recorded (pass-through — the statement still runs normally). Feed the captured
statements to :mod:`lineage.derive`.

QRP loaders typically read via one connection and write via another (e.g. optimiser reads the
``sym`` package and writes the ``optimiser`` DB). Use :class:`CaptureSession` to give both
connections **one shared sink**, so ``derive_edges`` sees the whole run and can produce the
cross-DB edge::

    sess = CaptureSession()
    solve(sess.wrap(sym_conn), sess.wrap(opt_conn))
    edges = derive_edges(sess.captured, schema=pg_schema(sym_conn))

Residual limits (documented, low-reachability for current loaders): statements from a
rolled-back transaction remain in the sink; server-side/named cursors and ``COPY`` bypass
``execute`` and are not captured.
"""

from __future__ import annotations


def _text(q) -> str:
    if isinstance(q, (bytes, bytearray)):
        return q.decode("utf-8", "replace")
    return q if isinstance(q, str) else str(q)


class _Cursor:
    """Pass-through cursor that records the SQL it executes into a shared sink."""

    def __init__(self, cur, sink: list[str]):
        object.__setattr__(self, "_cur", cur)
        object.__setattr__(self, "_sink", sink)

    def execute(self, query, params=None, **kw):
        self._sink.append(_text(query))
        return self._cur.execute(query, params, **kw)

    def executemany(self, query, params_seq=None, **kw):
        self._sink.append(_text(query))
        return self._cur.executemany(query, params_seq, **kw)

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def __setattr__(self, name, value):
        setattr(self._cur, name, value)

    def __iter__(self):
        return iter(self._cur)

    def __enter__(self):
        self._cur.__enter__()
        return self

    def __exit__(self, *exc):
        return self._cur.__exit__(*exc)


class CapturingConnection:
    """Wrap a psycopg connection; record every executed statement into ``.captured``.

    Attribute reads and writes (other than the wrapper's own ``_conn``/``captured``) delegate to
    the real connection — so ``conn.autocommit = True``, ``conn.row_factory = ...`` etc. all reach
    psycopg, not the wrapper.
    """

    _OWN = {"_conn", "captured"}

    def __init__(self, conn, sink: list[str] | None = None):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "captured", sink if sink is not None else [])

    def execute(self, query, params=None, **kw):
        self.captured.append(_text(query))
        return self._conn.execute(query, params, **kw)

    def cursor(self, *a, **kw):
        return _Cursor(self._conn.cursor(*a, **kw), self.captured)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        if name in CapturingConnection._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)


class CaptureSession:
    """One shared sink across multiple connections, for a single loader run."""

    def __init__(self):
        self.captured: list[str] = []

    def wrap(self, conn) -> CapturingConnection:
        return CapturingConnection(conn, self.captured)
