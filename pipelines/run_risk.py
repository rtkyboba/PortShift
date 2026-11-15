"""Run the risk job against the Delta tables: read shipments, legs and disruption_events, score, replace shipment_risk.

    python pipelines/run_risk.py --dry-run             # score demo/fixtures, print the SQL, touch nothing
    python pipelines/run_risk.py                       # needs DATABRICKS_HOST/TOKEN/WAREHOUSE_ID
    python pipelines/run_risk.py --now 2026-11-14T16:00:00Z

Also runs as a Databricks Job (Python script task), e.g. after each monitor run. This job is the only
writer of shipment_risk (CONTRACTS.md section 6). The table is replaced with INSERT OVERWRITE, a single
atomic Delta commit, so the app never reads an empty table mid-run. NOT yet run against a live warehouse.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db  # noqa: E402
import load_fixtures  # noqa: E402
import queries  # noqa: E402
import tables  # noqa: E402
from risk_job import score_fleet, ts  # noqa: E402

INPUTS = ("shipments", "legs", "disruption_events")


def overwrite_sql(rows):
    """INSERT OVERWRITE for shipment_risk; an empty fleet clears the table instead."""
    ins = load_fixtures.insert_sql("shipment_risk", rows)
    if ins is None:
        return f"DELETE FROM {tables.qualified('shipment_risk')}"
    return ins.replace("INSERT INTO ", "INSERT OVERWRITE ", 1)


def score(read, now):
    """`read(table) -> list of row dicts`. Returns the shipment_risk rows."""
    t = {name: read(name) for name in INPUTS}
    return score_fleet(t["shipments"], t["legs"], t["disruption_events"], now)


def run(cursor, now):
    rows = score(lambda name: db.fetch(cursor, queries.READERS[name]), now)
    cursor.execute(overwrite_sql(rows))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="ISO time; default is the current UTC time")
    a = ap.parse_args(argv)
    now = ts(a.now) if a.now else datetime.now(timezone.utc)
    if a.dry_run:
        rows = score(load_fixtures.load_rows, now)
        print(overwrite_sql(rows) + ";")
        return 0
    if not db.configured():
        print("DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_WAREHOUSE_ID are not all set; use --dry-run.")
        return 2
    with db.connect() as conn, conn.cursor() as cur:
        rows = run(cur, now)
    print(f"wrote {len(rows)} shipment_risk rows at {now:%Y-%m-%dT%H:%MZ}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
