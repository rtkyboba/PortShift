"""What if: a hypothetical disruption, described in a sentence, run against the fleet without touching any table.

"What if Dover closes on Tuesday for 48 hours?" becomes a hypothetical event (never stored, never shown as a real
disruption, no source because there is none). The same deterministic risk job scores the fleet with it, the same
costing prices waiting it out, and the same greedy planner proposes what to do. Everything returned is marked
hypothetical. The sentence is read by rules; when they cannot place it and a model is configured, the model is
asked only to name the place, the kind and the dates, and its answer is checked against the known places.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import data
import fleet
import planner

EVENT_ID = "WHAT-IF"
TYPES = [("strike", r"strike|walk ?out|industrial action|picket"),
         ("weather", r"storm|flood|snow|fog|wind|hurricane|weather|ice\b"),
         ("congestion", r"congest|backlog|queue|gridlock|delay"),
         ("closure", r"clos|shut|block|suspend|out of action|goes down|down\b")]
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
GENERIC = {"warehouse", "airport", "port", "north", "south", "east", "west", "london"}
EXAMPLE = "What if Dover closes on Tuesday for 48 hours?"


def _places() -> list[dict]:
    seen, out = set(), []
    for e in data._stored_rows("disruption_events"):  # places a real event already names, e.g. "Port of Rotterdam"
        if e["location"] not in seen:
            seen.add(e["location"])
            out.append({"name": e["location"], "kind": "area", "lat": e["lat"], "lon": e["lon"]})
    return [p for p in planner.PLACES] + out


def _place(m: str) -> dict | None:
    places = _places()
    for p in sorted(places, key=lambda p: -len(p["name"])):  # a full name first, longest first
        if p["name"].lower() in m:
            return p
    words = set(re.findall(r"[a-z]{4,}", m))
    order = {"port": 0, "airport": 1, "area": 2, "warehouse": 3}
    for p in sorted(places, key=lambda p: order.get(p["kind"], 9)):  # then a distinctive word of it, ports first
        if any(w in words for w in re.findall(r"[a-z]{4,}", p["name"].lower()) if w not in GENERIC):
            return p
    return None


def _window(m: str, now: datetime) -> tuple[datetime, datetime, str]:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start, said = now.replace(minute=0, second=0, microsecond=0), "from now"
    if hit := re.search(r"in (\d+|a|an|one|two|three) (hour|day|week)s?", m):
        n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}.get(hit[1]) or int(hit[1])
        start = now + timedelta(**{hit[2] + "s": n})
        start, said = start.replace(minute=0, second=0, microsecond=0), f"in {n} {hit[2]}{'s' if n != 1 else ''}"
    elif "tomorrow" in m:
        start, said = midnight + timedelta(days=1), "from tomorrow"
    elif "next week" in m:
        start, said = midnight + timedelta(days=7 - now.weekday()), "from next Monday"
    elif "tonight" in m:
        start, said = midnight + timedelta(hours=20), "from tonight"
    else:
        for i, name in enumerate(DAYS):
            if re.search(rf"\b{name}|\b{name[:3]}\b", m):
                ahead = (i - now.weekday()) % 7
                start, said = (midnight + timedelta(days=ahead) if ahead else start), f"from {name.capitalize()}"
                break
    hours = 48.0
    if hit := re.search(r"(?:for|lasting|lasts) (?:about |around )?(\d+(?:\.\d+)?|a|an|one|two|three) (hour|day|week)s?", m):
        n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}.get(hit[1]) or float(hit[1])
        hours = n * {"hour": 1, "day": 24, "week": 168}[hit[2]]
    elif "all week" in m or "a week" in m:
        hours = 168.0
    hours = max(1.0, min(hours, 24.0 * 30))
    return start, start + timedelta(hours=hours), said


def _from_model(message: str, now: datetime) -> dict | None:
    """Ask the model only for place, kind and dates; the place must be one PortShift knows."""
    try:
        import assistant
        llm = assistant._llm()
        if llm is None:
            return None
        names = [p["name"] for p in _places()]
        raw = llm.complete(
            "You turn a what-if question about a transport disruption into JSON. Reply with JSON only: "
            '{"place": one name copied exactly from the list, "type": strike|closure|weather|congestion, '
            '"start": ISO UTC time, "hours": number}. If no listed place fits, reply {"place": null}. '
            f"Now is {data._iso(now)}. Places: {', '.join(names)}.", message, max_tokens=120)
        got = json.loads(re.search(r"\{.*\}", raw or "", re.S)[0])
        place = next((p for p in _places() if p["name"] == got.get("place")), None)
        if place is None:
            return None
        start = data._ts(str(got["start"])) if got.get("start") else now
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
        hours = max(1.0, min(float(got.get("hours") or 48), 720.0))
        kind = got.get("type") if got.get("type") in {t for t, _ in TYPES} else "closure"
        return {"place": place, "type": kind, "start": max(start, now - timedelta(hours=1)), "end": start + timedelta(hours=hours),
                "said": "as read by the model", "read_by": "model"}
    except Exception:
        return None


def parse(message: str, now: datetime | None = None) -> dict:
    """The hypothetical event the sentence describes. Raises ValueError with a sentence the operator can act on."""
    now = now or data._now()
    m = (message or "").lower()
    place = _place(m)
    if place is None:
        read = _from_model(message, now)
        if read is None:
            raise ValueError(f"I could not tell where. Name a port, airport or warehouse PortShift knows, for example: {EXAMPLE}")
    else:
        start, end, said = _window(m, now)
        read = {"place": place, "type": next((t for t, pat in TYPES if re.search(pat, m)), "closure"),
                "start": start, "end": end, "said": said, "read_by": "rules"}
    p, kind = read["place"], read["type"]
    hours = (read["end"] - read["start"]).total_seconds() / 3600
    span = f"{hours / 24:g} days" if hours >= 48 and hours % 24 == 0 else f"{hours:g} hours"
    return {"event_id": EVENT_ID, "type": kind, "status": "confirmed", "location": p["name"], "lat": p["lat"], "lon": p["lon"],
            "radius_km": 40 if kind == "weather" else 25, "window_start": data._iso(read["start"]), "window_end": data._iso(read["end"]),
            "summary": f"Hypothetical {kind} at {p['name']}, {read['said']}, for {span}.", "detected_at": data._iso(now),
            "is_fixture": True, "is_hypothetical": True, "read_by": read["read_by"], "duration_text": span}


def run(message: str, preferences: dict | None = None) -> dict:
    event = parse(message)
    before = {s["shipment_id"]: s for s in data.shipments()}
    with data.supposing([event]):
        ships = data.shipments()
        plan = fleet.plan_all(preferences)
    changed = []
    for s in ships:
        was, lvl = before[s["shipment_id"]], s["risk"]["level"] or 0
        if EVENT_ID not in s["risk"]["event_ids"] and lvl == (was["risk"]["level"] or 0):
            continue
        row = next((r for r in plan["rows"] if r["shipment_id"] == s["shipment_id"]), None)
        changed.append({"shipment_id": s["shipment_id"], "origin": s["origin"], "destination": s["destination"], "mode": s["mode"],
                        "cargo": s["cargo"], "from": was["risk"]["level"] or 0, "to": lvl, "reason": s["risk"]["reason"],
                        "wait_out": s["wait_out"], "wait_out_before": was["wait_out"],
                        "choice": {k: row["choice"].get(k) for k in ("label", "kind", "extra_cost", "resulting_risk", "delay_hours", "within_limits")} if row else None,
                        "why": row["why"] if row else None, "plan_status": row["status"] if row else None})
    changed.sort(key=lambda c: (-c["to"], c["shipment_id"]))
    worse = [c for c in changed if c["to"] > c["from"]]
    cost = lambda w: (w or {}).get("cost") or 0
    count = lambda rows: {n: sum(1 for s in rows if (s["risk"]["level"] or 0) == n) for n in range(1, 6)}
    return {"question": message, "event": event, "hypothetical": True, "ships": ships, "changed": changed,
            "levels_before": count(before.values()), "levels_after": count(ships),
            "totals": {"touched": len(changed), "worse": len(worse), "newly_critical": sum(1 for c in worse if c["to"] == 5),
                       "wait_out": round(sum(cost(c["wait_out"]) for c in changed), 2),  # to sit it out, for the shipments it touches
                       "plan_cost": round(sum((c["choice"] or {}).get("extra_cost") or 0 for c in changed if c["plan_status"] == "change"), 2),
                       "plan_changes": sum(1 for c in changed if c["plan_status"] == "change"),
                       "needs_your_call": sum(1 for c in changed if c["plan_status"] == "needs_your_call"), "currency": "EUR"},
            "note": "Hypothetical: this event is not real and has no source. Nothing was saved or changed. Risk levels come from "
                    "the same scoring job, costs from the same rate tables (estimates), the plan from the same greedy heuristic."}
