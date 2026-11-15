"""Cost formulas over the cost_rates table. Never produced by an LLM.

reschedule_cost = delay_days * per_delay_day + rebooking_fee
reroute_cost    = extra_km * per_extra_km + rebooking_fee
All figures are estimates from illustrative rates.
"""
from . import store


def _shipment(shipment_id: str, db: dict) -> dict:
    for s in db["shipments"]:
        if s["shipment_id"] == shipment_id:
            return s
    raise KeyError(f"unknown shipment {shipment_id}")


def _rate(mode: str, db: dict) -> dict:
    for r in db["cost_rates"]:
        if r["mode"] == mode:
            return r
    raise KeyError(f"no cost rate for mode {mode}")


def reschedule_cost(shipment_id: str, delay_days: int, db: dict | None = None) -> dict:
    db = store.resolve(db)
    rate = _rate(_shipment(shipment_id, db)["mode"], db)
    delay = delay_days * rate["per_delay_day"]
    return {
        "cost": round(delay + rate["rebooking_fee"], 2),
        "currency": rate["currency"],
        "breakdown": {"delay_days": delay_days, "delay": delay, "rebooking_fee": rate["rebooking_fee"]},
    }


def reroute_cost(shipment_id: str, extra_km: float, db: dict | None = None) -> dict:
    db = store.resolve(db)
    rate = _rate(_shipment(shipment_id, db)["mode"], db)
    distance = extra_km * rate["per_extra_km"]
    return {
        "cost": round(distance + rate["rebooking_fee"], 2),
        "currency": rate["currency"],
        "breakdown": {"extra_km": extra_km, "distance": round(distance, 2), "rebooking_fee": rate["rebooking_fee"]},
    }
