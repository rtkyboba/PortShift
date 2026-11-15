"""Rows for the agent, from the same source as the app (fixtures or Databricks).

Reuses app/data.py so there is exactly one place that knows where data lives. Pass a plain
dict of tables (`{"shipments": [...], ...}`) to any agent function to bypass it (tests).
"""
import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TABLES = ("shipments", "legs", "disruption_events", "evidence", "shipment_risk", "cost_rates")
_mod = None


def _app_data():
    global _mod
    if _mod is None:
        spec = importlib.util.spec_from_file_location("portshift_app_data", _ROOT / "app" / "data.py")
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
    return _mod


def snapshot() -> dict:
    data = _app_data()
    return {t: data._rows(t) for t in _TABLES}


def resolve(db: dict | None) -> dict:
    return db if db is not None else snapshot()
