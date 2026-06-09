"""Unit tests for lineage.derive + lineage.sql_capture (static; no live DB)."""

from lineage.derive import classify, derive_edges, _norm
from lineage.sql_capture import CaptureSession


# --- placeholder neutralization ---

def test_norm_neutralizes_placeholders():
    assert "%s" not in _norm("INSERT INTO t VALUES (%s, %s)")
    assert _norm("WHERE x = %(name)s AND y = %s").count("NULL") == 2
    # %% is an escaped literal percent, must survive as a single %, not become a placeholder
    out = _norm("SELECT s %% 500 AS m")
    assert "NULL" not in out and "%" in out


# --- classify ---

def test_classify_insert_values_is_write_no_sources():
    c = classify("INSERT INTO optimiser.weight (solution_id, composite_figi, ticker, weight) "
                 "VALUES (%s,%s,%s,%s)")
    assert c["kind"] == "write" and c["target"] == "weight" and c["basis"] == "values"
    assert "composite_figi" in c["target_cols"] and c["sources"] == set()


def test_classify_insert_select_is_write_with_sources():
    c = classify("INSERT INTO fact_returns (composite_figi, pr) "
                 "SELECT composite_figi, close FROM prices_raw")
    assert c["kind"] == "write" and c["target"] == "fact_returns" and c["basis"] == "sql"
    assert "prices_raw" in c["sources"]


def test_classify_select_is_read():
    c = classify("SELECT composite_figi, pr FROM fact_returns WHERE window_id = %s")
    assert c["kind"] == "read" and "fact_returns" in c["tables"]


def test_classify_update_is_write():
    c = classify("UPDATE fundamentals SET market_cap_usd = %s WHERE composite_figi = %s")
    assert c["kind"] == "write" and c["target"] == "fundamentals"


def test_cte_aliases_excluded_from_tables():
    sql = ("WITH shares AS (SELECT composite_figi FROM fundamentals), "
           "px AS (SELECT close FROM prices_raw) "
           "SELECT * FROM shares JOIN px USING (composite_figi)")
    c = classify(sql)
    assert c["kind"] == "read"
    assert "shares" not in c["tables"] and "px" not in c["tables"]
    assert {"fundamentals", "prices_raw"} <= c["tables"]


# --- derive_edges ---

def test_cross_db_correlation_with_schema_keys():
    schema = {"fact_returns": {"composite_figi": "char", "pr": "numeric"},
              "weight": {"composite_figi": "char", "weight": "numeric"}}
    stmts = [
        "SELECT as_of_date, composite_figi, pr FROM fact_returns WHERE window_id = %s",
        "INSERT INTO optimiser.weight (solution_id, composite_figi, ticker, weight) "
        "VALUES (%s,%s,%s,%s)",
    ]
    edges = derive_edges(stmts, schema=schema)
    e = [x for x in edges if x["to"] == "weight" and x["from"] == "fact_returns"]
    assert e and "composite_figi" in e[0]["keys"]
    assert "run-correlation" in e[0]["basis"]


def test_select_star_key_resolved_via_schema():
    schema = {"securities": {"composite_figi": "char"}, "wiki_map": {"composite_figi": "char"}}
    stmts = ["SELECT * FROM securities",
             "INSERT INTO wiki_map (composite_figi, article) VALUES (%s,%s)"]
    edges = derive_edges(stmts, schema=schema)
    e = [x for x in edges if x["to"] == "wiki_map" and x["from"] == "securities"]
    assert e and "composite_figi" in e[0]["keys"]  # key found despite SELECT *


def test_order_aware_no_future_read_edge():
    stmts = ["INSERT INTO weight (composite_figi) VALUES (%s)",
             "SELECT composite_figi FROM fact_returns"]
    schema = {"fact_returns": {"composite_figi": "c"}, "weight": {"composite_figi": "c"}}
    edges = derive_edges(stmts, schema=schema)
    assert not [x for x in edges if x["to"] == "weight" and x["from"] == "fact_returns"]


def test_dedup_unions_keys():
    schema = {"fact_returns": {"composite_figi": "c"}, "weight": {"composite_figi": "c"}}
    stmts = ["SELECT composite_figi FROM fact_returns",
             "SELECT composite_figi FROM fact_returns",
             "INSERT INTO weight (composite_figi) VALUES (%s)"]
    edges = derive_edges(stmts, schema=schema)
    fr = [x for x in edges if x["to"] == "weight" and x["from"] == "fact_returns"]
    assert len(fr) == 1 and fr[0]["keys"] == ["composite_figi"]


def test_insert_select_direct_edge_has_basis_sql():
    edges = derive_edges([
        "INSERT INTO fact_returns (composite_figi, pr) "
        "SELECT composite_figi, close FROM prices_raw"],
        schema={"prices_raw": {"composite_figi": "c"}, "fact_returns": {"composite_figi": "c"}})
    e = [x for x in edges if x["from"] == "prices_raw" and x["to"] == "fact_returns"]
    assert e and "sql" in e[0]["basis"] and "composite_figi" in e[0]["keys"]


def test_with_before_insert_captures_real_source():
    # CTE attached above the INSERT's SELECT — the real upstream (prices_raw) must still be found.
    c = classify("WITH s AS (SELECT composite_figi, close FROM prices_raw) "
                 "INSERT INTO fact_returns (composite_figi, pr) "
                 "SELECT composite_figi, close FROM s")
    assert c["kind"] == "write" and c["target"] == "fact_returns" and c["basis"] == "sql"
    assert "prices_raw" in c["sources"] and "s" not in c["sources"]


def test_delete_does_not_fabricate_edges():
    # A plain DELETE after some reads must NOT correlate to those reads.
    stmts = ["SELECT composite_figi FROM fact_returns",
             "DELETE FROM weight WHERE composite_figi = %s"]
    edges = derive_edges(stmts, schema={"fact_returns": {"composite_figi": "c"},
                                        "weight": {"composite_figi": "c"}})
    assert not [e for e in edges if e["to"] == "weight"]


def test_update_from_is_write_with_source():
    c = classify("UPDATE fundamentals SET market_cap_usd = %s FROM fx_rate "
                 "WHERE fundamentals.composite_figi = %s")
    assert c["kind"] == "write" and c["target"] == "fundamentals"
    assert "fx_rate" in c["sources"]


# --- capture ---

class _FakeCur:
    def execute(self, q, p=None):
        return self

    def executemany(self, q, p=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self):
        self.autocommit = False

    def execute(self, q, p=None):
        return _FakeCur()

    def cursor(self, *a, **k):
        return _FakeCur()


def test_capture_session_combines_connections_and_delegates_attrs():
    sess = CaptureSession()
    read_conn = sess.wrap(_FakeConn())
    write_conn = sess.wrap(_FakeConn())
    read_conn.autocommit = True  # must delegate to the real connection
    read_conn.execute("SELECT composite_figi FROM fact_returns")
    with write_conn.cursor() as cur:
        cur.executemany("INSERT INTO weight (composite_figi) VALUES (%s)", [(1,)])
    assert len(sess.captured) == 2
    assert read_conn.autocommit is True
    edges = derive_edges(sess.captured,
                         schema={"fact_returns": {"composite_figi": "c"},
                                 "weight": {"composite_figi": "c"}})
    assert any(e["from"] == "fact_returns" and e["to"] == "weight" for e in edges)
