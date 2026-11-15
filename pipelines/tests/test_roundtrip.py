"""Readers, writers and edge cases, run for real in DuckDB (Spark SQL transpiled by sqlglot). No network."""
import json

import pytest

import load_fixtures
import queries
import scenario
import tables

NASTY = "O'Brien \\ said \"hi\" ; DROP TABLE x; -- 100% é中\nline2"
CHANGE_COLS = ["change_type", "delay_days", "new_planned_start", "cost_delta", "note", "extra_km"]


def _fixture(name, fixtures_dir):
    return json.loads((fixtures_dir / f"{name}.json").read_text())


def _by_key(table, rows):
    key = tables.TABLES[table][1]
    return {tuple(r[k] for k in key): r for r in rows}


# ---- one test per reader ---------------------------------------------------------------------
@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_reader_returns_contract_columns_in_order(loaded_db, table):
    cur = loaded_db.run(queries.READERS[table])
    assert [d[0] for d in cur.description] == tables.columns(table)


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_reader_returns_every_fixture_row_unchanged(loaded_db, fixtures_dir, table):
    expected = _by_key(table, _fixture(table, fixtures_dir))
    got = _by_key(table, loaded_db.rows(queries.READERS[table]))
    # fixtures may omit nullable columns; the reader returns them as None
    assert got == {k: {c: r.get(c) for c in tables.columns(table)} for k, r in expected.items()}


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_reader_on_empty_table_returns_no_rows(empty_db, table):
    assert empty_db.rows(queries.READERS[table]) == []


def test_reader_order_for_legs_is_shipment_then_seq(loaded_db):
    got = [(r["shipment_id"], r["seq"]) for r in loaded_db.rows(queries.READERS["legs"])]
    assert got == sorted(got)


def test_reader_order_for_scenarios_is_newest_first(empty_db):
    base = {"label": "x", "status": "tentative", "cost_delta": 1.0, "currency": "EUR"}
    empty_db.write("scenarios", [{**base, "scenario_id": "A", "created_at": "2026-01-01T00:00:00Z"},
                                 {**base, "scenario_id": "B", "created_at": "2026-02-01T00:00:00Z"}])
    assert [r["scenario_id"] for r in empty_db.rows(queries.READERS["scenarios"])] == ["B", "A"]


# ---- round trips -----------------------------------------------------------------------------
def test_roundtrip_string_with_quotes_backslash_and_newline(empty_db):
    row = {"scenario_id": "S", "label": NASTY, "status": "tentative",
           "created_at": "2026-01-01T00:00:00Z", "cost_delta": 0.0, "currency": "EUR"}
    empty_db.write("scenarios", [row])
    assert empty_db.rows(queries.READERS["scenarios"]) == [row]


def test_roundtrip_single_quote_is_kept_not_dropped(empty_db):
    # Spark reads '' as adjacent-literal concatenation, which would turn it's into its.
    empty_db.write("shipments", [{"shipment_id": "S", "cargo": "it's", "is_demo_fleet": True}])
    assert empty_db.rows("SELECT cargo FROM main.portshift.shipments") == [{"cargo": "it's"}]


def test_roundtrip_null_columns_stay_null(empty_db):
    row = {"evidence_id": "V", "event_id": "E", "claim": "c", "url": "u", "title": "t",
           "retrieved_at": "2026-01-01T00:00:00Z", "published_at": None, "domain": "d", "is_official": False}
    empty_db.write("evidence", [row])
    assert empty_db.rows(queries.READERS["evidence"]) == [row]


def test_missing_keys_in_row_are_written_as_null(empty_db):
    empty_db.write("cost_rates", [{"mode": "ship"}])
    assert empty_db.rows(queries.READERS["cost_rates"]) == [
        {"mode": "ship", "per_delay_day": None, "rebooking_fee": None, "per_extra_km": None, "currency": None}]


def test_roundtrip_nested_array_of_doubles(empty_db):
    geometry = [[51.95, 4.14], [-1.5, 100.0], [0.0, -179.99]]
    empty_db.write("legs", [{"shipment_id": "S", "seq": 1, "geometry": geometry}])
    got = empty_db.rows("SELECT geometry FROM main.portshift.legs")
    assert [list(p) for p in got[0]["geometry"]] == geometry


def test_roundtrip_string_array_preserves_order_and_nasty_values(empty_db):
    ids = ["E-2", "E-1", "it's"]
    empty_db.write("shipment_risk", [{"shipment_id": "S", "level": 3, "reason": "r", "event_ids": ids}])
    assert empty_db.rows(queries.READERS["shipment_risk"])[0]["event_ids"] == ids


def test_roundtrip_empty_string_array(empty_db):
    empty_db.write("shipment_risk", [{"shipment_id": "S", "level": 1, "reason": "clear", "event_ids": []}])
    assert empty_db.rows(queries.READERS["shipment_risk"])[0]["event_ids"] == []


def test_roundtrip_iso_timestamp_string_is_unchanged(empty_db):
    ts = "2026-11-14T16:00:00Z"
    empty_db.write("disruption_events", [{"event_id": "E", "window_start": ts, "detected_at": ts}])
    row = empty_db.rows(queries.READERS["disruption_events"])[0]
    assert (row["window_start"], row["detected_at"]) == (ts, ts)


def test_roundtrip_numbers_booleans_and_negative_values(empty_db):
    row = {"event_id": "E", "lat": -33.86, "lon": 151.2, "radius_km": 0.0, "is_fixture": False}
    empty_db.write("disruption_events", [row])
    got = empty_db.rows(queries.READERS["disruption_events"])[0]
    assert (got["lat"], got["lon"], got["radius_km"], got["is_fixture"]) == (-33.86, 151.2, 0.0, False)


# ---- lit() and literal() ---------------------------------------------------------------------
def test_lit_wraps_in_single_quotes():
    assert queries.lit("abc") == "'abc'"


def test_lit_escapes_quote_with_backslash():
    assert queries.lit("it's") == "'it\\'s'"


def test_lit_escapes_backslash_before_quote():
    assert queries.lit("a\\'b") == "'a\\\\\\'b'"


def test_lit_coerces_non_strings():
    assert queries.lit(5) == "'5'"


@pytest.mark.parametrize("value", ["plain", "it's", "\\", "\\'", "'; DROP TABLE shipments; --", "''", ""])
def test_lit_value_survives_a_real_sql_engine(empty_db, value):
    assert empty_db.rows(f"SELECT {queries.lit(value)} AS v") == [{"v": value}]


@pytest.mark.parametrize("value,expected", [
    (None, "NULL"), (True, "TRUE"), (False, "FALSE"), (3, "3"), (1.5, "1.5"),
    ([], "array()"), (["a", "b"], "array('a', 'b')"), ([[1.0, 2.0]], "array(array(1.0, 2.0))"),
])
def test_literal_renders_each_python_type(value, expected):
    assert load_fixtures.literal(value) == expected


# ---- loader validation -----------------------------------------------------------------------
def test_insert_sql_rejects_unknown_field_with_clear_error():
    with pytest.raises(ValueError, match=r"cost_rates: fixture fields not in contract: \['bogus'\]"):
        load_fixtures.insert_sql("cost_rates", [{"mode": "ship", "bogus": 1}])


def test_insert_sql_rejects_unknown_field_in_any_row_not_just_first():
    with pytest.raises(ValueError, match="extra"):
        load_fixtures.insert_sql("cost_rates", [{"mode": "a"}, {"mode": "b", "extra": 1}])


def test_insert_sql_of_no_rows_is_none():
    assert load_fixtures.insert_sql("shipments", []) is None


def test_statements_reject_fixture_dir_with_unknown_field(tmp_path):
    for t in tables.TABLE_NAMES:
        (tmp_path / f"{t}.json").write_text("[]")
    (tmp_path / "cost_rates.json").write_text(json.dumps([{"mode": "ship", "oops": 1}]))
    with pytest.raises(ValueError, match="oops"):
        load_fixtures.statements(fixtures=tmp_path)


# ---- idempotent loader -----------------------------------------------------------------------
def test_loading_twice_leaves_no_duplicates(loaded_db, fixtures_dir):
    loaded_db.load_fixtures()
    for t in tables.TABLE_NAMES:
        assert len(loaded_db.rows(queries.READERS[t])) == len(_fixture(t, fixtures_dir))


def test_loading_twice_gives_identical_rows(loaded_db):
    before = {t: loaded_db.rows(queries.READERS[t]) for t in tables.TABLE_NAMES}
    loaded_db.load_fixtures()
    assert {t: loaded_db.rows(queries.READERS[t]) for t in tables.TABLE_NAMES} == before


def test_loading_replaces_rows_that_are_not_in_fixtures(loaded_db):
    loaded_db.write("cost_rates", [{"mode": "rocket"}])
    loaded_db.load_fixtures()
    assert "rocket" not in [r["mode"] for r in loaded_db.rows(queries.READERS["cost_rates"])]


def test_loading_a_subset_leaves_other_tables_alone(loaded_db):
    loaded_db.write("cost_rates", [{"mode": "rocket"}])
    load_fixtures.run(lambda s: None if s.startswith("CREATE SCHEMA") else loaded_db.run(s), only=["shipments"])
    assert "rocket" in [r["mode"] for r in loaded_db.rows(queries.READERS["cost_rates"])]


def test_create_table_ddl_is_rerunnable_and_keeps_rows(empty_db):
    empty_db.write("cost_rates", [{"mode": "ship"}])
    empty_db.create_tables()  # IF NOT EXISTS: must not raise or wipe
    assert len(empty_db.rows(queries.READERS["cost_rates"])) == 1


# ---- scenario_rows() -------------------------------------------------------------------------
def test_scenario_rows_with_missing_id_returns_every_shipment_unchanged(loaded_db):
    got = loaded_db.rows(queries.scenario_rows("NO-SUCH-SCENARIO"))
    assert len(got) == 14
    assert all(r[c] is None for r in got for c in CHANGE_COLS)


def test_scenario_rows_with_missing_id_still_carries_base_risk(loaded_db):
    got = loaded_db.rows(queries.scenario_rows("NO-SUCH-SCENARIO"))
    assert all(r["level"] is not None for r in got)


def test_scenario_rows_id_with_quote_does_not_break_or_inject(loaded_db):
    got = loaded_db.rows(queries.scenario_rows("x' OR '1'='1"))
    assert all(r["change_type"] is None for r in got)


def test_scenario_rows_id_with_quote_matches_that_exact_scenario(loaded_db):
    loaded_db.write("scenario_changes", [{"scenario_id": "it's", "shipment_id": "S-1003",
                                          "change_type": "reschedule", "delay_days": 2}])
    got = loaded_db.rows(queries.scenario_rows("it's"))
    assert [r["shipment_id"] for r in got if r["change_type"]] == ["S-1003"]


def test_scenario_rows_known_id_marks_only_changed_shipments(loaded_db):
    got = loaded_db.rows(queries.scenario_rows("SC-1"))
    assert [r["shipment_id"] for r in got if r["change_type"]] == ["S-1002"]


def test_scenario_rows_on_empty_tables_returns_no_rows(empty_db):
    assert empty_db.rows(queries.scenario_rows("SC-1")) == []


def test_scenario_rows_shipment_without_risk_row_has_null_level(empty_db):
    empty_db.write("shipments", [{"shipment_id": "S-9", "is_demo_fleet": True}])
    got = empty_db.rows(queries.scenario_rows("SC-1"))
    assert [(r["shipment_id"], r["level"]) for r in got] == [("S-9", None)]


def test_scenario_rows_does_not_duplicate_shipments_across_scenarios(loaded_db):
    loaded_db.write("scenario_changes", [{"scenario_id": "SC-2", "shipment_id": "S-1002",
                                          "change_type": "reschedule", "delay_days": 1}])
    ids = [r["shipment_id"] for r in loaded_db.rows(queries.scenario_rows("SC-1"))]
    assert len(ids) == len(set(ids))


# ---- apply_scenario edge cases ---------------------------------------------------------------
def test_apply_scenario_with_no_inputs_returns_nothing():
    assert scenario.apply_scenario([], [], []) == []


def test_apply_scenario_with_no_changes_leaves_shipments_unchanged():
    ships = [{"shipment_id": "S", "eta": "2026-11-14T00:00:00Z"}]
    out = scenario.apply_scenario(ships, [], [])
    assert out == [{"shipment_id": "S", "eta": "2026-11-14T00:00:00Z", "legs": [], "changed": False,
                    "scenario_change": None}]


def test_apply_scenario_with_null_delay_days_shifts_nothing():
    ships = [{"shipment_id": "S", "eta": "2026-11-14T00:00:00Z"}]
    out = scenario.apply_scenario(ships, [], [{"shipment_id": "S", "delay_days": None}])
    assert out[0]["eta"] == "2026-11-14T00:00:00Z" and out[0]["changed"]


def test_shift_keeps_none():
    assert scenario.shift(None, 3) is None
