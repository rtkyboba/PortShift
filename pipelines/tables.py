"""Delta table schemas, copied from CONTRACTS.md section 3 (single source for DDL and the loader).

Timestamps are STRING (ISO 8601 UTC) exactly as in the contract and fixtures, so rows
round-trip unchanged and sort correctly. Arrays: geometry is ARRAY<ARRAY<DOUBLE>>
([lat, lon] pairs), event_ids is ARRAY<STRING>.
"""
import os

# table -> (ordered [(column, spark type)], primary key columns)
TABLES: dict[str, tuple[list[tuple[str, str]], list[str]]] = {
    "shipments": ([
        ("shipment_id", "STRING"), ("cargo", "STRING"), ("origin", "STRING"),
        ("destination", "STRING"), ("mode", "STRING"), ("eta", "STRING"),
        ("is_demo_fleet", "BOOLEAN")], ["shipment_id"]),
    "legs": ([
        ("shipment_id", "STRING"), ("seq", "INT"), ("mode", "STRING"),
        ("from_name", "STRING"), ("from_lat", "DOUBLE"), ("from_lon", "DOUBLE"),
        ("to_name", "STRING"), ("to_lat", "DOUBLE"), ("to_lon", "DOUBLE"),
        ("geometry", "ARRAY<ARRAY<DOUBLE>>"),
        ("planned_start", "STRING"), ("planned_end", "STRING")], ["shipment_id", "seq"]),
    "disruption_events": ([
        ("event_id", "STRING"), ("type", "STRING"), ("status", "STRING"),
        ("location", "STRING"), ("lat", "DOUBLE"), ("lon", "DOUBLE"), ("radius_km", "DOUBLE"),
        ("window_start", "STRING"), ("window_end", "STRING"), ("summary", "STRING"),
        ("detected_at", "STRING"), ("is_fixture", "BOOLEAN")], ["event_id"]),
    "evidence": ([
        ("evidence_id", "STRING"), ("event_id", "STRING"), ("claim", "STRING"),
        ("url", "STRING"), ("title", "STRING"), ("retrieved_at", "STRING"),
        ("published_at", "STRING"), ("domain", "STRING"), ("is_official", "BOOLEAN")],
        ["evidence_id"]),
    "shipment_risk": ([
        ("shipment_id", "STRING"), ("level", "INT"), ("reason", "STRING"),
        ("event_ids", "ARRAY<STRING>")], ["shipment_id"]),
    "cost_rates": ([
        ("mode", "STRING"), ("per_delay_day", "DOUBLE"), ("rebooking_fee", "DOUBLE"),
        ("per_extra_km", "DOUBLE"), ("currency", "STRING")], ["mode"]),
    "scenarios": ([
        ("scenario_id", "STRING"), ("label", "STRING"), ("status", "STRING"),
        ("created_at", "STRING"), ("cost_delta", "DOUBLE"), ("currency", "STRING")],
        ["scenario_id"]),
    "scenario_changes": ([
        ("scenario_id", "STRING"), ("shipment_id", "STRING"), ("change_type", "STRING"),
        ("delay_days", "INT"), ("new_planned_start", "STRING"), ("cost_delta", "DOUBLE"),
        ("note", "STRING"), ("extra_km", "DOUBLE")], ["scenario_id", "shipment_id"]),
    # Costing (app/costing.py). An empty string means "any" (partner, lane, unit, validity date).
    "rate_cards": ([
        ("rate_id", "STRING"), ("partner", "STRING"), ("mode", "STRING"), ("origin", "STRING"),
        ("destination", "STRING"), ("unit", "STRING"), ("base_rate", "DOUBLE"), ("per_km", "DOUBLE"),
        ("min_charge", "DOUBLE"), ("currency", "STRING"), ("valid_from", "STRING"), ("valid_to", "STRING"),
        ("source", "STRING"), ("note", "STRING")], ["rate_id"]),
    "surcharges": ([
        ("code", "STRING"), ("mode", "STRING"), ("label", "STRING"), ("partner", "STRING"),
        ("basis", "STRING"), ("value", "DOUBLE"), ("applies_to_units", "ARRAY<STRING>"),
        ("source", "STRING")], ["code", "mode"]),
    "delay_charges": ([
        ("mode", "STRING"), ("unit", "STRING"), ("partner", "STRING"), ("label", "STRING"),
        ("free_days", "INT"), ("per_unit_per_day", "DOUBLE"), ("rebooking_fee", "DOUBLE"),
        ("source", "STRING")], ["mode", "unit", "partner"]),
    "shipment_terms": ([
        ("shipment_id", "STRING"), ("carrier", "STRING"), ("units", "DOUBLE"), ("unit_type", "STRING"),
        ("weight_kg", "DOUBLE"), ("volume_m3", "DOUBLE"), ("promised_by", "STRING"),
        ("late_penalty_per_day", "DOUBLE")], ["shipment_id"]),
    # Warehouse stock and dispatch (app/stock.py). The stock rows are what a stockpile manager would supply.
    "warehouse_stock": ([
        ("stock_id", "STRING"), ("warehouse", "STRING"), ("sku", "STRING"), ("item", "STRING"),
        ("quantity", "INT"), ("unit", "STRING"), ("kg_per_unit", "DOUBLE"), ("reserved", "INT"),
        ("updated_at", "STRING"), ("is_sample", "BOOLEAN")], ["stock_id"]),
    "dispatch_orders": ([
        ("order_id", "STRING"), ("warehouse", "STRING"), ("destination", "STRING"), ("stops", "ARRAY<STRING>"),
        ("route_label", "STRING"), ("status", "STRING"), ("submitted_at", "STRING"), ("depart_at", "STRING"),
        ("eta", "STRING"), ("cost", "DOUBLE"), ("currency", "STRING"), ("is_sample", "BOOLEAN")], ["order_id"]),
    "dispatch_lines": ([
        ("order_id", "STRING"), ("stock_id", "STRING"), ("sku", "STRING"), ("item", "STRING"),
        ("quantity", "INT"), ("unit", "STRING")], ["order_id", "stock_id"]),
}

TABLE_NAMES = list(TABLES)


def columns(table: str) -> list[str]:
    return [c for c, _ in TABLES[table][0]]


def _cat_sch() -> tuple[str, str]:
    return os.environ.get("DATABRICKS_CATALOG", "main"), os.environ.get("DATABRICKS_SCHEMA", "portshift")


def qualified(table: str) -> str:
    """catalog.schema.table; override with DATABRICKS_CATALOG / DATABRICKS_SCHEMA."""
    return "{}.{}.{}".format(*_cat_sch(), table)


def create_schema_sql() -> str:
    return "CREATE SCHEMA IF NOT EXISTS {}.{}".format(*_cat_sch())


def ddl(table: str) -> str:
    cols = ",\n  ".join(f"{c} {t}" for c, t in TABLES[table][0])
    pk = ", ".join(TABLES[table][1])
    return (f"CREATE TABLE IF NOT EXISTS {qualified(table)} (\n  {cols}\n) USING DELTA\n"
            f"COMMENT 'PortShift {table}; primary key ({pk}); see CONTRACTS.md section 3'")


def all_ddl() -> list[str]:
    return [ddl(t) for t in TABLE_NAMES]
