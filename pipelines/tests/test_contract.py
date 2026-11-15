"""Contract tests: tables.py DDL and demo/fixtures agree with CONTRACTS.md section 3."""
import json
import pathlib
import re

import pytest

import tables

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = (ROOT / "CONTRACTS.md").read_text()
FIX = ROOT / "demo" / "fixtures"

# CONTRACTS.md section 3 gives column names in prose but no types, so the expected Spark types are
# written down once here. Column NAMES are parsed from CONTRACTS.md, not copied.
EXPECTED_TYPES = {
    "shipments": {"shipment_id": "STRING", "cargo": "STRING", "origin": "STRING", "destination": "STRING",
                  "mode": "STRING", "eta": "STRING", "is_demo_fleet": "BOOLEAN"},
    "legs": {"shipment_id": "STRING", "seq": "INT", "mode": "STRING", "from_name": "STRING",
             "from_lat": "DOUBLE", "from_lon": "DOUBLE", "to_name": "STRING", "to_lat": "DOUBLE",
             "to_lon": "DOUBLE", "geometry": "ARRAY<ARRAY<DOUBLE>>", "planned_start": "STRING",
             "planned_end": "STRING"},
    "disruption_events": {"event_id": "STRING", "type": "STRING", "status": "STRING", "location": "STRING",
                          "lat": "DOUBLE", "lon": "DOUBLE", "radius_km": "DOUBLE", "window_start": "STRING",
                          "window_end": "STRING", "summary": "STRING", "detected_at": "STRING",
                          "is_fixture": "BOOLEAN"},
    "evidence": {"evidence_id": "STRING", "event_id": "STRING", "claim": "STRING", "url": "STRING",
                 "title": "STRING", "retrieved_at": "STRING", "published_at": "STRING", "domain": "STRING",
                 "is_official": "BOOLEAN"},
    "shipment_risk": {"shipment_id": "STRING", "level": "INT", "reason": "STRING",
                      "event_ids": "ARRAY<STRING>"},
    "cost_rates": {"mode": "STRING", "per_delay_day": "DOUBLE", "rebooking_fee": "DOUBLE",
                   "per_extra_km": "DOUBLE", "currency": "STRING"},
    "scenarios": {"scenario_id": "STRING", "label": "STRING", "status": "STRING", "created_at": "STRING",
                  "cost_delta": "DOUBLE", "currency": "STRING"},
    "scenario_changes": {"scenario_id": "STRING", "shipment_id": "STRING", "change_type": "STRING",
                         "delay_days": "INT", "new_planned_start": "STRING", "cost_delta": "DOUBLE",
                         "note": "STRING", "extra_km": "DOUBLE"},
}
# Nullability per CONTRACTS.md: evidence.published_at is "ts|null" (section 2), scenario_changes.extra_km
# is "nullable" (section 3). Every other column is required in fixture rows.
NULLABLE = {("evidence", "published_at"), ("scenario_changes", "extra_km")}

PY_TYPES = {"STRING": str, "INT": int, "DOUBLE": (int, float), "BOOLEAN": bool}


def _split_top_level(text):
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def contract_columns() -> dict[str, list[str]]:
    """Parse the '**`table`**: `col` (PK), ...' lines of CONTRACTS.md section 3."""
    section = CONTRACTS.split("## 3.")[1].split("\n## 4.")[0]
    out = {}
    for line in section.splitlines():
        m = re.match(r"\*\*`(\w+)`\*\*[^:]*: (.*)", line)
        if not m:
            continue
        field_text = re.split(r"\. ", m.group(2))[0]  # field list ends at the first sentence end
        cols = []
        for item in _split_top_level(field_text):
            item = item.strip()
            if item.startswith("`"):
                cols.append(re.match(r"`(\w+)`", item).group(1))
            else:  # e.g. "the citation object fields (`claim`, `url`, ...)"
                cols += re.findall(r"`(\w+)`", item)
        cols += [c for c in re.findall(r"`(\w+)` is nullable", m.group(2)) if c not in cols]
        out[m.group(1)] = cols
    return out


def _conforms(value, spark_type):
    if spark_type.startswith("ARRAY<ARRAY<"):
        return isinstance(value, list) and all(
            isinstance(p, list) and all(_conforms(x, "DOUBLE") for x in p) for p in value)
    if spark_type.startswith("ARRAY<"):
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if spark_type in ("INT", "DOUBLE") and isinstance(value, bool):
        return False
    return isinstance(value, PY_TYPES[spark_type])


CONTRACT = contract_columns()
FIXTURE_FILES = sorted(p.stem for p in FIX.glob("*.json"))
# Fixture files that are not tables, and tables CONTRACTS.md defines that have no Delta DDL yet
# (CONTRACTS.md says so for agent_runs; market_rates is not stored yet). Anything else that is
# missing on one side fails the "same set" tests below, so new tables are picked up automatically.
NON_TABLE_FIXTURES = {"clock"}
CONTRACT_ONLY = {"market_rates", "agent_runs"}


def _load(table):
    path = FIX / f"{table}.json"
    return json.loads(path.read_text()) if path.exists() else []


def _fixture_cases():
    return [(t, i, row) for t in tables.TABLE_NAMES for i, row in enumerate(_load(t))]


def _contract_cols(table):
    if table not in CONTRACT:
        pytest.fail(f"table {table!r} is in pipelines/tables.py but has no section 3 entry in CONTRACTS.md")
    return CONTRACT[table]


def test_every_contract_table_has_ddl():
    missing = sorted(set(CONTRACT) - set(tables.TABLE_NAMES) - CONTRACT_ONLY)
    assert not missing, f"CONTRACTS.md section 3 defines {missing} but pipelines/tables.py has no DDL for them"


def test_every_ddl_table_is_in_contract():
    extra = sorted(set(tables.TABLE_NAMES) - set(CONTRACT))
    assert not extra, f"pipelines/tables.py defines {extra} but CONTRACTS.md section 3 does not"


def test_every_fixture_file_matches_a_contract_table():
    orphans = sorted(set(FIXTURE_FILES) - NON_TABLE_FIXTURES - set(CONTRACT))
    assert not orphans, f"demo/fixtures has {orphans} with no matching table in CONTRACTS.md section 3"


def test_every_ddl_table_has_a_fixture_file():
    missing = sorted(set(tables.TABLE_NAMES) - set(FIXTURE_FILES))
    assert not missing, f"tables {missing} have no demo/fixtures/<table>.json"


def test_every_contract_table_has_a_fixture_file():
    missing = sorted(set(CONTRACT) - set(FIXTURE_FILES) - CONTRACT_ONLY)
    assert not missing, f"CONTRACTS.md tables {missing} have no demo/fixtures/<table>.json"


@pytest.mark.parametrize("table", sorted(set(CONTRACT) & set(FIXTURE_FILES) - set(tables.TABLE_NAMES)))
def test_fixture_rows_of_contract_only_tables_use_contract_columns(table):
    bad = [r for r in _load(table) if not set(r) <= set(CONTRACT[table])]
    assert not bad, f"{table}.json has fields outside CONTRACTS.md: {sorted(set().union(*bad) - set(CONTRACT[table]))}"


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_columns_match_contract_names_and_order(table):
    assert tables.columns(table) == _contract_cols(table)


@pytest.mark.parametrize("table", sorted(EXPECTED_TYPES))
def test_column_types_match_expected(table):
    # pins the original eight tables; later tables are checked through tables.py by the fixture tests
    assert dict(tables.TABLES[table][0]) == EXPECTED_TYPES[table]


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_ddl_declares_every_column_with_its_type(table):
    ddl = tables.ddl(table)
    for col, typ in tables.TABLES[table][0]:
        assert f"\n  {col} {typ}" in ddl


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_primary_key_columns_exist(table):
    assert set(tables.TABLES[table][1]) <= set(tables.columns(table))


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_primary_key_matches_contract_marker(table):
    section = CONTRACTS.split("## 3.")[1]
    line = next((l for l in section.splitlines() if l.startswith(f"**`{table}`**")), None)
    assert line, f"no CONTRACTS.md section 3 line for {table}"
    marked = set(re.findall(r"`(\w+)` \(PK", line))
    # composite keys (legs, scenario_changes) are partly described in words, so only require inclusion
    assert marked <= set(tables.TABLES[table][1])


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_fixture_file_is_non_empty(table):
    assert _load(table), f"demo/fixtures/{table}.json is missing or empty"


@pytest.mark.parametrize("table,i,row", _fixture_cases(), ids=lambda v: v if isinstance(v, str) else None)
def test_fixture_row_has_only_contract_columns_and_all_required_ones(table, i, row):
    cols = set(tables.columns(table))
    required = {c for c in cols if (table, c) not in NULLABLE}
    assert set(row) <= cols, f"{table} fixture has fields outside the contract: {sorted(set(row) - cols)}"
    assert required <= set(row), f"{table} fixture row lacks required fields: {sorted(required - set(row))}"


@pytest.mark.parametrize("table,i,row", _fixture_cases(), ids=lambda v: v if isinstance(v, str) else None)
def test_fixture_row_values_match_column_types(table, i, row):
    types = dict(tables.TABLES[table][0])
    bad = [c for c, v in row.items()
           if c in types and not (v is None and (table, c) in NULLABLE) and not _conforms(v, types[c])]
    assert bad == []


@pytest.mark.parametrize("table", tables.TABLE_NAMES)
def test_fixture_primary_keys_are_unique(table):
    key = tables.TABLES[table][1]
    keys = [tuple(r.get(k) for k in key) for r in _load(table)]
    assert len(keys) == len(set(keys))
