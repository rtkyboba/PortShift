"""Databricks mode reuses one SQL connection and caches table reads briefly; writes clear the cache."""
import sys
import types

import pytest

import data


class FakeCursor:
    def __init__(self, log):
        self.log, self.description = log, [("shipment_id", "string")]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q):
        self.log["queries"].append(q)
        if self.log.get("fail_next"):
            self.log["fail_next"] = False
            raise ConnectionError("stale")

    def fetchall(self):
        return [("S-1",)]


@pytest.fixture
def fake_sql(monkeypatch):
    log = {"connects": 0, "queries": []}

    class Conn:
        def cursor(self):
            return FakeCursor(log)

        def close(self):
            pass

    def connect(**kw):
        log["connects"] += 1
        return Conn()

    mod = types.ModuleType("databricks.sql"); mod.connect = connect
    pkg = types.ModuleType("databricks"); pkg.sql = mod
    monkeypatch.setitem(sys.modules, "databricks", pkg); monkeypatch.setitem(sys.modules, "databricks.sql", mod)
    for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setattr(data, "_SQL_CONN", None)
    data.forget_rows()
    yield log
    data.forget_rows()
    monkeypatch.setattr(data, "_SQL_CONN", None)


def test_reads_share_one_connection_and_repeat_reads_come_from_the_cache(fake_sql):
    for t in ("shipments", "legs", "shipments", "legs", "events" if "events" in data.ORDER else "evidence"):
        data._sql_rows(t)
    assert fake_sql["connects"] == 1 and len(fake_sql["queries"]) == 3


def test_cached_rows_are_copies(fake_sql):
    data._sql_rows("shipments")[0]["shipment_id"] = "changed"
    assert data._sql_rows("shipments")[0]["shipment_id"] == "S-1"


def test_forget_rows_and_expiry_force_a_fresh_read(fake_sql, monkeypatch):
    data._sql_rows("shipments"); data.forget_rows(); data._sql_rows("shipments")
    monkeypatch.setenv("PORTSHIFT_SQL_CACHE_S", "0")
    data._sql_rows("shipments")
    assert len(fake_sql["queries"]) == 3


def test_a_stale_connection_is_replaced_once(fake_sql):
    fake_sql["fail_next"] = True
    assert data._sql_rows("shipments") == [{"shipment_id": "S-1"}]
    assert fake_sql["connects"] == 2


def test_a_successful_write_request_clears_the_cache(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    calls = []
    monkeypatch.setattr(data, "forget_rows", lambda table=None: calls.append(table))
    c = TestClient(main.app)
    c.get("/api/shipments")
    assert calls == []
    c.post("/api/planned", json={"plans": []})
    assert calls == [None]
