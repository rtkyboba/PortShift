"""Reroutes for a disrupted shipment, found by search instead of read from a fixed table.

For the part of the route the disruption touches, this builds real alternatives with the planner's own pieces
(roads, sea lanes, ports, airports) and keeps only the ones the risk job says get the shipment clear:

  * another crossing: for a truck that has to cross water, every pair of ports that is outside a disrupted area;
  * another gateway: a nearby port or airport in place of the disrupted one (also as the place to leave from);
  * straight past: the stops either side joined directly, skipping the disrupted stop;
  * round the area: by road to either side of it;
  * a known sea alternative to a canal (Suez: the Cape of Good Hope).

Each alternative is timed with the same model as the stretch it replaces, so "+6 h" or "-2 h" compares like with
like; the fleet's planned times are kept and shifted by that difference. Distance and time changes can be negative.
The result is scored by pipelines/risk_job.py against every active event; an alternative that is not safer than
the current plan is dropped. It is still a heuristic search over a small set of places, not a routing engine.
"""
import math
from datetime import timedelta

import data
import planner

MAX_OPTIONS = 3
CAPE_LANE = [(5.9, 95.0), (-28.0, 49.5), (-35.5, 20.0), (14.0, -19.5), (43.3, -10.5), (48.6, -6.0), (50.4, 0.3), (51.6, 2.6)]
CANALS = {"suez": ("the Cape of Good Hope", CAPE_LANE), "red sea": ("the Cape of Good Hope", CAPE_LANE)}
_memo: dict = {}

# Ferry terminals that are not in the planner's list of places, and the freight ferry routes a truck can use.
# A truck crossing is only offered on one of these routes. The list is from general knowledge of the short-sea
# market (operators change routes): check it against current timetables before relying on it.
FERRY_PORTS = [{"name": n, "kind": "port", "lat": la, "lon": lo} for n, la, lo in [
    ("Dunkirk", 51.05, 2.37), ("Harwich", 51.95, 1.29), ("Hook of Holland", 51.98, 4.13), ("Portsmouth", 50.80, -1.09),
    ("Caen (Ouistreham)", 49.28, -0.25), ("Hull", 53.74, -0.28), ("Tilbury", 51.46, 0.36), ("Teesport", 54.60, -1.16),
    ("Holyhead", 53.31, -4.63)]]
FERRY_ROUTES = [
    ("Dover", "Calais"), ("Dover", "Dunkirk"), ("Portsmouth", "Le Havre"), ("Portsmouth", "Caen (Ouistreham)"),
    ("Harwich", "Hook of Holland"), ("Felixstowe", "Rotterdam"), ("Hull", "Rotterdam"), ("Immingham", "Rotterdam"),
    ("Immingham", "Zeebrugge"), ("Tilbury", "Zeebrugge"), ("Teesport", "Zeebrugge"),
    ("Liverpool", "Dublin"), ("Holyhead", "Dublin"), ("Dublin", "Zeebrugge"), ("Dublin", "Rotterdam")]


def _ports() -> dict:
    return {p["name"]: p for p in [*planner.PLACES, *FERRY_PORTS] if p["kind"] == "port"}


def _km(a: dict, b: dict) -> float:
    return planner.km([a["lat"], a["lon"]], [b["lat"], b["lon"]])


def _stop(name: str, lat: float, lon: float) -> dict:
    """A stop of the shipment as a place: a port or airport if it sits on one the planner knows."""
    here = {"name": name, "lat": lat, "lon": lon}
    near = min(planner.PLACES, key=lambda p: _km(p, here))
    kind = near["kind"] if _km(near, here) <= 30 and near["kind"] in ("port", "airport") else "warehouse"
    return {**here, "kind": kind}


def _inside(p: dict, event: dict) -> bool:
    return data._km((p["lat"], p["lon"]), (event["lat"], event["lon"])) <= event["radius_km"]


def _line_km(geometry: list) -> float:
    return sum(planner.km(p, q) for p, q in zip(geometry, geometry[1:]))


_events_now: list = []  # the active events, set by alternatives() for the legs it builds


def _leg(mode: str, a: dict, b: dict) -> dict | None:
    if _km(a, b) < 5:
        return None
    leg = planner.make_leg(mode, a, b)
    return _keep_off(leg, _events_now) if mode == "ship" else leg


def _keep_off(leg: dict, events: list[dict]) -> dict:
    """A ship can hold a course clear of a disrupted area it would otherwise sail through: where the sea lane
    passes inside one (and the leg does not call there), bend it out to just beyond the edge."""
    g = [list(p) for p in leg["geometry"]]
    for e in events:
        centre = (e["lat"], e["lon"])
        if any(data._km(tuple(g[i]), centre) <= e["radius_km"] for i in (0, -1)):
            continue  # it calls at the disrupted place: nothing to bend
        for _ in range(3):
            worst = None  # (distance, index of the segment, point on it)
            for i, (p, q) in enumerate(zip(g, g[1:])):
                for k in range(0, 21):
                    pt = (p[0] + (q[0] - p[0]) * k / 20, p[1] + (q[1] - p[1]) * k / 20)
                    dist = data._km(pt, centre)
                    if dist <= e["radius_km"] + 2 and (worst is None or dist < worst[0]):
                        worst = (dist, i, pt)
            if worst is None:
                break
            dist, i, pt = worst
            scale = (e["radius_km"] + 8) / max(dist, 0.5)
            g.insert(i + 1, [centre[0] + (pt[0] - centre[0]) * scale, centre[1] + (pt[1] - centre[1]) * scale])
    if len(g) == len(leg["geometry"]):
        return leg
    dist = _line_km(g)
    return {**leg, "geometry": g, "km": dist, "hours": dist / planner.SPEED_KMH["ship"] + planner.FIXED_HOURS["ship"]}


def _hours(legs: list[dict]) -> float:
    """Travel time of consecutive legs, with the waiting where the mode changes (as the planner counts it)."""
    total = sum(l["hours"] for l in legs)
    for prev, nxt in zip(legs, legs[1:]):
        if prev["mode"] != nxt["mode"]:
            total += planner.CHANGE_HOURS.get(nxt["from"].get("kind"), 1.0)
    return total


def _side(w: dict, event: dict) -> str:
    dlat, dlon = w["lat"] - event["lat"], (w["lon"] - event["lon"]) * math.cos(math.radians(event["lat"]))
    return ("north" if dlat > 0 else "south") if abs(dlat) >= abs(dlon) else ("east" if dlon > 0 else "west")


def _around(a: dict, b: dict, event: dict, extra_km: float, side: int) -> dict:
    dlat, dlon = b["lat"] - a["lat"], (b["lon"] - a["lon"]) * math.cos(math.radians(event["lat"]))
    n = math.hypot(dlat, dlon) or 1.0
    off = (event["radius_km"] + extra_km) / 111.0
    return {"name": "around the area", "kind": "warehouse", "lat": event["lat"] + side * (dlon / n) * off,
            "lon": event["lon"] - side * (dlat / n) * off / max(0.2, math.cos(math.radians(event["lat"])))}


def _candidates(x: dict, y: dict, mode: str, bad_stops: list[dict], event: dict, safe: list[dict], can_leave_elsewhere: bool) -> list[dict]:
    """Ways from x to y that do not use a disrupted place: each {label, via, how, legs}."""
    out = []

    def add(label, via, how, legs):
        legs = [l for l in legs if l]
        if legs:
            out.append({"label": label, "via": via, "how": how, "legs": legs})

    ports = [p for p in safe if p["kind"] == "port"]
    name = event["location"]
    if mode == "truck":
        if planner.region(x) != planner.region(y):  # it has to cross water: the ferry routes whose two ports are both safe
            known, pairs = _ports(), []
            for one, two in FERRY_ROUTES:
                for na, nb in ((one, two), (two, one)):
                    pa, pb = known.get(na), known.get(nb)
                    if pa and pb and planner.region(pa) == planner.region(x) and planner.region(pb) == planner.region(y) \
                            and not any(_inside(q, e) for q in (pa, pb) for e in _events_now):
                        pairs.append((pa, pb))
            rough = lambda pq: _km(x, pq[0]) * planner.ROAD_FACTOR / 60 + _km(pq[0], pq[1]) / 28 + _km(pq[1], y) * planner.ROAD_FACTOR / 60
            for pa, pb in sorted(pairs, key=rough)[:4]:
                start_here = _km(x, pa) < 5
                add(f"Reroute via {pb['name']}" + ("" if start_here else f", sailing from {pa['name']}"), pb["name"],
                    ("ferry" if start_here else "road to " + pa["name"] + ", ferry") + f" to {pb['name']}, then road",
                    [_leg("truck", x, pa), _leg("ship", pa, pb), _leg("truck", pb, y)])
        else:
            add(f"Go direct, {x['name']} to {y['name']}", None, "by road, skipping the stop in between", [_leg("truck", x, y)])
            for extra in (60,):
                for side in (1, -1):
                    w = _around(x, y, event, extra, side)
                    add(f"Go round {name} to the {_side(w, event)}", f"{_side(w, event)} of {name}", f"by road, {round(event['radius_km'] + extra)} km clear of it",
                        [_leg("truck", x, w), _leg("truck", w, y)])
    else:
        kind = planner.MODE_KIND[mode]
        gates = [p for p in safe if p["kind"] == kind]
        if x["kind"] == kind and y["kind"] == kind and bad_stops:
            add(f"Go direct, {x['name']} to {y['name']}", None, f"by {'sea' if mode == 'ship' else 'air'}, skipping {bad_stops[0]['name']}", [_leg(mode, x, y)])
        for s in bad_stops:  # another gateway in place of the disrupted one
            for q in sorted((g for g in gates if planner.region(g) == planner.region(s) and g["name"] not in (x["name"], y["name"])), key=lambda g: _km(g, s))[:3]:
                if x["kind"] != kind:
                    continue
                onward = _leg(mode, q, y) if y["kind"] == kind and not _same(y, s) else _leg("truck", q, y)
                add(f"Reroute via {q['name']}", q["name"], f"{'ship' if mode == 'ship' else 'fly'} to {q['name']} instead of {s['name']}, then on to {y['name']}",
                    [_leg(mode, x, q), onward])
        if can_leave_elsewhere and x["kind"] == kind:  # still at the disrupted gateway, not yet left: leave from another one
            for q in sorted((g for g in gates if planner.region(g) == planner.region(x)), key=lambda g: _km(g, x))[:3]:
                add(f"Leave from {q['name']} instead of {x['name']}", q["name"], f"road to {q['name']}, then {'ship' if mode == 'ship' else 'fly'} from there",
                    [_leg("truck", x, q), _leg(mode, q, y)])
        if mode == "ship":
            for word, (lane_name, lane) in CANALS.items():
                if word in name.lower():
                    # in three stretches, so each has its own dates: the ship is off north-west Europe weeks later
                    pts = [[x["lat"], x["lon"]], *[list(p) for p in lane], [y["lat"], y["lon"]]]
                    marks = [(0, x), (3, {"name": "Cape of Good Hope", "kind": "warehouse", "lat": lane[2][0], "lon": lane[2][1]}),
                             (5, {"name": "Cape Finisterre", "kind": "warehouse", "lat": lane[4][0], "lon": lane[4][1]}), (len(pts) - 1, y)]
                    parts = []
                    for (i, a), (j, b_) in zip(marks, marks[1:]):
                        geometry = pts[i:j + 1]
                        dist = _line_km(geometry)
                        parts.append({"mode": "ship", "from": a, "to": b_, "geometry": geometry, "km": dist, "road": False,
                                      "hours": dist / planner.SPEED_KMH["ship"] + (planner.FIXED_HOURS["ship"] if i == 0 else 0)})
                    add(f"Reroute via {lane_name}", lane_name, "by sea, round Africa instead of through the canal", parts)
                    break
    return out


def _same(a: dict, b: dict) -> bool:
    return _km(a, b) < 5


def _delta(hours: float) -> str:
    h = abs(hours)
    size = f"{h / 24:.1f} days" if h >= 48 else f"{round(h)} h"
    return "no change in time" if h < 0.5 else f"{size} {'later' if hours > 0 else 'sooner'}"


def alternatives(shipment_id: str) -> dict:
    """{"options": [...], "why_none": text or None}. Options are in the shape the app prices and shows."""
    d = data.shipment_detail(shipment_id)
    if not d or not d["legs"]:
        return {"options": [], "why_none": "The shipment has no route to change."}
    now = data._now()
    legs = sorted(d["legs"], key=lambda l: l["seq"])
    events = [e for e in data._rows("disruption_events") if data._ts(e["window_end"]) >= now]
    linked = [e for e in events if e["event_id"] in d["risk"]["event_ids"]]
    if not linked:
        return {"options": [], "why_none": "No disruption is on this route."}
    job = data.risk_job()
    cur = job.current_index(legs, now)
    if cur is None:
        return {"options": [], "why_none": "The shipment has arrived."}
    key = (shipment_id, cur, planner.roads.enabled(), tuple(sorted((e["event_id"], e["window_start"], e["window_end"], e["status"]) for e in events)),
           tuple(l["planned_start"] for l in legs))
    if key in _memo:
        return _memo[key]
    stops = [_stop(legs[0]["from_name"], legs[0]["from_lat"], legs[0]["from_lon"])] + [_stop(l["to_name"], l["to_lat"], l["to_lon"]) for l in legs]
    safe = [p for p in planner.PLACES if not any(_inside(p, e) for e in events)]
    level_now = d["risk"]["level"] or 1
    found, why = [], None
    _events_now[:] = events
    for event in linked:
        hit = [j for j in range(cur, len(legs)) if data.leg_in_area(legs[j], event)]
        if not hit:
            continue
        j0, j1 = hit[0], hit[-1]
        x, y, mode = stops[j0], stops[j1 + 1], legs[j0]["mode"]
        started = data._ts(legs[j0]["planned_start"]) <= now
        if _inside(x, event) and (mode == "truck" or started):
            why = f"The shipment is already at {x['name']}, inside the disrupted area, so there is no way round it: waiting or keeping the plan are the choices."
            continue
        bad = [s for s in stops[j0 + 1:j1 + 2] if _inside(s, event)]
        old = []  # the stretch being replaced, timed with the same model as the alternatives
        for j in range(j0, j1 + 1):
            a, b, m = stops[j], stops[j + 1], legs[j]["mode"]
            if m == "truck" and planner.region(a) != planner.region(b):
                m = "ship"  # the planned crossing is a ferry too: time and price it as one
            if m == "ship" and legs[j]["mode"] == "ship" and not (a["kind"] == "port" and b["kind"] == "port"):
                dist = _line_km(legs[j]["geometry"])
                old.append({"mode": m, "from": a, "to": b, "km": dist, "hours": dist / planner.SPEED_KMH[m] + planner.FIXED_HOURS[m]})
            else:
                old.append(planner.make_leg(m, a, b))
        old_h, old_km = _hours(old), sum(l["km"] for l in old)
        t0, t1 = data._ts(legs[j0]["planned_start"]), data._ts(legs[j1]["planned_end"])
        for c in _candidates(x, y, mode, bad, event, safe, can_leave_elsewhere=_inside(x, event) and not started):
            new_h, new_km = _hours(c["legs"]), sum(l["km"] for l in c["legs"])
            dh, dkm = new_h - old_h, new_km - old_km
            span = max(1.0, (t1 - t0).total_seconds() / 3600 + dh)  # the planned time for the stretch, moved by the difference
            rows, t = [dict(l) for l in legs[:j0]], t0
            for l in c["legs"]:
                end = t + timedelta(hours=span * (l["hours"] / max(0.01, sum(k["hours"] for k in c["legs"]))))
                rows.append({"shipment_id": shipment_id, "seq": len(rows) + 1, "mode": l["mode"], "from_name": l["from"]["name"],
                             "from_lat": l["from"]["lat"], "from_lon": l["from"]["lon"], "to_name": l["to"]["name"], "to_lat": l["to"]["lat"],
                             "to_lon": l["to"]["lon"], "geometry": l["geometry"], "planned_start": data._iso(t), "planned_end": data._iso(end)})
                t = end
            shift = timedelta(hours=dh)
            for l in legs[j1 + 1:]:
                rows.append({**l, "seq": len(rows) + 1, "planned_start": data._iso(data._ts(l["planned_start"]) + shift),
                             "planned_end": data._iso(data._ts(l["planned_end"]) + shift)})
            try:
                level, reason, _ = job.score_shipment(rows, events, now)
            except Exception:
                continue
            if level >= level_now:
                continue  # not safer than the plan as it is
            n_new = len(c["legs"])
            new_rows = rows[j0:j0 + n_new]
            ferry = None
            if mode == "truck":  # road and sea are priced apart: road by the change in distance, each ferry as a fare
                sea = lambda ls: [{"from": l["from"]["name"], "to": l["to"]["name"], "km": round(l["km"])} for l in ls if l["mode"] == "ship"]
                road = lambda ls: sum(l["km"] for l in ls if l["mode"] != "ship")
                ferry = {"new": sea(c["legs"]), "old": sea(old), "road_km": round(road(c["legs"]) - road(old))}
            found.append({
                "kind": "reroute", "label": c["label"], "extra_km": ferry["road_km"] if ferry else round(dkm), "km_delta": round(dkm), "ferry": ferry,
                "delay_hours": round(dh, 1),
                "delay_days": max(0, math.ceil(dh / 24)) if dh > 0 else 0, "resulting_risk": level, "new_planned_start": None,
                "detail": f"Leaves the planned route at {x['name']}: {c['how']}; rejoins at {y['name']}. "
                          f"{abs(round(dkm)):,} km {'more' if dkm >= 0 else 'less'}, {_delta(dh)}. Avoids the {event['type']} at {event['location']}.",
                "path": {"from": x["name"], "to": y["name"], "via": c["via"], "avoids": event["event_id"],
                         "from_point": [x["lat"], x["lon"]], "to_point": [y["lat"], y["lon"]],
                         "segments": [{"mode": r["mode"], "geometry": r["geometry"]} for r in rows],
                         "changed": [{"mode": r["mode"], "geometry": r["geometry"], "from_name": r["from_name"], "to_name": r["to_name"]} for r in new_rows],
                         "sea_is_indicative": any(r["mode"] == "ship" for r in new_rows)},
                "_rank": (level, dh, dkm)})
    seen, best = set(), []
    for o in sorted(found, key=lambda o: o.pop("_rank")):
        if o["label"] in seen or (o["path"]["via"], o["path"]["from"]) in seen:
            continue
        seen.update({o["label"], (o["path"]["via"], o["path"]["from"])})
        o["id"] = "reroute" if not best else f"reroute-{len(best) + 1}"
        best.append(o)
        if len(best) == MAX_OPTIONS:
            break
    if not best and why is None:
        why = "No way round was found that is safer than the plan as it is."
    out = {"options": best, "why_none": None if best else why}
    if len(_memo) > 200:
        _memo.clear()
    _memo[key] = out
    return out


def price_ferries(ship: dict, option: dict, op=None) -> dict:
    """Add the ferry fares to a priced truck reroute: each new crossing as a cost, the planned one it replaces as a credit."""
    import costing
    ferry = option.get("ferry")
    if not ferry or not (ferry["new"] or ferry["old"]):
        return option
    terms, when = costing.terms_of(ship), data._now()
    lines = list(option.get("cost_lines") or [])
    for sign, crossings, what in ((1, ferry["new"], "Ferry"), (-1, ferry["old"], "Planned ferry no longer used")):
        for f in crossings:
            fare = costing.freight("ship", terms, f["from"], f["to"], f["km"], when, terms.get("carrier"), op)
            first = fare["cost_lines"][0] if fare["cost_lines"] else {}
            lines.append({**first, "label": f"{what}, {f['from']} to {f['to']}", "amount": round(sign * fare["cost"], 2),
                          "formula": f"{first.get('formula', 'fare')}, with port and fuel charges" + (" (credit)" if sign < 0 else ""),
                          "note": "fare from the sea rate table; estimate"})
    total = round(sum(l["amount"] for l in lines), 2)
    return {**option, "cost_lines": lines, "extra_cost": total}
