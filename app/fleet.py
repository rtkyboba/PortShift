"""Plan the whole fleet on request, and hand the result back for approval.

The operator says what they want ("optimise everything for the least cost"). The agent then works through
every affected shipment, highest risk first: it builds the options, prices them from the rate tables, checks
them against the operator's limits, picks one per shipment for the stated goal, and keeps to a fleet budget
when one is given. It returns one proposal and the list of what it did. Nothing is written or booked here:
a change only becomes a (tentative) decision when the operator approves it.

A greedy heuristic, shipment by shipment, not a solver: the UI calls the result a suggested plan.
No model produces a figure, a risk level or a choice.
"""
import data

GOALS = {
    "balanced": ("Balanced", "the cheapest option that stays inside your limits"),
    "low_cost": ("Least cost", "the cheapest option that stays inside your limits"),
    "low_risk": ("Least risk", "the lowest risk, then the least delay, then the least cost"),
}
NAMES = {0: "Not scored", 1: "Clear", 2: "Watch", 3: "At risk", 4: "Severe", 5: "Critical"}


def _pick(options: list[dict], goal: str) -> tuple[dict, str]:
    inside = [o for o in options if o["within_limits"]]
    pool = inside or options
    if goal == "low_risk":
        best = min(pool, key=lambda o: (o["resulting_risk"], o["delay_hours"], o["extra_cost"]))
    else:
        best = min(pool, key=lambda o: (o["extra_cost"], o["resulting_risk"], o["delay_hours"])) if inside else \
            min(pool, key=lambda o: (len(o["violations"]), o["resulting_risk"], o["extra_cost"]))
    if not inside:
        return best, "No option fits your limits; this one breaks the fewest. It needs your call."
    if best["kind"] == "keep":
        return best, "The current plan is already inside your limits, so nothing changes."
    return best, f"Chosen for {GOALS[goal][0].lower()}: {GOALS[goal][1]}."


def _limits_text(p: dict) -> str:
    cost = "any cost" if p["max_extra_cost"] is None else f"up to EUR {p['max_extra_cost']:,.0f} extra per shipment"
    delay = "any delay" if p["max_delay_hours"] is None else f"up to {p['max_delay_hours']:g} h delay"
    return f"risk up to {p['max_risk']} {NAMES[p['max_risk']]}, {cost}, {delay}"


def plan_all(preferences: dict | None = None, goal: str = "balanced", max_total_cost: float | None = None) -> dict:
    goal = goal if goal in GOALS else "balanced"
    p = data._limits(preferences)
    ships = data.shipments()
    events = {e["event_id"]: e for e in data._rows("disruption_events")}
    affected = sorted((s for s in ships if (s["risk"]["level"] or 0) >= 2),
                      key=lambda s: (-(s["risk"]["level"] or 0), s["impact_at"] or "9999", s["shipment_id"]))
    rows, spent, n_options, own = [], 0.0, 0, False
    for s in affected:
        o = data.options(s["shipment_id"], p)
        n_options += len(o["options"])
        choice, why = _pick(o["options"], goal)
        if max_total_cost is not None and spent + choice["extra_cost"] > max_total_cost:
            fits = [x for x in o["options"] if spent + x["extra_cost"] <= max_total_cost]
            cheaper, _ = _pick(fits, goal) if fits else (next(x for x in o["options"] if x["kind"] == "keep"), "")
            why = (f"The fleet budget of EUR {max_total_cost:,.0f} would be passed by \"{choice['label']}\" "
                   f"(EUR {choice['extra_cost']:,.0f}), so this is the best that still fits.")
            choice = cheaper
        spent += choice["extra_cost"]
        own = own or choice.get("cost_basis") in ("operator", "mixed")
        linked = [events[i] for i in s["risk"]["event_ids"] if i in events]
        rows.append({
            "shipment_id": s["shipment_id"], "origin": s["origin"], "destination": s["destination"], "mode": s["mode"],
            "cargo": s["cargo"], "eta": s["eta"], "current_risk": s["risk"]["level"], "reason": s["risk"]["reason"],
            "events": [{"event_id": e["event_id"], "type": e["type"], "location": e["location"], "status": e["status"],
                        "is_fixture": e["is_fixture"]} for e in linked],
            "choice": choice, "why": why, "options_considered": len(o["options"]),
            "status": "no_change" if choice["kind"] == "keep" and choice["within_limits"] else
                      "change" if choice["within_limits"] else "needs_your_call"})
    changes = [r for r in rows if r["status"] == "change"]
    calls = [r for r in rows if r["status"] == "needs_your_call"]
    steps = [
        {"text": f"Read {len(ships)} shipments and {len(events)} disruptions with their sources",
         "detail": f"{len(ships) - len(affected)} shipments are clear and are left alone"},
        {"text": f"Found {len(affected)} shipments at Watch or above",
         "detail": "worked through them highest risk first, then soonest disruption"},
        {"text": f"Built and priced {n_options} options: keep, reschedule or reroute",
         "detail": "prices looked up in the rate tables" + (", your own rates where they apply" if own else ", illustrative default rates")},
        {"text": "Checked every option against your limits", "detail": _limits_text(p)},
        {"text": f"Chose one option per shipment for {GOALS[goal][0].lower()}",
         "detail": GOALS[goal][1] + (f"; fleet budget EUR {max_total_cost:,.0f}" if max_total_cost is not None else "")},
        {"text": f"Proposal ready: {len(changes)} change{'' if len(changes) == 1 else 's'}, "
                 f"{len(rows) - len(changes) - len(calls)} left as planned, {len(calls)} needing your call",
         "detail": "nothing is applied until you approve it"},
    ]
    return {"goal": goal, "goal_label": GOALS[goal][0], "preferences": p, "max_total_cost": max_total_cost,
            "steps": steps, "rows": rows, "currency": "EUR",
            "totals": {"extra_cost": round(sum(r["choice"]["extra_cost"] for r in changes), 2), "changes": len(changes),
                       "no_change": len(rows) - len(changes) - len(calls), "needs_your_call": len(calls),
                       "shipments": len(ships), "affected": len(affected)},
            "note": "A suggested plan from a greedy heuristic, shipment by shipment, not a solver. Costs are estimates. "
                    "Approving records each change as tentative; nothing is booked or sent to a carrier."}
