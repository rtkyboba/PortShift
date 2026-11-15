"""Run the DDL, loader and readers for real in DuckDB (Spark SQL transpiled with sqlglot)."""
import json
import pathlib
import sys

import duckdb
import pytest
import sqlglot

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipelines"))
import load_fixtures  # noqa: E402
import queries  # noqa: E402
import scenario  # noqa: E402
import tables  # noqa: E402

FIX = ROOT / "demo" / "fixtures"


def to_duck(sql: str) -> str:
    sql = sql.split("\nCOMMENT")[0]  # DuckDB has no table COMMENT clause
    out = sqlglot.transpile(sql.replace(" USING DELTA", ""), read="databricks", write="duckdb")[0]
    return out.replace("main.portshift.", "portshift.")


@pytest.fixture()
def con():
    c = duckdb.connect()
    c.execute("CREATE SCHEMA portshift")
    load_fixtures.run(lambda s: None if s.startswith("CREATE SCHEMA") else c.execute(to_duck(s)))
    return c


def rows(c, sql):
    cur = c.execute(to_duck(sql))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def test_all_sql_parses_as_spark():
    for s in tables.all_ddl() + list(queries.READERS.values()) + [queries.scenario_rows("SC-1")]:
        sqlglot.parse_one(s, read="databricks")


def test_fixture_fields_are_in_tables():
    for t in tables.TABLE_NAMES:
        for row in json.loads((FIX / f"{t}.json").read_text()):
            assert set(row) <= set(tables.columns(t)), t


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_reader_roundtrips_fixture(con, table):
    expected = json.loads((FIX / f"{table}.json").read_text())
    got = rows(con, queries.READERS[table])
    assert len(got) == len(expected)
    key = tables.TABLES[table][1]
    exp = {tuple(r[k] for k in key): r for r in expected}
    for g in got:
        e = exp[tuple(g[k] for k in key)]
        for col in tables.columns(table):
            assert g[col] == e.get(col), (table, col)


def test_loader_is_idempotent(con):
    load_fixtures.run(lambda s: None if s.startswith("CREATE SCHEMA") else con.execute(to_duck(s)))
    assert len(rows(con, queries.READERS["shipments"])) == 14


def test_literal_escaping():
    assert load_fixtures.literal("it's a\\b") == "'it\\'s a\\\\b'"
    assert load_fixtures.literal([[1.5, 2.0]]) == "array(array(1.5, 2.0))"
    assert load_fixtures.literal(None) == "NULL" and load_fixtures.literal(True) == "TRUE"


def test_unknown_field_rejected():
    with pytest.raises(ValueError):
        load_fixtures.insert_sql("cost_rates", [{"mode": "x", "bogus": 1}])


def test_scenario_query_and_state(con):
    r = rows(con, queries.scenario_rows("SC-1"))
    assert len(r) == 14
    assert [x["shipment_id"] for x in r if x["change_type"]] == ["S-1002"]

    ships = json.loads((FIX / "shipments.json").read_text())
    legs = json.loads((FIX / "legs.json").read_text())
    changes = json.loads((FIX / "scenario_changes.json").read_text())
    state = scenario.apply_scenario(ships, legs, changes)
    s2 = next(s for s in state if s["shipment_id"] == "S-1002")
    assert s2["changed"] and s2["eta"] == "2026-11-19T10:00:00Z"
    assert s2["legs"][0]["planned_start"] == "2026-11-18T06:00:00Z"
    assert not next(s for s in state if s["shipment_id"] == "S-1003")["changed"]
    assert ships[1]["eta"] == "2026-11-16T10:00:00Z"  # input untouched


def test_dry_run_runs_without_credentials(capsys):
    assert load_fixtures.main(["--dry-run"]) == 0
    assert "CREATE TABLE IF NOT EXISTS main.portshift.legs" in capsys.readouterr().out


def test_confirmed_suez_evidence_v7(con):
    ev = rows(con, queries.READERS["evidence"])
    v7 = next(e for e in ev if e["evidence_id"] == "V-7")
    assert v7["event_id"] == "E-2" and v7["is_official"] is True
    e2 = next(e for e in rows(con, queries.READERS["disruption_events"]) if e["event_id"] == "E-2")
    assert e2["status"] == "confirmed"
    s1 = next(r for r in rows(con, queries.READERS["shipment_risk"]) if r["shipment_id"] == "S-1001")
    assert s1["level"] == 4 and s1["event_ids"] == ["E-2"]


def test_multi_waypoint_geometry_roundtrips(con):
    got = rows(con, queries.READERS["legs"])
    assert max(len(g["geometry"]) for g in got) > 3  # sea-lane legs have many waypoints
    for g in got:
        assert len(g["geometry"]) >= 2
        assert all(len(p) == 2 for p in g["geometry"])


def test_extra_km_is_nullable(con):
    changes = rows(con, queries.scenario_rows("SC-1"))
    assert next(r for r in changes if r["change_type"])["extra_km"] is None
    row = {"scenario_id": "SC-2", "shipment_id": "S-1001", "change_type": "reroute", "extra_km": 1200.5}
    con.execute(to_duck(load_fixtures.insert_sql("scenario_changes", [row])))
    got = rows(con, "SELECT scenario_id, extra_km FROM main.portshift.scenario_changes ORDER BY scenario_id")
    assert [(g["scenario_id"], g["extra_km"]) for g in got] == [("SC-1", None), ("SC-2", 1200.5)]
