"""Shared fixtures for the database-layer tests. Everything here is local (DuckDB + sqlglot)."""
import pathlib
import sys

import duckdb
import pytest
import sqlglot

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipelines"))
import load_fixtures  # noqa: E402
import tables  # noqa: E402


def to_duck(sql: str) -> str:
    """Spark/Databricks SQL -> DuckDB. Real transpilation, so Spark string-escape rules apply."""
    sql = sql.split("\nCOMMENT")[0]  # DuckDB has no table COMMENT clause
    out = sqlglot.transpile(sql.replace(" USING DELTA", ""), read="databricks", write="duckdb")[0]
    return out.replace("main.portshift.", "portshift.")


class Db:
    def __init__(self):
        self.con = duckdb.connect()
        self.con.execute("CREATE SCHEMA portshift")

    def run(self, sql):
        return self.con.execute(to_duck(sql))

    def rows(self, sql):
        cur = self.run(sql)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def create_tables(self):
        for stmt in tables.all_ddl():
            self.run(stmt)

    def write(self, table, rows):
        self.run(load_fixtures.insert_sql(table, rows))

    def load_fixtures(self):
        load_fixtures.run(lambda s: None if s.startswith("CREATE SCHEMA") else self.run(s))


@pytest.fixture()
def empty_db():
    """All eight tables created, no rows."""
    db = Db()
    db.create_tables()
    return db


@pytest.fixture()
def loaded_db():
    """All eight tables created and loaded from demo/fixtures."""
    db = Db()
    db.load_fixtures()
    return db


@pytest.fixture()
def fixtures_dir():
    return ROOT / "demo" / "fixtures"
