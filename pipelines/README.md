# pipelines/ (issue #8: tables, loader, readers, scenarios)

- `tables.py`: Delta schemas from CONTRACTS.md section 3 and the DDL (`all_ddl()`).
- `load_fixtures.py`: creates the tables and loads `demo/fixtures/*.json` (`--dry-run` prints the SQL; `--tables` limits it). Needs `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID` and `databricks-sql-connector`. Catalog/schema: `DATABRICKS_CATALOG` (default `main`), `DATABRICKS_SCHEMA` (default `portshift`). Runs as a Job Python task.
- `queries.py`: one reader per table (`READERS`) and `scenario_rows(id)`; `app/data.py` runs the same SELECTs.
- `scenario.py`: `apply_scenario(shipments, legs, changes)` returns the full alternative fleet state.
- Tests: `python -m pytest pipelines` runs the DDL, loader and readers in DuckDB through sqlglot, no Databricks needed.
