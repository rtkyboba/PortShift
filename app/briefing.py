"""The agent's briefing: what it found and what it proposes, in the order it works, from the tables as they are now.

Search, cross-check, score, plan, resources: each step is counted from the stored rows (agent run records, events
with their evidence, the risk rows, the fleet plan, the fleet register). Nothing here is generated text and nothing
is decided: the last step hands the plan to the operator to review and approve.
"""
from datetime import timedelta

import assets
import data
import fleet

NAMES = fleet.NAMES


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _unsure(e: dict) -> str | None:
    """Why the end of this event's window is not firm, if it is not."""
    if e["status"] != "confirmed":
        return "the disruption itself is only suspected"
    hours = (data._ts(e["window_end"]) - data._ts(e["window_start"])).total_seconds() / 3600
    if not e["is_fixture"] and abs(hours - 72) < 0.01:  # agent/extract.py: a source that gives no end gets start + 72 h
        return "no reopening time was reported, so 72 hours is assumed"
    return None


def _waiting(urgent: list[dict], events: dict) -> dict:
    """If nothing is changed: how long each Severe or Critical shipment would be held, and its new arrival.
    The delay is the wait-out estimate the costing already uses (the span of the linked event windows, whole days)."""
    rows = []
    for x in urgent:
        w = x["wait_out"]
        if not w:
            continue
        linked = [events[i] for i in x["risk"]["event_ids"] if i in events]
        why = next((r for r in (_unsure(e) for e in linked) if r), None)
        eta = data._ts(x["eta"])
        rows.append({"shipment_id": x["shipment_id"], "level": x["risk"]["level"], "text": f"{x['origin']} → {x['destination']}",
                     "delay_days": w["days"], "delay_hours": w["days"] * 24, "eta": x["eta"],
                     "eta_if_waiting": data._iso(eta + timedelta(days=w["days"])), "cost": w["cost"],
                     "tentative": why is not None, "why_tentative": why,
                     "until": max((e["window_end"] for e in linked), default=None),
                     "events": [f"{e['type']} at {e['location']}" for e in linked]})
    return {"rows": rows, "total_cost": round(sum(r["cost"] for r in rows), 2), "tentative": sum(1 for r in rows if r["tentative"]),
            "longest_days": max((r["delay_days"] for r in rows), default=0),
            "note": "Delay is the time to sit out the linked disruption windows, in whole days, from their reported start and end. "
                    "Marked tentative where the end is not firm. Costs are estimates."}


def build(preferences: dict | None = None) -> dict:
    now = data._now()
    runs, events, ships, s = data.agent_runs(), data.events(), data.shipments(), data.summary()
    plan = fleet.plan_all(preferences)
    live = [e for e in events if not e["is_fixture"]]
    evidence = [v for e in events for v in e["evidence"]]
    domains = {v["domain"] for v in evidence}
    confirmed, suspected = [e for e in events if e["status"] == "confirmed"], [e for e in events if e["status"] != "confirmed"]
    urgent = sorted((x for x in ships if (x["risk"]["level"] or 0) >= 4), key=lambda x: (-(x["risk"]["level"] or 0), x["impact_at"] or "9999"))
    t, steps = plan["totals"], []

    if runs:
        last = runs[0]
        steps.append({"key": "search", "title": f"Searched the live web: {_n(len(runs), 'corridor run')}",
                      "detail": f"{sum(r.get('queries_run') or 0 for r in runs)} searches, {sum(r.get('results_seen') or 0 for r in runs)} results read, "
                                f"{sum(r.get('events_extracted') or 0 for r in runs)} events extracted, {sum(r.get('events_dropped') or 0 for r in runs)} dropped. "
                                f"Last: {last.get('corridor')}.",
                      "at": last.get("finished_at") or last.get("started_at"), "items": []})
    else:
        steps.append({"key": "search", "title": "No live search has run on this server yet",
                      "detail": "The disruptions below are sample events, each marked sample. Ask me to run a live check to search now.",
                      "at": None, "items": [], "action": "check"})
    steps.append({"key": "sources", "title": f"Cross-checked {_n(len(events), 'disruption')} against {_n(len(evidence), 'source')} from {_n(len(domains), 'site')}",
                  "detail": f"{len(confirmed)} confirmed (two independent sites, or one official source), {len(suspected)} suspected. "
                            + (f"All {len(live)} from live search." if len(live) == len(events) else f"{len(live)} from live search, {len(events) - len(live)} sample."),
                  "at": s["evidence"]["newest_retrieved_at"],
                  "items": [{"event_id": e["event_id"], "text": f"{e['type'].capitalize()} · {e['location']}", "status": e["status"],
                             "basis": e["basis"]["text"], "is_fixture": e["is_fixture"], "shipments": len(e["shipments"])} for e in events]})
    steps.append({"key": "score", "title": f"Scored all {_n(len(ships), 'shipment')}: {len(urgent)} need you",
                  "detail": ", ".join(f"{c} {NAMES[int(n)]}" for n, c in sorted(s["levels"].items(), reverse=True) if c and int(n)) + ". Scored by the risk job, not by a model.",
                  "at": None,
                  "items": [{"shipment_id": x["shipment_id"], "level": x["risk"]["level"], "text": f"{x['origin']} → {x['destination']}",
                             "reason": x["risk"]["reason"], "impact_at": x["impact_at"]} for x in urgent]})
    steps.append({"key": "plan", "title": f"Drafted a plan: {_n(t['changes'], 'change')} for about EUR {t['extra_cost']:,.0f}",
                  "detail": f"Waiting out the disruptions instead would cost about EUR {s['exposure']['amount']:,.0f} on {_n(s['exposure']['shipments'], 'shipment')}. "
                            f"{t['no_change']} left as they are" + (f", {t['needs_your_call']} need your call (no option fits your limits)." if t["needs_your_call"] else "."),
                  "at": None,
                  "items": [{"shipment_id": r["shipment_id"], "level": r["current_risk"], "text": r["choice"]["label"],
                             "cost": r["choice"]["extra_cost"], "status": r["status"]} for r in plan["rows"] if r["status"] != "no_change"]})
    f = assets.view()["counts"]
    steps.append({"key": "fleet", "title": f"Checked your fleet: {_n(f['available'], 'truck')} free to use",
                  "detail": f"{f['allocated']} allocated, {f['in_transit']} in transit, {f['off_road']} off road.", "at": None, "items": []})
    return {"as_of": data._iso(now), "source": data.source(), "steps": steps,
            "decision": {"changes": t["changes"], "needs_your_call": t["needs_your_call"], "cost": t["extra_cost"],
                         "wait_out": s["exposure"]["amount"], "currency": "EUR"},
            "wait_out": _waiting(urgent, {e["event_id"]: e for e in events}),
            "note": "Counted from the tables as they are now. Demo fleet: synthetic shipments. Costs are estimates. The plan is a "
                    "greedy suggestion; nothing changes until you approve it, and nothing is booked or sent to a carrier."}
