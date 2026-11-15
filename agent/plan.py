"""Plan options per shipment, and how the user's limits on risk and price pick one.

Deterministic. No LLM is involved in any number here. This is a greedy heuristic (a "suggested
plan"), not a solver: for each affected shipment it builds three options (keep, reschedule,
reroute), checks each against the user's limits, and recommends the cheapest one inside them.

Illustrative assumptions, labelled as such in every answer:
  * Costs: formulas over the cost_rates table (see cost.py).
  * Detours (extra km and extra hours of a reroute) come from the DETOURS table below, not from
    a routing engine.
  * Rescheduling pushes the shipment past the end of the disruption window plus one day.
  * After a reroute or a reschedule that clears the window, the event is off the route, so the
    resulting risk level is 1.
"""
import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from . import cost, store

RISK_NAMES = {1: "Clear", 2: "Watch", 3: "At risk", 4: "Severe", 5: "Critical"}

# (extra_km, extra_hours). Keys: mode, optionally narrowed by a word in the event location.
DETOURS = {
    ("ship", None): ("Reroute around the disruption", 650, 18),
    ("truck", None): ("Reroute via an alternative corridor", 140, 4),
    ("plane", None): ("Reroute via an alternate airport", 380, 3),
    ("ship", "suez"): ("Reroute via the Cape of Good Hope", 5900, 216),
    ("ship", "rotterdam"): ("Reroute via Antwerp (feeder to Rotterdam)", 90, 12),
    ("truck", "rotterdam"): ("Reroute via the Antwerp road corridor", 120, 5),
    ("truck", "calais"): ("Reroute via Zeebrugge", 210, 6),
}


@dataclass
class Preferences:
    """How much risk and price the user is happy to accept."""

    max_risk: int = 3  # highest resulting risk level accepted, 1 (Clear) to 5 (Critical)
    max_extra_cost: float | None = 5000.0  # most extra cost accepted, in EUR; None = no limit
    max_delay_hours: float | None = None  # most extra delay accepted; None = no limit

    @classmethod
    def from_dict(cls, d: dict | None) -> "Preferences":
        base = cls()
        if not d:
            return base

        def num(key, default):
            if key not in d:
                return default
            v = d[key]
            if v in (None, "", "none", "no limit"):
                return None
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                return default

        risk = d.get("max_risk", base.max_risk)
        try:
            risk = min(5, max(1, int(risk)))
        except (TypeError, ValueError):
            risk = base.max_risk
        return cls(max_risk=risk, max_extra_cost=num("max_extra_cost", base.max_extra_cost),
                   max_delay_hours=num("max_delay_hours", base.max_delay_hours))

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        cost_part = "no cost limit" if self.max_extra_cost is None else f"extra cost up to EUR {self.max_extra_cost:,.0f}"
        delay_part = "no delay limit" if self.max_delay_hours is None else f"extra delay up to {self.max_delay_hours:g} h"
        return f"risk up to level {self.max_risk} ({RISK_NAMES[self.max_risk]}), {cost_part}, {delay_part}"


def _t(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def _shipment(shipment_id: str, db: dict) -> dict:
    for s in db["shipments"]:
        if s["shipment_id"] == shipment_id:
            return s
    raise KeyError(f"unknown shipment {shipment_id}")


def _reach_time(shipment_id: str, event: dict, db: dict) -> tuple[datetime, datetime]:
    """When the shipment is planned to be at the point nearest the event, and its first leg start."""
    legs = sorted((l for l in db["legs"] if l["shipment_id"] == shipment_id), key=lambda l: l["seq"])
    target = (event["lat"], event["lon"])
    best = None
    for leg in legs:
        for lat, lon, when in ((leg["from_lat"], leg["from_lon"], leg["planned_start"]),
                               (leg["to_lat"], leg["to_lon"], leg["planned_end"])):
            d = _km((lat, lon), target)
            if best is None or d < best[0]:
                best = (d, _t(when))
    return best[1], _t(legs[0]["planned_start"])


def _detour(mode: str, location: str) -> tuple[str, float, float]:
    low = (location or "").lower()
    for (m, word), value in DETOURS.items():
        if m == mode and word and word in low:
            return value
    return DETOURS[(mode, None)]


def options_for(shipment_id: str, db: dict | None = None) -> dict:
    """The shipment, its primary event, and every option with cost, delay and resulting risk."""
    db = store.resolve(db)
    ship = _shipment(shipment_id, db)
    risk_row = next((r for r in db["shipment_risk"] if r["shipment_id"] == shipment_id),
                    {"level": 1, "reason": "No risk record", "event_ids": []})
    level = int(risk_row["level"])
    events = {e["event_id"]: e for e in db["disruption_events"]}
    event = next((events[i] for i in risk_row["event_ids"] if i in events), None)
    currency = next((r["currency"] for r in db["cost_rates"] if r["mode"] == ship["mode"]), "EUR")

    options = [{
        "id": "keep", "kind": "keep", "label": "Keep the current plan", "extra_cost": 0.0,
        "delay_hours": 0.0, "resulting_risk": level, "delay_days": 0, "extra_km": None,
        "new_planned_start": None, "detail": risk_row["reason"],
    }]
    if event is not None:
        reach, first_start = _reach_time(shipment_id, event, db)
        window_end = _t(event["window_end"])
        if reach <= window_end:
            days = math.ceil((window_end - reach).total_seconds() / 86400) + 1
            c = cost.reschedule_cost(shipment_id, days, db)
            options.append({
                "id": f"reschedule-{days}d", "kind": "reschedule", "label": f"Reschedule by {days} days",
                "extra_cost": c["cost"], "delay_hours": days * 24.0, "resulting_risk": 1,
                "delay_days": days, "extra_km": None,
                "new_planned_start": (first_start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "detail": f"Moves the shipment past the end of the {event['type']} window at "
                          f"{event['location']} ({event['window_end'][:10]}) plus one day.",
            })
        label, extra_km, hours = _detour(ship["mode"], event["location"])
        c = cost.reroute_cost(shipment_id, extra_km, db)
        options.append({
            "id": "reroute", "kind": "reroute", "label": label, "extra_cost": c["cost"],
            "delay_hours": float(hours), "resulting_risk": 1, "delay_days": 0, "extra_km": extra_km,
            "new_planned_start": None,
            "detail": f"Avoids {event['location']}: about {extra_km:,.0f} km extra and {hours:g} h later.",
        })
    return {"shipment": ship, "risk": level, "reason": risk_row["reason"], "event": event,
            "options": options, "currency": currency}


def evaluate(options: list[dict], prefs: Preferences) -> list[dict]:
    """Mark each option as inside or outside the user's limits, with the reasons."""
    out = []
    for o in options:
        violations = []
        if o["resulting_risk"] > prefs.max_risk:
            violations.append(f"risk level {o['resulting_risk']} is above your limit of {prefs.max_risk}")
        if prefs.max_extra_cost is not None and o["extra_cost"] > prefs.max_extra_cost:
            violations.append(f"extra cost EUR {o['extra_cost']:,.0f} is above your limit of EUR {prefs.max_extra_cost:,.0f}")
        if prefs.max_delay_hours is not None and o["delay_hours"] > prefs.max_delay_hours:
            violations.append(f"extra delay {o['delay_hours']:g} h is above your limit of {prefs.max_delay_hours:g} h")
        out.append({**o, "within_limits": not violations, "violations": violations})
    return out


def recommend(options: list[dict], prefs: Preferences) -> tuple[dict, str, list[dict]]:
    """Cheapest option inside the limits; if none fits, the least-bad one, flagged."""
    evaluated = evaluate(options, prefs)
    inside = [o for o in evaluated if o["within_limits"]]
    if inside:
        best = min(inside, key=lambda o: (o["extra_cost"], o["resulting_risk"], o["delay_hours"]))
        return best, ("no_action_needed" if best["kind"] == "keep" else "within_limits"), evaluated
    best = min(evaluated, key=lambda o: (len(o["violations"]), o["resulting_risk"], o["extra_cost"]))
    return best, "outside_limits", evaluated


def suggest_plan(shipment_ids: list[str] | None = None, prefs: Preferences | None = None,
                 db: dict | None = None) -> dict:
    """Plan for the given shipments (default: every shipment with a disruption)."""
    db = store.resolve(db)
    prefs = prefs or Preferences()
    if not shipment_ids:
        shipment_ids = sorted(r["shipment_id"] for r in db["shipment_risk"] if int(r["level"]) > 1)
    rows, changes, total = [], [], 0.0
    seed = ",".join(sorted(shipment_ids)) + repr(sorted(prefs.to_dict().items()))
    scenario_id = "SC-" + hashlib.sha1(seed.encode()).hexdigest()[:8]
    for sid in shipment_ids:
        info = options_for(sid, db)
        best, status, evaluated = recommend(info["options"], prefs)
        ship = info["shipment"]
        rows.append({
            "shipment_id": sid, "mode": ship["mode"], "origin": ship["origin"],
            "destination": ship["destination"], "cargo": ship["cargo"], "current_risk": info["risk"],
            "reason": info["reason"], "event": info["event"], "options": evaluated,
            "recommended_id": best["id"], "status": status,
        })
        if best["kind"] != "keep":
            total += best["extra_cost"]
            changes.append({
                "scenario_id": scenario_id, "shipment_id": sid, "change_type": best["kind"],
                "delay_days": best["delay_days"], "new_planned_start": best["new_planned_start"],
                "extra_km": best["extra_km"], "cost_delta": best["extra_cost"], "note": best["label"],
            })
    scenario = {
        "scenario_id": scenario_id,
        "label": f"Suggested plan for {len(shipment_ids)} shipment(s)",
        "status": "tentative",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cost_delta": round(total, 2), "currency": "EUR",
    }
    return {"scenario": scenario, "changes": changes, "shipments": rows,
            "preferences": prefs.to_dict(), "currency": "EUR"}
