"""Scenario as a full alternative fleet state (AGENTS.md section 7, pipelines slice 4)."""
from datetime import datetime, timedelta, timezone

FMT = "%Y-%m-%dT%H:%M:%SZ"


def shift(ts, days: int):
    if ts is None:
        return None
    d = datetime.strptime(ts, FMT).replace(tzinfo=timezone.utc) + timedelta(days=days)
    return d.strftime(FMT)


def apply_scenario(shipments: list[dict], legs: list[dict], changes: list[dict]) -> list[dict]:
    """Return every shipment with its legs, applying the scenario's changes.

    A change with delay_days shifts the ETA and every leg time by that many days. Changed
    shipments carry `changed = True` and `scenario_change` (the row); others are returned
    unshifted with `changed = False`. Inputs are not mutated.
    """
    by_ship = {c["shipment_id"]: c for c in changes}
    legs_by: dict[str, list[dict]] = {}
    for leg in sorted(legs, key=lambda l: (l["shipment_id"], l["seq"])):
        legs_by.setdefault(leg["shipment_id"], []).append(leg)
    out = []
    for s in shipments:
        c = by_ship.get(s["shipment_id"])
        sl = [dict(l) for l in legs_by.get(s["shipment_id"], [])]
        if not c:
            out.append({**s, "legs": sl, "changed": False, "scenario_change": None})
            continue
        d = int(c.get("delay_days") or 0)
        for l in sl:
            l["planned_start"] = shift(l["planned_start"], d)
            l["planned_end"] = shift(l["planned_end"], d)
        out.append({**s, "eta": shift(s["eta"], d), "legs": sl, "changed": True, "scenario_change": c})
    return out
