"""A line to draw for each option of a disrupted shipment, so the operator can see what a reroute looks like.

The options themselves (keep, reschedule, reroute, with extra km and hours) come from agent.plan and are priced by
costing.py. A reroute there is a label and two numbers, not a path, so the line here is **indicative**: the legs the
disruption touches are replaced by a path through the place the option names ("via Zeebrugge"), or, when it names
none, around the edge of the disrupted area. It is for looking at, never for distance or cost.
"""
import math
from datetime import timedelta

import data
import planner

# An indicative lane for "via the Cape of Good Hope": points between the Malacca Strait and the Channel.
CAPE_LANE = [(5.9, 95.0), (-28.0, 49.5), (-35.5, 20.0), (14.0, -19.5), (43.3, -10.5), (48.6, -6.0), (50.4, 0.3), (51.6, 2.6)]


def _pt(name, lat, lon, kind="warehouse") -> dict:
    return {"name": name, "kind": kind, "lat": lat, "lon": lon}


def _via(label: str) -> dict | None:
    low = label.lower()
    hits = [p for p in planner.PLACES if p["name"].lower() in low]
    return max(hits, key=lambda p: len(p["name"])) if hits else None


def _around(a: dict, b: dict, event: dict) -> dict:
    """A point just outside the disrupted area, to the side of the straight line from a to b."""
    dlat, dlon = b["lat"] - a["lat"], (b["lon"] - a["lon"]) * math.cos(math.radians(event["lat"]))
    n = math.hypot(dlat, dlon) or 1.0
    off = (event["radius_km"] + 45) / 111.0  # degrees of latitude
    side = 1 if (event["lon"] - a["lon"]) * dlat - (event["lat"] - a["lat"]) * dlon >= 0 else -1  # away from the centre's side
    return _pt("around the area", event["lat"] + side * (dlon / n) * off,
               event["lon"] - side * (dlat / n) * off / max(0.2, math.cos(math.radians(event["lat"]))))


def _segment(mode: str, a: dict, b: dict) -> dict | None:
    if planner.km([a["lat"], a["lon"]], [b["lat"], b["lon"]]) < 5:
        return None
    if mode == "truck" and planner.region(a) != planner.region(b):
        mode = "ship"  # a truck cannot drive across the water: this part is a ferry
    leg = planner.make_leg(mode, a, b)
    return {"mode": mode, "geometry": leg["geometry"]}


def _reroute(legs: list[dict], event: dict, label: str) -> dict | None:
    hit = [i for i, l in enumerate(legs) if data.leg_in_area(l, event)]
    if not hit:
        return None
    first, last = legs[hit[0]], legs[hit[-1]]
    a, b = _pt(first["from_name"], first["from_lat"], first["from_lon"]), _pt(last["to_name"], last["to_lat"], last["to_lon"])
    if data._km((b["lat"], b["lon"]), (event["lat"], event["lon"])) <= event["radius_km"]:
        return None  # the destination itself is inside the disruption: there is no line around it to show
    mode = first["mode"]
    before = [{"mode": l["mode"], "geometry": l["geometry"]} for l in legs[:hit[0]]]
    after = [{"mode": l["mode"], "geometry": l["geometry"]} for l in legs[hit[-1] + 1:]]
    if "cape of good hope" in label.lower():
        new, via = [{"mode": "ship", "geometry": [[a["lat"], a["lon"]], *[list(p) for p in CAPE_LANE], [b["lat"], b["lon"]]]}], "the Cape of Good Hope"
    else:
        place = _via(label)
        mid = place or _around(a, b, event)
        new = [s for s in (_segment(mode, a, mid), _segment(mode, mid, b)) if s]
        via = place["name"] if place else None
    return {"segments": before + new + after, "changed": new, "via": via,
            "from": a["name"], "to": b["name"], "indicative": True}


def routes(shipment_id: str, preferences: dict | None = None) -> dict | None:
    """For each option of the shipment: what to draw, and the arrival it leads to."""
    out = data.options(shipment_id, preferences)
    d = data.shipment_detail(shipment_id)
    if not out or not d:
        return None
    legs = d["legs"]
    events = {e["event_id"]: e for e in data._rows("disruption_events")}
    linked = [events[i] for i in d["risk"]["event_ids"] if i in events]
    event = events.get((out.get("event") or {}).get("event_id")) or (linked[0] if linked else None)
    eta = data._ts(d["eta"])
    current = [{"mode": l["mode"], "geometry": l["geometry"]} for l in legs]
    rows = {}
    for o in out["options"]:
        r = {"kind": o["kind"], "eta": data._iso(eta + timedelta(hours=o.get("delay_hours") or 0)), "segments": current,
             "changed": [], "same_line": True, "indicative": False, "via": None, "note": None}
        if o["kind"] == "reroute" and o.get("path"):  # found by reroute.py: the line is the route it worked out
            path = o["path"]
            r.update(segments=path["segments"], changed=path["changed"], via=path["via"], same_line=False,
                     indicative=path["sea_is_indicative"], **{"from": path["from"], "to": path["to"],
                     "from_point": path["from_point"], "to_point": path["to_point"]})
        elif o["kind"] == "reroute":
            alt = _reroute(legs, event, o["label"]) if event and legs else None
            if alt:
                r.update(alt, same_line=False)
            else:
                r["note"] = "No line to draw for this reroute; the current route is shown."
        rows[o["id"]] = r
    return {"shipment_id": shipment_id, "eta": d["eta"], "event_id": event["event_id"] if event else None, "options": rows,
            "note": "Each reroute line is the route the search worked out: roads where the road service answered, straight "
                    "lines otherwise, and indicative lanes at sea."}
