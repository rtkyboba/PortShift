"""run_risk wiring tests with a fake cursor (stdlib only; no Databricks, no DuckDB).
Run: python3 -m unittest pipelines/test_run_risk.py"""
import sys, unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import load_fixtures  # noqa: E402
import queries  # noqa: E402
import run_risk  # noqa: E402

NOW = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)


class FakeCursor:
    """Answers the reader SQL from demo/fixtures and records every statement it is given."""
    def __init__(self):
        self.executed, self.description, self._rows = [], None, []

    def execute(self, sql):
        self.executed.append(sql)
        for table, q in queries.READERS.items():
            if sql == q:
                data = load_fixtures.load_rows(table)
                cols = list(data[0])
                self.description = [(c,) for c in cols]
                self._rows = [tuple(r[c] for c in cols) for r in data]

    def fetchall(self):
        return self._rows


class RunRisk(unittest.TestCase):
    def test_reads_three_inputs_and_overwrites_shipment_risk_once(self):
        cur = FakeCursor()
        rows = run_risk.run(cur, NOW)
        reads = [s for s in cur.executed if s.startswith("SELECT")]
        self.assertEqual(len(reads), 3)
        self.assertTrue(all("shipment_risk" not in s for s in reads))
        writes = [s for s in cur.executed if not s.startswith("SELECT")]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].startswith("INSERT OVERWRITE main.portshift.shipment_risk"), writes[0][:80])
        self.assertEqual(len(rows), 14)

    def test_sql_contains_every_shipment_and_array_literals(self):
        sql = run_risk.overwrite_sql(run_risk.score(load_fixtures.load_rows, NOW))
        for sid in ("S-1001", "S-1006"):
            self.assertIn(f"'{sid}'", sql)
        self.assertIn("array(", sql)

    def test_empty_fleet_clears_instead_of_inserting(self):
        self.assertTrue(run_risk.overwrite_sql([]).startswith("DELETE FROM"))

    def test_dry_run_touches_nothing_and_prints_sql(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(run_risk.main(["--dry-run", "--now", "2026-11-14T16:00:00Z"]), 0)
        self.assertIn("INSERT OVERWRITE", buf.getvalue())

    def test_without_credentials_exits_2(self):
        import os
        for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"):
            os.environ.pop(k, None)
        self.assertEqual(run_risk.main([]), 2)


if __name__ == "__main__":
    unittest.main()
