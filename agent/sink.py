"""Where the monitor writes events and evidence.

DatabricksSink: upserts into the Delta tables (DELETE by key, then INSERT) when DATABRICKS_HOST,
DATABRICKS_TOKEN and DATABRICKS_WAREHOUSE_ID are set. Reuses pipelines/ for the table schema, the
SQL literals and the connection.
JsonDirSink: otherwise writes fixture-shaped JSON files to a local folder, seeded from demo/fixtures
so the app can read them: run the app with PORTSHIFT_FIXTURES=<that folder>.
"""
import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pipelines():
    path = str(ROOT / "pipelines")
    if path not in sys.path:
        sys.path.insert(0, path)
    import db
    import load_fixtures
    import tables
    return db, load_fixtures, tables


class JsonDirSink:
    def __init__(self, directory: str | os.PathLike | None = None, seed: pathlib.Path | None = None):
        self.dir = pathlib.Path(directory or os.environ.get("PORTSHIFT_LIVE_DIR") or ROOT / ".portshift_live")
        seed = seed or ROOT / "demo" / "fixtures"
        self.dir.mkdir(parents=True, exist_ok=True)
        if not any(self.dir.glob("*.json")):
            for f in seed.glob("*.json"):
                shutil.copy(f, self.dir / f.name)

    def write(self, table: str, rows: list[dict], key: list[str]) -> int:
        path = self.dir / f"{table}.json"
        existing = json.loads(path.read_text()) if path.exists() else []
        index = {tuple(r.get(k) for k in key): i for i, r in enumerate(existing)}
        for row in rows:
            k = tuple(row.get(c) for c in key)
            if k in index:
                existing[index[k]] = row
            else:
                index[k] = len(existing)
                existing.append(row)
        path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
        return len(rows)

    def describe(self) -> str:
        return f"local files in {self.dir} (run the app with PORTSHIFT_FIXTURES={self.dir})"


class DatabricksSink:
    def __init__(self, execute=None):
        self._execute = execute  # injectable for tests: execute(sql)

    def statements(self, table: str, rows: list[dict]) -> list[str]:
        _, load_fixtures, tables = _pipelines()
        if not rows:
            return []
        pk = tables.TABLES[table][1]
        stmts = []
        if len(pk) == 1:
            values = ", ".join(load_fixtures.literal(r[pk[0]]) for r in rows)
            stmts.append(f"DELETE FROM {tables.qualified(table)} WHERE {pk[0]} IN ({values})")
        else:
            for r in rows:
                cond = " AND ".join(f"{k} = {load_fixtures.literal(r[k])}" for k in pk)
                stmts.append(f"DELETE FROM {tables.qualified(table)} WHERE {cond}")
        stmts.append(load_fixtures.insert_sql(table, rows))
        return stmts

    def write(self, table: str, rows: list[dict], key: list[str] | None = None) -> int:
        stmts = self.statements(table, rows)
        if not stmts:
            return 0
        if self._execute is not None:
            for s in stmts:
                self._execute(s)
        else:
            db, _, _ = _pipelines()
            with db.connect() as conn, conn.cursor() as cur:
                for s in stmts:
                    cur.execute(s)
        return len(rows)

    def describe(self) -> str:
        return "Databricks Delta tables"


def default_sink():
    try:
        db, _, _ = _pipelines()
        if db.configured():
            return DatabricksSink()
    except Exception:
        pass
    return JsonDirSink()
