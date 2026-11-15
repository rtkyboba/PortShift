"""Plan a shipment: turn a list of stops into suggested routes with distance, time, cost and risk.

This is a sketch planner, not a routing engine, and the UI says so:
  * road legs follow real roads (roads.py: OpenStreetMap via the public OSRM router, cached); when that lookup is
    not available the distance is the straight line x ROAD_FACTOR; sea legs follow a small hand-written set of sea waypoints;
    air legs are straight lines
  * cost = for each leg, a looked-up rate x what is billed for the cargo in that mode, plus surcharges
    (costing.py): the operator's own rate where one applies, else the illustrative default
  * risk = the same deterministic job the fleet uses (pipelines/risk_job.py), run on the planned legs against
    the current disruption events
Nothing is booked and no shipment is created. No LLM is involved.
"""
import heapq
import math
import pathlib
from datetime import datetime, timedelta, timezone

import costing
import data
import roads

_ROOT = pathlib.Path(__file__).resolve().parent.parent
ROAD_FACTOR = 1.25
SPEED_KMH = {"truck": 60.0, "ship": 28.0, "plane": 750.0}
FIXED_HOURS = {"truck": 0.5, "ship": 2.0, "plane": 2.0}       # loading, port or airport time per leg
CHANGE_HOURS = {"port": 4.0, "airport": 3.0, "warehouse": 1.0, "customer": 1.0}  # waiting where the mode changes (customer: a customer site)
MODE_KIND = {"ship": "port", "plane": "airport"}
REGION_NAMES = {"GB": "Great Britain", "IE": "Ireland", "EU": "the Continent"}

# Places an example UK and Europe operator can use. The operator adds their own in the UI.
PLACES = [
    {"name": n, "kind": k, "lat": la, "lon": lo} for n, k, la, lo in [
        ("Felixstowe", "port", 51.96, 1.35), ("Dover", "port", 51.13, 1.31), ("Southampton", "port", 50.90, -1.40),
        ("Immingham", "port", 53.63, -0.19), ("Liverpool", "port", 53.45, -3.02), ("Grangemouth", "port", 56.03, -3.70),
        ("Aberdeen", "port", 57.14, -2.07), ("Greenock", "port", 55.95, -4.76), ("Avonmouth", "port", 51.50, -2.70),
        ("Dublin", "port", 53.35, -6.20), ("Rotterdam", "port", 51.95, 4.14), ("Antwerp", "port", 51.26, 4.40),
        ("Zeebrugge", "port", 51.33, 3.20), ("Calais", "port", 50.97, 1.85), ("Le Havre", "port", 49.49, 0.11),
        ("Hamburg", "port", 53.54, 9.98),
        ("London Heathrow", "airport", 51.47, -0.45), ("Manchester Airport", "airport", 53.36, -2.27),
        ("Glasgow Airport", "airport", 55.87, -4.43), ("East Midlands Airport", "airport", 52.83, -1.33),
        ("Edinburgh Airport", "airport", 55.95, -3.37), ("Birmingham Airport", "airport", 52.45, -1.75),
        ("Dublin Airport", "airport", 53.43, -6.25), ("Brussels Airport", "airport", 50.90, 4.48), ("Amsterdam Schiphol", "airport", 52.31, 4.76),
        ("Paris CDG", "airport", 49.01, 2.55), ("Frankfurt Airport", "airport", 50.03, 8.57),
        ("Glasgow warehouse", "warehouse", 55.86, -4.25), ("Edinburgh warehouse", "warehouse", 55.93, -3.30),
        ("Leeds warehouse", "warehouse", 53.76, -1.55), ("Manchester warehouse", "warehouse", 53.48, -2.24),
        ("Birmingham warehouse", "warehouse", 52.48, -1.89), ("London warehouse (Hayes)", "warehouse", 51.51, -0.42),
        ("Bristol warehouse", "warehouse", 51.45, -2.59), ("Lille warehouse", "warehouse", 50.63, 3.06),
        ("Brussels warehouse", "warehouse", 50.85, 4.35), ("Duisburg warehouse", "warehouse", 51.45, 6.73),
        ("Paris warehouse", "warehouse", 48.86, 2.35),
    ]
]

# Sea waypoints around Great Britain, Ireland and the near Continent, and which are joined by open water.
SEA = {"north_sea_n": (57.4, -1.2), "forth": (56.1, -2.4), "north_sea_c": (55.0, -0.6), "humber": (53.6, 0.6),
       "north_sea_s": (52.6, 2.4), "thames": (51.7, 1.8), "dover_strait": (51.05, 1.5), "channel_e": (50.4, 0.0),
       "solent": (50.6, -1.2), "channel_c": (50.1, -2.5), "channel_w": (49.6, -5.2), "lands_end": (50.0, -6.2),
       "bristol_ch": (51.3, -4.4), "celtic": (51.3, -6.4), "irish_s": (52.6, -5.6), "irish_c": (53.6, -4.6),
       "north_ch": (55.2, -5.7), "clyde": (55.6, -5.0), "dutch": (52.2, 3.6), "scheldt": (51.5, 3.1),
       "german_bight": (54.0, 7.6), "seine_bay": (49.7, -0.2)}
SEA_LINKS = [("north_sea_n", "forth"), ("north_sea_n", "north_sea_c"), ("forth", "north_sea_c"), ("north_sea_c", "humber"),
             ("north_sea_c", "german_bight"), ("humber", "north_sea_s"), ("humber", "german_bight"), ("north_sea_s", "thames"),
             ("north_sea_s", "dutch"), ("dutch", "german_bight"), ("dutch", "scheldt"), ("scheldt", "thames"),
             ("thames", "dover_strait"), ("scheldt", "dover_strait"), ("dover_strait", "channel_e"), ("channel_e", "solent"),
             ("channel_e", "seine_bay"), ("solent", "channel_c"), ("seine_bay", "channel_c"), ("channel_c", "channel_w"),
             ("channel_w", "lands_end"), ("lands_end", "bristol_ch"), ("lands_end", "celtic"), ("bristol_ch", "celtic"),
             ("celtic", "irish_s"), ("irish_s", "irish_c"), ("irish_c", "north_ch"), ("north_ch", "clyde")]
PORT_ACCESS = {"Felixstowe": ["thames", "north_sea_s"], "Dover": ["dover_strait"], "Calais": ["dover_strait"],
               "Southampton": ["solent"], "Immingham": ["humber"], "Liverpool": ["irish_c"], "Dublin": ["irish_c", "irish_s"],
               "Grangemouth": ["forth"], "Aberdeen": ["north_sea_n"], "Greenock": ["clyde"], "Avonmouth": ["bristol_ch"],
               "Rotterdam": ["dutch"], "Antwerp": ["scheldt"], "Zeebrugge": ["scheldt"], "Le Havre": ["seine_bay"],
               "Hamburg": ["german_bight"]}
FERRY = {frozenset(("GB", "EU")): ("Dover", "Calais"), frozenset(("GB", "IE")): ("Liverpool", "Dublin")}


def km(a, b) -> float:
    return data._km((a[0], a[1]), (b[0], b[1]))


def region(p: dict) -> str:
    """Which landmass a point is on, by rough boxes: enough to know whether a truck needs a ferry."""
    la, lo = p["lat"], p["lon"]
    if 51.3 <= la <= 55.5 and -10.6 <= lo <= -5.3:
        return "IE"
    if 49.9 <= la <= 59.5 and -8.0 <= lo <= 1.85 and not (la < 51.2 and lo > 1.5):
        return "GB"
    return "EU"


def _pt(p: dict) -> list:
    return [p["lat"], p["lon"]]


def nearest(places: list[dict], kind: str, to: dict, same_region: bool = True) -> dict | None:
    pool = [p for p in places if p["kind"] == kind and (not same_region or region(p) == region(to))]
    return min(pool, key=lambda p: km(_pt(p), _pt(to))) if pool else None


def sea_path(a: dict, b: dict) -> list:
    """Shortest path over the sea waypoints between two ports. A port without a listed approach joins at its
    two nearest waypoints (indicative only)."""
    def access(p):
        return PORT_ACCESS.get(p["name"]) or sorted(SEA, key=lambda w: km(SEA[w], _pt(p)))[:2]
    graph: dict[str, list] = {w: [] for w in SEA}
    for u, v in SEA_LINKS:
        d = km(SEA[u], SEA[v])
        graph[u].append((v, d)); graph[v].append((u, d))
    start, goal = {w: km(_pt(a), SEA[w]) for w in access(a)}, {w: km(_pt(b), SEA[w]) for w in access(b)}
    best, heap, prev = dict(start), [(d, w) for w, d in start.items()], {}
    heapq.heapify(heap)
    while heap:
        d, u = heapq.heappop(heap)
        if d > best.get(u, math.inf):
            continue
        for v, w in graph[u]:
            if d + w < best.get(v, math.inf):
                best[v], prev[v] = d + w, u
                heapq.heappush(heap, (d + w, v))
    end = min(goal, key=lambda w: best.get(w, math.inf) + goal[w])
    chain = [end]
    while chain[-1] in prev:
        chain.append(prev[chain[-1]])
    return [_pt(a), *[list(SEA[w]) for w in reversed(chain)], _pt(b)]


def make_leg(mode: str, a: dict, b: dict) -> dict:
    by_road = roads.route(_pt(a), _pt(b)) if mode == "truck" else None
    if by_road:  # the road itself: its line and its length
        geometry, dist = by_road
    else:
        geometry = sea_path(a, b) if mode == "ship" else [_pt(a), _pt(b)]
        dist = sum(km(p, q) for p, q in zip(geometry, geometry[1:])) * (ROAD_FACTOR if mode == "truck" else 1.0)
    return {"mode": mode, "from": a, "to": b, "geometry": geometry, "km": dist, "road": bool(by_road),
            "hours": dist / SPEED_KMH[mode] + FIXED_HOURS[mode]}


def check_leg(mode: str, a: dict, b: dict) -> str | None:
    """Why this leg cannot be done in this mode, or None."""
    kind = MODE_KIND.get(mode)
    if kind and (a["kind"] != kind or b["kind"] != kind):
        which = " and ".join(p["name"] for p in (a, b) if p["kind"] != kind)
        return f"A {mode} leg needs {'a port' if kind == 'port' else 'an airport'} at both ends; {which} is not one."
    if mode == "truck" and region(a) != region(b):
        return (f"A truck cannot drive from {REGION_NAMES[region(a)]} to {REGION_NAMES[region(b)]}. "
                "Add a ferry (ship) leg between two ports, or use the road suggestion.")
    if a["name"] == b["name"]:
        return "A leg needs two different places."
    return None


# ---- strategies: how to get from one stop to the next -------------------------------------------

def by_road(a: dict, b: dict, places: list[dict]) -> list[dict]:
    ra, rb = region(a), region(b)
    if ra == rb:
        return [make_leg("truck", a, b)]
    if {ra, rb} == {"IE", "EU"}:  # Ireland to the Continent goes over Great Britain
        via = next(p for p in places if p["name"] == ("Liverpool" if ra == "IE" else "Dover"))
        return by_road(a, via, places) + by_road(via, b, places)
    names = FERRY[frozenset((ra, rb))]
    ports = {p["name"]: p for p in places if p["name"] in names}
    pa = next(p for p in ports.values() if region(p) == ra)
    pb = next(p for p in ports.values() if region(p) == rb)
    legs = [] if a["name"] == pa["name"] else [make_leg("truck", a, pa)]
    legs.append(make_leg("ship", pa, pb))
    return legs + ([] if b["name"] == pb["name"] else [make_leg("truck", pb, b)])


def _via(mode: str, kind: str, a: dict, b: dict, places: list[dict], min_km: float) -> list[dict] | None:
    ha, hb = nearest(places, kind, a), nearest(places, kind, b)
    if not ha or not hb or ha["name"] == hb["name"] or km(_pt(a), _pt(b)) < min_km:
        return None
    main = make_leg(mode, ha, hb)
    access = km(_pt(a), _pt(ha)) + km(_pt(hb), _pt(b))
    direct = km(_pt(a), _pt(b))
    if main["km"] > 2.5 * direct or access > 0.6 * direct:  # a detour that makes no sense for this pair
        return None
    legs = [] if a["name"] == ha["name"] else [make_leg("truck", a, ha)]
    legs.append(main)
    return legs + ([] if b["name"] == hb["name"] else [make_leg("truck", hb, b)])


def by_sea(a, b, places):
    return _via("ship", "port", a, b, places, 150.0)


def by_air(a, b, places):
    return _via("plane", "airport", a, b, places, 300.0)


# ---- scoring ------------------------------------------------------------------------------------

_risk_job = data.risk_job


DEFAULT_CARGO = {"units": 20, "unit_type": "pallet", "weight_kg": None}


def schedule(legs: list[dict], depart: datetime, cargo: dict, op: dict) -> list[dict]:
    """Give each leg its times and cost, in the shape of the `legs` table so the risk job can score it."""
    out, t = [], depart
    for i, leg in enumerate(legs):
        if i and legs[i - 1]["mode"] != leg["mode"]:
            t += timedelta(hours=CHANGE_HOURS[leg["from"]["kind"]])
        end = t + timedelta(hours=leg["hours"])
        c = costing.freight(leg["mode"], cargo, leg["from"]["name"], leg["to"]["name"], leg["km"], t, None, op)
        out.append({"seq": i + 1, "mode": leg["mode"], "from_name": leg["from"]["name"], "from_lat": leg["from"]["lat"],
                    "from_lon": leg["from"]["lon"], "to_name": leg["to"]["name"], "to_lat": leg["to"]["lat"],
                    "to_lon": leg["to"]["lon"], "geometry": leg["geometry"], "planned_start": data._iso(t),
                    "planned_end": data._iso(end), "km": round(leg["km"]), "hours": round(leg["hours"], 1), "road": bool(leg.get("road")),
                    "cost": c["cost"], "cost_lines": c["cost_lines"], "cost_basis": c["cost_basis"]})
        t = end
    return out


def score(route_id: str, label: str, legs: list[dict], depart: datetime, prefs: dict, problems=(), cargo=None, op=None) -> dict:
    rows = schedule(legs, depart, cargo or DEFAULT_CARGO, op or costing.operator())
    events = data._rows("disruption_events")
    try:
        level, reason, event_ids = _risk_job().score_shipment(rows, events, data._now())
    except Exception:  # the job is missing or failed: say so rather than guess a level
        level, reason, event_ids = None, "Risk could not be scored", []
    hit = [e for e in events if e["event_id"] in event_ids]
    for r in rows:
        r["event_ids"] = [e["event_id"] for e in hit if data.leg_in_area(r, e)]
    cost = round(sum(r["cost"] or 0 for r in rows), 2)
    used = {l["rate_source"] for r in rows for l in r["cost_lines"]}
    basis = "operator" if used == {"operator"} else "mixed" if "operator" in used else "default"
    hours = (data._ts(rows[-1]["planned_end"]) - depart).total_seconds() / 3600 if rows else 0
    violations = []
    if level and level > prefs["max_risk"]:
        violations.append(f"risk level {level} is above your limit of {prefs['max_risk']}")
    return {"id": route_id, "label": label, "legs": rows, "km": sum(r["km"] for r in rows), "hours": round(hours, 1),
            "cost": cost, "currency": costing.CURRENCY, "cost_basis": basis,
            "cost_note": {"operator": "estimate, your rates", "mixed": "estimate, your rates where you have them, illustrative rates elsewhere",
                          "default": "estimate, illustrative rates"}[basis],
            "eta": rows[-1]["planned_end"] if rows else None,
            "risk": {"level": level, "reason": reason, "event_ids": event_ids},
            "problems": list(problems), "violations": violations, "within_limits": not violations and not problems}


def clean_cargo(cargo: dict | None) -> dict:
    c = {**DEFAULT_CARGO, **(cargo or {})}
    try:
        units = max(1.0, min(5000.0, float(c["units"])))
        weight = float(c["weight_kg"]) if c.get("weight_kg") not in (None, "") else None
    except (TypeError, ValueError):
        units, weight = DEFAULT_CARGO["units"], None
    kind = c["unit_type"] if c.get("unit_type") in costing.CARGO_TYPES else "pallet"
    return {"units": units, "unit_type": kind, "weight_kg": weight if weight and weight > 0 else None}


def _utc(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def _when(t: datetime) -> str:
    return t.strftime("%d %b, %H:%M").lstrip("0")


def _span(h: float) -> str:
    h = abs(h)
    return f"{h / 24:.1f} days" if h >= 48 else f"{round(h)} h"


def suggest(stops: list[dict], modes: list[str], depart_at: str | None, preferences: dict | None,
            extra_places: list[dict] | None = None, cargo: dict | None = None,
            arrive_by: str | None = None, plan_from: str = "depart") -> dict:
    """Routes through the stops in order: as drawn (the modes given), by road, by sea and by air.

    plan_from "depart": leave at depart_at (default two hours from now); with arrive_by, each route is checked
    against that deadline. plan_from "arrive" (needs arrive_by): plan backwards, so each route leaves at the latest
    whole hour that still arrives by arrive_by; depart_at is then the earliest the cargo can leave, if given.
    """
    prefs = data._limits(preferences)
    places = PLACES + [p for p in (extra_places or []) if p.get("name") and p.get("kind") in CHANGE_HOURS]
    now = data._now()
    deadline = _utc(data._ts(arrive_by)) if arrive_by else None
    backwards = plan_from == "arrive" and deadline is not None
    earliest = _utc(data._ts(depart_at)) if depart_at else None
    depart = earliest if earliest and not backwards else (now + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    pairs = list(zip(stops, stops[1:]))
    routes, seen = [], set()
    cargo = clean_cargo(cargo)
    op = costing.operator()

    def add(route_id, label, legs, problems=()):
        key = tuple((l["mode"], l["from"]["name"], l["to"]["name"]) for l in legs)
        if not legs or key in seen:
            return
        seen.add(key)
        problems, leave = list(problems), depart
        if backwards:  # the trip takes the same time whenever it starts: leave at the latest whole hour that makes it
            trip = data._ts(schedule(legs, depart, cargo, op)[-1]["planned_end"]) - depart
            leave = (deadline - trip).replace(minute=0, second=0, microsecond=0)
            if leave < now:
                problems.append(f"Too late: to arrive by {_when(deadline)} this route had to leave by {_when(leave)}.")
        r = score(route_id, label, legs, leave, prefs, problems, cargo, op)
        r["depart_at"] = data._iso(leave)
        if deadline is not None:
            r["arrive_by"] = data._iso(deadline)
            r["slack_hours"] = round((deadline - data._ts(r["eta"])).total_seconds() / 3600, 1)
            if r["slack_hours"] < 0:
                r["violations"].append(f"arrives {_span(r['slack_hours'])} after your arrive-by date ({_when(deadline)})")
        if backwards and earliest and leave < earliest:
            r["violations"].append(f"has to leave by {_when(leave)}, before your earliest departure ({_when(earliest)})")
        r["within_limits"] = not r["violations"] and not r["problems"]
        routes.append(r)

    problems = [f"Leg {i + 1}: {p}" for i, ((a, b), m) in enumerate(zip(pairs, modes)) if (p := check_leg(m, a, b))]
    add("drawn", "As you drew it", [make_leg(m, a, b) for (a, b), m in zip(pairs, modes)], problems)
    road = [leg for a, b in pairs for leg in by_road(a, b, places)]
    add("road", "By road" + (", with a ferry" if any(l["mode"] == "ship" for l in road) else ""), road)
    for route_id, word, fn in (("sea", "sea", by_sea), ("air", "air", by_air)):
        parts = [fn(a, b, places) for a, b in pairs]
        if any(parts):
            legs = [leg for part, (a, b) in zip(parts, pairs) for leg in (part or by_road(a, b, places))]
            main = next(l for l in legs if l["mode"] == ("ship" if word == "sea" else "plane"))
            add(route_id, f"By {word}: {main['from']['name']} to {main['to']['name']}", legs)

    ok = [r for r in routes if r["within_limits"]] or [r for r in routes if not r["problems"]] or routes
    best = min(ok, key=lambda r: (r["cost"], r["risk"]["level"] or 9)) if ok else None
    return {"routes": routes, "recommended_id": best["id"] if best else None,
            "depart_at": best["depart_at"] if backwards and best else data._iso(depart),
            "arrive_by": data._iso(deadline) if deadline else None, "plan_from": "arrive" if backwards else "depart",
            "preferences": prefs, "cargo": cargo,
            "notes": "Suggested routes, not optimal ones. "
                     + ("Truck legs follow real roads (OpenStreetMap, via the public OSRM router; only the two end points are sent). "
                        if all(l.get("road") for r in routes for l in r["legs"] if l["mode"] == "truck") and any(l["mode"] == "truck" for r in routes for l in r["legs"])
                        else "Truck legs follow real roads where the road lookup worked; otherwise the distance is the straight line times "
                             f"{ROAD_FACTOR}. " if any(l.get("road") for r in routes for l in r["legs"])
                        else f"Road distance is the straight line times {ROAD_FACTOR}. ")
                     + "Sea legs follow indicative sea lanes. Costs are estimates from the rate tables: "
                     "your own rate where one applies, else the illustrative default. Nothing is booked."}
