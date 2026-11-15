"""Integration suite against a real Databricks warehouse. Run with: pytest -m databricks

Skipped unless DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_WAREHOUSE_ID are all set. Every run
works in a throwaway schema portshift_test_<random> (in DATABRICKS_CATALOG, default main) and drops it
afterwards, so the real portshift schema is never touched.
"""
import json
import os
import uuid

import pytest

import db
import load_fixtures
import queries
import tables

pytestmark = [
    pytest.mark.databricks,
    pytest.mark.skipif(not db.configured(), reason="DATABRICKS_HOST/TOKEN/WAREHOUSE_ID not set"),
]

NASTY = "O'Brien \\ said \"hi\" ; -- 100%\nline2"


@pytest.fixture(scope="module")
def cursor():
    schema = f"portshift_test_{uuid.uuid4().hex[:10]}"
    saved = os.environ.get("DATABRICKS_SCHEMA")
    os.environ["DATABRICKS_SCHEMA"] = schema
    conn = db.connect()
    cur = conn.cursor()
    try:
        yield cur
    finally:
        try:
            cur.execute("DROP SCHEMA IF EXISTS {}.{} CASCADE".format(*tables._cat_sch()))
        finally:
            cur.close()
            conn.close()
            if saved is None:
                os.environ.pop("DATABRICKS_SCHEMA", None)
            else:
                os.environ["DATABRICKS_SCHEMA"] = saved


@pytest.fixture()
def loaded(cursor):
    load_fixtures.run(cursor.execute)
    return cursor


def _plain(v):
    return [_plain(x) for x in v] if isinstance(v, (list, tuple)) else v


def _read(cursor, table):
    return [{k: _plain(v) for k, v in r.items()} for r in db.fetch(cursor, queries.reader(table))]


def test_schema_name_is_throwaway(cursor):
    assert tables._cat_sch()[1].startswith("portshift_test_")


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_reader_returns_fixture_rows_unchanged(loaded, fixtures_dir, table):
    expected = json.loads((fixtures_dir / f"{table}.json").read_text())
    key = tables.TABLES[table][1]
    cols = tables.columns(table)
    exp = {tuple(r[k] for k in key): {c: r.get(c) for c in cols} for r in expected}  # absent nullable column -> NULL
    got = {tuple(r[k] for k in key): r for r in _read(loaded, table)}
    assert got == exp


def test_loading_twice_leaves_no_duplicates(loaded, fixtures_dir):
    load_fixtures.run(loaded.execute)
    n = len(json.loads((fixtures_dir / "shipments.json").read_text()))
    assert len(_read(loaded, "shipments")) == n


def test_quote_backslash_and_newline_roundtrip(loaded):
    row = {"scenario_id": "S-T", "label": NASTY, "status": "tentative",
           "created_at": "2026-01-01T00:00:00Z", "cost_delta": 1.5, "currency": "EUR"}
    loaded.execute(load_fixtures.insert_sql("scenarios", [row]))
    got = [r for r in _read(loaded, "scenarios") if r["scenario_id"] == "S-T"]
    assert got == [row]


def test_null_published_at_roundtrips(loaded):
    row = {"evidence_id": "V-T", "event_id": "E-T", "claim": "c", "url": "u", "title": "t",
           "retrieved_at": "2026-01-01T00:00:00Z", "published_at": None, "domain": "d", "is_official": False}
    loaded.execute(load_fixtures.insert_sql("evidence", [row]))
    got = [r for r in _read(loaded, "evidence") if r["evidence_id"] == "V-T"]
    assert got == [row]


def test_scenario_rows_missing_id_returns_all_shipments_unchanged(loaded):
    rows = db.fetch(loaded, queries.scenario_rows("NO-SUCH-SCENARIO"))
    assert len(rows) == len(_read(loaded, "shipments"))
    assert all(r["change_type"] is None for r in rows)


def test_scenario_rows_quote_in_id_is_escaped_for_spark(loaded):
    rows = db.fetch(loaded, queries.scenario_rows("x' OR '1'='1"))
    assert all(r["change_type"] is None for r in rows)


def test_reader_on_empty_table_returns_no_rows(loaded):
    loaded.execute(f"DELETE FROM {tables.qualified('cost_rates')}")
    assert _read(loaded, "cost_rates") == []
