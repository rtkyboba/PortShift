"""Check shipment_risk rows against the risk-level rules in AGENTS.md (table "Risk levels").

  python evals/check_risk.py [DIR]     # DIR holds shipment_risk, disruption_events, evidence, legs (.json)
Only constraints that need no judgement call are enforced:
  level 1          lists no events
  level 2..5       lists at least one event, and every listed event exists
  level 2          cites only SUSPECTED events (a confirmed event means level 3+)
  level 4, 5       cite at least one CONFIRMED event
  level 2, 4, 5    the cited event must lie on the route (within radius_km of a leg stop or geometry point)
  confirmed        events must meet the contract rule (2 domains or 1 official) - see check_citations.py
Exit code 1 on any failure. This does not recompute levels; the real scorer lives in pipelines/.
Default DIR: demo/fixtures if present, else app/dev_fixtures.
"""
import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def route_points(legs):
    pts = []
    for l in legs:
        pts += [(l["from_lat"], l["from_lon"]), (l["to_lat"], l["to_lon"])]
        pts += [tuple(p) for p in l.get("geometry") or []]
    return pts


def check(d):
    L = lambda t: json.loads((d / f"{t}.json").read_text())
    risk, events, legs = L("shipment_risk"), {e["event_id"]: e for e in L("disruption_events")}, L("legs")
    fails = []
    for r in risk:
        sid, lvl = r["shipment_id"], r["level"]
        ids = r["event_ids"]
        evs = [events[i] for i in ids if i in events]
        for i in ids:
            if i not in events:
                fails.append(f"{sid}: cites unknown event {i}")
        if lvl == 1 and ids:
            fails.append(f"{sid}: level 1 (Clear) but lists events {ids}")
        if lvl >= 2 and not ids:
            fails.append(f"{sid}: level {lvl} but no events")
        if lvl == 2 and any(e["status"] == "confirmed" for e in evs):
            fails.append(f"{sid}: level 2 (Watch) cites a confirmed event; confirmed events are level 3+")
        if lvl >= 4 and ids and not any(e["status"] == "confirmed" for e in evs):
            fails.append(f"{sid}: level {lvl} needs a CONFIRMED event but cites only suspected {ids}")
        if lvl in (2, 4, 5) and evs:
            pts = route_points([l for l in legs if l["shipment_id"] == sid])
            on = [e for e in evs if pts and min(km(p, (e["lat"], e["lon"])) for p in pts) <= e.get("radius_km", 0)]
            if not on:
                fails.append(f"{sid}: level {lvl} but no cited event lies within its radius of the route")
    return fails, len(risk)


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "demo/fixtures" if (ROOT / "demo/fixtures").exists() else ROOT / "app/dev_fixtures")
    fails, n = check(d)
    for f in fails:
        print("FAIL", f)
    print(f"{'FAIL' if fails else 'ok'}: {n} shipments checked, {len(fails)} failures")
    sys.exit(bool(fails))
