"""Create the Delta tables from CONTRACTS.md and load demo/fixtures into them.

    python pipelines/load_fixtures.py             # needs DATABRICKS_HOST/TOKEN/WAREHOUSE_ID
    python pipelines/load_fixtures.py --dry-run   # print the SQL, touch nothing
    python pipelines/load_fixtures.py --tables shipments legs

Also runs as a Databricks Job (Python script task). Each listed table is replaced with its
fixture rows (all samples, is_fixture = true), so do not include tables the monitor writes
live (disruption_events, evidence) once real data exists: use --tables to limit.
Catalog and schema: DATABRICKS_CATALOG (default main), DATABRICKS_SCHEMA (default portshift).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import tables  # noqa: E402
from queries import lit  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "demo" / "fixtures"


def literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "array(" + ", ".join(literal(x) for x in v) + ")"
    return lit(v)


def load_rows(table: str, fixtures: pathlib.Path = FIXTURES) -> list[dict]:
    return json.loads((fixtures / f"{table}.json").read_text())


def insert_sql(table: str, rows: list[dict]):
    if not rows:
        return None
    cols = tables.columns(table)
    unknown = {k for r in rows for k in r} - set(cols)
    if unknown:
        raise ValueError(f"{table}: fixture fields not in contract: {sorted(unknown)}")
    values = ",\n  ".join("(" + ", ".join(literal(r.get(c)) for c in cols) + ")" for r in rows)
    return f"INSERT INTO {tables.qualified(table)} ({', '.join(cols)}) VALUES\n  {values}"


def statements(only=None, fixtures: pathlib.Path = FIXTURES) -> list[str]:
    names = only or tables.TABLE_NAMES
    out = [tables.create_schema_sql()]
    out += [tables.ddl(t) for t in names]
    for t in names:
        out.append(f"DELETE FROM {tables.qualified(t)}")
        ins = insert_sql(t, load_rows(t, fixtures))
        if ins:
            out.append(ins)
    return out


def run(execute, only=None, fixtures=FIXTURES) -> int:
    stmts = statements(only, fixtures)
    for s in stmts:
        execute(s)
    return len(stmts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tables", nargs="*", choices=tables.TABLE_NAMES)
    a = ap.parse_args(argv)
    if a.dry_run:
        print(";\n\n".join(statements(a.tables)) + ";")
        return 0
    import db
    if not db.configured():
        print("DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_WAREHOUSE_ID are not all set; use --dry-run.")
        return 2
    with db.connect() as conn, conn.cursor() as cur:
        n = run(cur.execute, a.tables)
    print(f"ran {n} statements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
