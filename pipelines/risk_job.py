"""Deterministic risk-scoring job: events x legs -> shipment_risk rows. No LLM, no network.

The rules are the table "Risk levels" in AGENTS.md. `score_fleet` is a pure function over rows shaped
exactly like the CONTRACTS.md tables, so it runs on demo/fixtures, on rows read from Delta, or in a test.

  python pipelines/risk_job.py                         # score demo/fixtures at the current UTC time
  python pipelines/risk_job.py --now 2026-11-14T16:00:00Z --fixtures demo/fixtures --out risk.json
  python pipelines/risk_job.py --compare               # diff the computed levels against shipment_risk.json

How an event is joined to a shipment (decisions the rules left open, kept in one place):
  * on route   : the event point lies within `radius_km` of the leg's geometry (sampled every ~10 km).
  * in time    : the event window overlaps the leg's planned interval [planned_start, planned_end].
  * relevant   : the leg has not finished (planned_end > now) and the event window has not ended.
  * current leg: the leg in progress at `now`; if none has started, the first unfinished leg. next = the one after.
  * hours_away : hours from `now` until the leg starts (0 for the current leg).
  * near       : within `radius_km + NEAR_KM` of the remaining route but not within `radius_km` of it. Only confirmed
                 events count as near (level 3); a suspected event that is merely near scores 1.
Levels per event, then the shipment takes the maximum (event_ids lists only the events at that level):
  5 confirmed, on the current or next leg        4 confirmed, on a later leg more than 24 h away
  3 suspected within 72 h, or confirmed near     2 suspected more than 72 h away       1 none
A confirmed event on a later leg within 24 h of starting counts as 5.
"""
import argparse, json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path

NEAR_KM = 100.0
STEP_KM = 10.0
ROOT = Path(__file__).resolve().parents[1]
LEVEL_NAMES = {1: "Clear", 2: "Watch", 3: "At risk", 4: "Severe", 5: "Critical"}


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def densify(points):
    """Points along the polyline at most STEP_KM apart (linear in lat/lon, matching how geometry is drawn)."""
    out = [tuple(points[0])]
    for a, b in zip(points, points[1:]):
        n = max(1, math.ceil(km(a, b) / STEP_KM))
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1)]
    return out


def leg_points(leg):
    geo = leg.get("geometry") or []
    pts = [tuple(p) for p in geo] if len(geo) >= 2 else [(leg["from_lat"], leg["from_lon"]), (leg["to_lat"], leg["to_lon"])]
    return densify(pts)


def distance_to_leg(event, leg, now=None):
    """Closest approach of the leg to the event. With `now`, only the part of the leg still ahead of the vehicle
    counts: a disruption at a place the shipment has already left is behind it, not on its route."""
    e = (event["lat"], event["lon"])
    pts = leg_points(leg)
    if now is not None:
        a, b = ts(leg["planned_start"]), ts(leg["planned_end"])
        if a < now < b:  # under way: drop the share of the line already travelled (by planned time)
            pts = pts[int((now - a) / (b - a) * (len(pts) - 1)):]
    return min(km(p, e) for p in pts)


def window_overlaps(event, leg):
    return ts(event["window_start"]) <= ts(leg["planned_end"]) and ts(event["window_end"]) >= ts(leg["planned_start"])


def current_index(legs, now):
    """Index of the leg in progress, else the first unfinished leg, else None (all finished)."""
    for i, l in enumerate(legs):
        if ts(l["planned_start"]) <= now < ts(l["planned_end"]):
            return i
    for i, l in enumerate(legs):
        if ts(l["planned_end"]) > now:
            return i
    return None


def score_shipment(legs, events, now):
    """-> (level, reason, event_ids) for one shipment. `legs` sorted by seq; `events` are all active events."""
    legs = sorted(legs, key=lambda l: l["seq"])
    cur = current_index(legs, now)
    best = (1, "No event on any remaining leg", [])
    hits = []  # (level, reason, event_id)
    if cur is None:
        return best
    for ev in events:
        if ts(ev["window_end"]) < now:
            continue
        conf = ev["status"] == "confirmed"
        kind = f"{ev['type']} at {ev['location']}"
        on = [(i, l) for i, l in enumerate(legs) if i >= cur and window_overlaps(ev, l)
              and distance_to_leg(ev, l, now) <= ev["radius_km"]]
        if on:
            i, leg = on[0]
            away = max(0.0, (ts(leg["planned_start"]) - now).total_seconds() / 3600)
            if conf and i - cur <= 1:
                where = "current" if i == cur else "next"
                hits.append((5, f"Confirmed {kind} on the {where} leg", ev["event_id"]))
            elif conf and away > 24:
                hits.append((4, f"Confirmed {kind} on a later leg, more than 24 h away", ev["event_id"]))
            elif conf:
                hits.append((5, f"Confirmed {kind} on a later leg starting within 24 h", ev["event_id"]))
            elif away <= 72:
                hits.append((3, f"Suspected {kind} on a leg within 72 h", ev["event_id"]))
            else:
                hits.append((2, f"Suspected {kind}, more than 72 h before the shipment reaches it", ev["event_id"]))
        elif conf:
            gaps = [distance_to_leg(ev, l, now) for i, l in enumerate(legs) if i >= cur]
            # near = spatially off the route; an on-route event outside the time window is simply not relevant
            if min(gaps) > ev["radius_km"] and min(gaps) <= ev["radius_km"] + NEAR_KM:
                hits.append((3, f"Confirmed {kind} near the route", ev["event_id"]))
    if not hits:
        return best
    top = max(h[0] for h in hits)
    chosen = sorted((h for h in hits if h[0] == top), key=lambda h: h[2])
    return top, chosen[0][1], sorted({h[2] for h in chosen})


def score_fleet(shipments, legs, events, now):
    """Rows for `shipment_risk` (shipment_id, level, reason, event_ids), one per shipment, sorted by id."""
    by_ship = {}
    for l in legs:
        by_ship.setdefault(l["shipment_id"], []).append(l)
    out = []
    for s in sorted(shipments, key=lambda s: s["shipment_id"]):
        level, reason, ids = score_shipment(by_ship.get(s["shipment_id"], []), events, now)
        out.append({"shipment_id": s["shipment_id"], "level": level, "reason": reason, "event_ids": ids})
    return out


def load(d):
    """Read the tables from `d`; any table missing there (e.g. events next to pipelines/seed) comes from demo/fixtures."""
    def one(t):
        for base in (Path(d), ROOT / "demo" / "fixtures"):
            if (base / f"{t}.json").exists():
                return json.loads((base / f"{t}.json").read_text())
        raise SystemExit(f"{t}.json not found in {d} or demo/fixtures")
    return {t: one(t) for t in ("shipments", "legs", "disruption_events", "shipment_risk")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixtures", default=str(ROOT / "demo" / "fixtures"))
    ap.add_argument("--now", help="ISO time; default is the current UTC time")
    ap.add_argument("--out"); ap.add_argument("--compare", action="store_true")
    a = ap.parse_args()
    now = ts(a.now) if a.now else datetime.now(timezone.utc)
    t = load(a.fixtures)
    rows = score_fleet(t["shipments"], t["legs"], t["disruption_events"], now)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1) + "\n")
    if a.compare:
        want = {r["shipment_id"]: r for r in t["shipment_risk"]}
        diffs = 0
        for r in rows:
            w = want.get(r["shipment_id"])
            if w and w["level"] != r["level"]:
                diffs += 1
                print(f"DIFF {r['shipment_id']}: computed {r['level']} ({r['reason']}), file says {w['level']} ({w['reason']})")
        print(f"{len(rows)} shipments, {diffs} differ from shipment_risk.json at {now:%Y-%m-%dT%H:%MZ}")
    elif not a.out:
        for r in rows:
            print(f"{r['shipment_id']}  {r['level']} {LEVEL_NAMES[r['level']]:8} {r['reason']}  {r['event_ids']}")


if __name__ == "__main__":
    main()
