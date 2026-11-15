"""Reader SQL for the app (app/data.py mirrors these) and the scenario query.

Rows come back exactly as CONTRACTS.md section 3. Plain SELECTs, Spark/Databricks SQL.
"""
from tables import TABLE_NAMES, columns, qualified

ORDER = {
    "shipments": "shipment_id",
    "legs": "shipment_id, seq",
    "disruption_events": "event_id",
    "evidence": "event_id, evidence_id",
    "shipment_risk": "shipment_id",
    "cost_rates": "mode",
    "scenarios": "created_at DESC, scenario_id",
    "scenario_changes": "scenario_id, shipment_id",
    "rate_cards": "rate_id",
    "surcharges": "mode, code",
    "delay_charges": "mode, unit, partner",
    "shipment_terms": "shipment_id",
    "warehouse_stock": "warehouse, stock_id",
    "dispatch_orders": "submitted_at DESC, order_id",
    "dispatch_lines": "order_id, stock_id",
}


def reader(table: str) -> str:
    """One reader per table: all contract columns, deterministic order."""
    return f"SELECT {', '.join(columns(table))} FROM {qualified(table)} ORDER BY {ORDER[table]}"


READERS = {t: reader(t) for t in TABLE_NAMES}


def lit(value) -> str:
    """Escape a string literal for Spark SQL: backslash and quote are backslash-escaped.
    Not '' (that is adjacent-literal concatenation in Spark, which silently drops the quote)."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def scenario_rows(scenario_id: str) -> str:
    """A scenario as a full alternative fleet: every shipment with its base risk and, when the
    scenario changes it, the change columns (NULL otherwise). Legs are shifted in Python by
    scenario.apply_scenario so date arithmetic stays out of the SQL."""
    return f"""SELECT s.shipment_id, s.cargo, s.origin, s.destination, s.mode, s.eta, s.is_demo_fleet,
       r.level, r.reason, r.event_ids,
       c.change_type, c.delay_days, c.new_planned_start, c.cost_delta, c.note, c.extra_km
FROM {qualified('shipments')} s
LEFT JOIN {qualified('shipment_risk')} r ON r.shipment_id = s.shipment_id
LEFT JOIN {qualified('scenario_changes')} c
  ON c.shipment_id = s.shipment_id AND c.scenario_id = {lit(scenario_id)}
ORDER BY s.shipment_id"""
