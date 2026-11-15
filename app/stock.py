"""Warehouse stock and dispatch: allocate stock to a shipment, plan it, submit it to the warehouse.

  * warehouse_stock  - what each warehouse holds. In production a stockpile manager supplies it; the demo rows
                       are samples (is_sample) and the UI says so.
  * plan()           - the operator picks quantities from one warehouse's stock and where they go. The allocation
                       is checked against what is available, turned into a cargo (pallets and weight), and
                       planner.py suggests routes for it, priced and risk-scored like any planned shipment.
  * submit()         - records a dispatch order and its lines for that warehouse and takes the quantities out of
                       what is available. Availability is checked again at this moment.

Orders are written to the Delta tables when Databricks is configured (through the agent's sink, the same writer
the monitor uses); otherwise they are held in this process, like submitted decisions. Nothing is sent to a carrier
and no warehouse system is contacted: "submitted to the warehouse" means the order is in the dispatch table for
that warehouse to pick up.
"""
import sys
from datetime import datetime, timezone

import costing
import data
import planner

ORDERS: list[dict] = []   # orders submitted in this process (when not writing to Delta)
LINES: list[dict] = []
STATUSES = ("submitted", "acknowledged", "picked", "dispatched")


def _orders() -> tuple[list[dict], list[dict]]:
    base_o, base_l = data.optional_rows("dispatch_orders"), data.optional_rows("dispatch_lines")
    have = {o["order_id"] for o in base_o}
    return base_o + [o for o in ORDERS if o["order_id"] not in have], base_l + [l for l in LINES if l["order_id"] not in have]


def _stock() -> list[dict]:
    """Stock rows with what is still available: quantity, less what the table says is reserved, less what
    orders submitted here have taken."""
    taken: dict[str, int] = {}
    for l in LINES:
        taken[l["stock_id"]] = taken.get(l["stock_id"], 0) + int(l["quantity"])
    out = []
    for r in data.optional_rows("warehouse_stock"):
        reserved = int(r["reserved"]) + taken.get(r["stock_id"], 0)
        out.append({**r, "reserved": reserved, "available": max(0, int(r["quantity"]) - reserved)})
    return out


def view() -> dict:
    stock, (orders, lines) = _stock(), _orders()
    places = {p["name"]: p for p in planner.PLACES}
    by_wh: dict[str, list] = {}
    for r in stock:
        by_wh.setdefault(r["warehouse"], []).append(r)
    orders = sorted(orders, key=lambda o: o["submitted_at"], reverse=True)
    return {
        "warehouses": [{"warehouse": w, "place": places.get(w), "lines": rows,
                        "pallets_available": sum(r["available"] for r in rows),
                        "updated_at": max(r["updated_at"] for r in rows)} for w, rows in sorted(by_wh.items())],
        "orders": [{**o, "lines": [l for l in lines if l["order_id"] == o["order_id"]]} for o in orders],
        "is_sample": any(r.get("is_sample") for r in stock),
        "stored": "Delta tables" if data.use_databricks() else "this app's memory (lost on restart)",
        "note": "Sample stock: no stockpile manager is connected, so these rows stand in for its feed. Submitting records a "
                "dispatch order for the warehouse; nothing is sent to a carrier or to a warehouse system.",
    }


def _allocate(warehouse: str, wanted: list[dict]) -> tuple[list[dict], list[str]]:
    """The requested lines checked against the warehouse's stock: (allocation, problems)."""
    stock = {r["stock_id"]: r for r in _stock() if r["warehouse"] == warehouse}
    lines, problems = [], []
    for w in wanted or []:
        try:
            qty = int(w.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        row = stock.get(w.get("stock_id"))
        if not row:
            problems.append(f"{w.get('stock_id')} is not a stock line at {warehouse}.")
        elif qty > row["available"]:
            problems.append(f"{row['item']}: {qty} {row['unit']}s asked for, {row['available']} available.")
        else:
            lines.append({"stock_id": row["stock_id"], "sku": row["sku"], "item": row["item"], "quantity": qty,
                          "unit": row["unit"], "kg": round(qty * row["kg_per_unit"], 1), "left_after": row["available"] - qty})
    if not lines and not problems:
        problems.append("Choose at least one stock line and a quantity to send.")
    return lines, problems


def _cargo(lines: list[dict]) -> dict:
    return {"units": sum(l["quantity"] for l in lines), "unit_type": "pallet", "weight_kg": round(sum(l["kg"] for l in lines), 1)}


def plan(warehouse: str, stops: list[dict], wanted: list[dict], preferences: dict | None = None,
         depart_at: str | None = None, own_places: list[dict] | None = None) -> dict:
    """Routes for sending the chosen stock from the warehouse through the stops. Nothing is recorded."""
    origin = next((p for p in planner.PLACES if p["name"] == warehouse and p["kind"] == "warehouse"), None)
    lines, problems = _allocate(warehouse, wanted)
    if origin is None:
        problems.append(f"{warehouse} is not a warehouse PortShift knows.")
    if not stops:
        problems.append("Say where the stock is going.")
    if problems or origin is None:
        return {"warehouse": warehouse, "allocation": lines, "problems": problems, "routes": [], "recommended_id": None}
    cargo = _cargo(lines)
    res = planner.suggest([origin, *stops], ["truck"] * len(stops), depart_at, preferences, own_places, cargo)
    routes = [r for r in res["routes"] if not r["problems"]] or res["routes"]
    best = res["recommended_id"] if any(r["id"] == res["recommended_id"] for r in routes) else routes[0]["id"]
    return {"warehouse": warehouse, "destination": stops[-1]["name"], "stops": [origin["name"], *[s["name"] for s in stops]],
            "allocation": lines, "cargo": cargo, "problems": [], "routes": routes, "recommended_id": best,
            "depart_at": res["depart_at"], "currency": costing.CURRENCY, "notes": res["notes"]}


def submit(warehouse: str, wanted: list[dict], route: dict, stops: list[str]) -> dict:
    """Record the dispatch order for the warehouse. Raises ValueError when the stock is no longer there."""
    lines, problems = _allocate(warehouse, wanted)
    if problems:
        raise ValueError(" ".join(problems))
    if not route.get("legs"):
        raise ValueError("The order needs the route it was planned on.")
    existing, _ = _orders()
    order_id = f"DO-{1001 + len(existing)}"
    order = {"order_id": order_id, "warehouse": warehouse, "destination": stops[-1] if stops else route["legs"][-1]["to_name"],
             "stops": [str(s) for s in stops] or [route["legs"][0]["from_name"], *[l["to_name"] for l in route["legs"]]],
             "route_label": str(route.get("label") or ""), "status": "submitted",
             "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "depart_at": route["legs"][0]["planned_start"], "eta": route.get("eta") or route["legs"][-1]["planned_end"],
             "cost": float(route.get("cost") or 0), "currency": route.get("currency") or costing.CURRENCY, "is_sample": False}
    rows = [{"order_id": order_id, "stock_id": l["stock_id"], "sku": l["sku"], "item": l["item"], "quantity": l["quantity"], "unit": l["unit"]}
            for l in lines]
    stored = "this app's memory"
    if data.use_databricks():
        try:  # Delta is the durable home: write the order, its lines, and the new reserved quantities
            root = str(data._here.parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            from agent import sink
            target = sink.DatabricksSink()
            target.write("dispatch_orders", [order])
            target.write("dispatch_lines", rows)
            current = {r["stock_id"]: r for r in data.optional_rows("warehouse_stock")}
            target.write("warehouse_stock", [{**current[l["stock_id"]], "reserved": int(current[l["stock_id"]]["reserved"]) + l["quantity"],
                                              "updated_at": order["submitted_at"]} for l in lines])  # a reservation changes the stock row
            stored = "Delta tables"
        except Exception:
            stored = "this app's memory (the Delta write failed)"
    if stored != "Delta tables":
        ORDERS.append(order)
        LINES.extend(rows)
    return {**order, "lines": rows, "legs": route["legs"], "stored": stored}
