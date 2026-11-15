"""Regenerate the sample rows in demo/fixtures: fixes to the original six shipments plus a UK and Europe example operator.
Run from the repo root on a clean checkout of the original six-shipment fixtures: python demo/make_fixtures.py demo/fixtures
Risk rows are written by pipelines/risk_job.py at the fixture time, not by hand."""
import json, pathlib, sys
F = pathlib.Path(sys.argv[1])
load = lambda t: json.loads((F / f"{t}.json").read_text())
def save(t, rows): (F / f"{t}.json").write_text(json.dumps(rows, indent=2) + "\n")
T = lambda day, hm: f"2026-11-{day:02d}T{hm}:00Z"

ships, legs, events, evidence, risk = (load(t) for t in ("shipments", "legs", "disruption_events", "evidence", "shipment_risk"))
scen_changes = load("scenario_changes")
by = lambda rows, key, val: next(r for r in rows if r[key] == val)

# --- fixes to the original six ---
# S-1002: it had already left Rotterdam when the strike began. Now it loads at Rotterdam during the strike.
l = by(legs, "shipment_id", "S-1002"); l["planned_start"], l["planned_end"] = T(15, "06:00"), T(16, "10:00")
by(risk, "shipment_id", "S-1002")["reason"] = "Confirmed strike at Rotterdam, where the shipment loads on the next leg"
by(scen_changes, "shipment_id", "S-1002")["new_planned_start"] = T(18, "06:00")
# S-1001: the closure window was a week after the ship passes Suez.
e = by(events, "event_id", "E-2"); e["window_start"], e["window_end"] = T(20, "00:00"), T(22, "00:00")
e["summary"] = "Suez Canal closed to transits after a grounding; convoys suspended."
# S-1003: a two-day flight. Now twelve hours, in the air.
l = by(legs, "shipment_id", "S-1003"); l["planned_start"], l["planned_end"] = T(14, "08:00"), T(14, "20:00")
by(ships, "shipment_id", "S-1003")["eta"] = T(14, "20:00")
# S-1006: the leg ended three days before the warning it was linked to. Now two legs, the second into Dallas.
l = by(legs, "shipment_id", "S-1006"); ep = [31.76, -106.49]
l2 = dict(l, seq=2, from_name="El Paso", from_lat=ep[0], from_lon=ep[1], geometry=[ep, [32.3, -101.5], l["geometry"][-1]],
          planned_start=T(18, "06:00"), planned_end=T(19, "12:00"))
l.update(to_name="El Paso", to_lat=ep[0], to_lon=ep[1], geometry=[l["geometry"][0], [32.7, -112.0], ep], planned_end=T(17, "06:00"))
legs.insert(legs.index(l) + 1, l2)
# S-1004: it called at Rotterdam during the strike, which is Critical by the rules, not At risk. It now calls at
# Antwerp, close to the strike but not in it.
an = [51.26, 4.40]
a, b = [x for x in legs if x["shipment_id"] == "S-1004"]
a.update(to_name="Antwerp", to_lat=an[0], to_lon=an[1], geometry=a["geometry"][:-1] + [an])
b.update(from_name="Antwerp", from_lat=an[0], from_lon=an[1],
         geometry=[an, [51.45, 3.5], [52.6, 3.6], [53.7, 5.5], [54.0, 7.8], [53.9, 8.7], b["geometry"][-1]])

# S-1005: at the fixture time it was still inside the Felixstowe closure area. It left a day earlier.
[x for x in legs if x["shipment_id"] == "S-1005"][0]["planned_start"] = T(13, "12:00")

# --- places ---
P = {"Rotterdam": (51.95, 4.14), "Felixstowe": (51.96, 1.35), "Grangemouth": (56.03, -3.70), "Birmingham": (52.48, -1.89),
     "Glasgow": (55.86, -4.25), "Carlisle": (54.89, -2.93), "Manchester": (53.48, -2.24), "London": (51.51, -0.13),
     "Dover": (51.13, 1.31), "Calais": (50.97, 1.85), "Lille": (50.63, 3.06), "Brussels": (50.85, 4.35),
     "London Heathrow": (51.47, -0.45), "Frankfurt": (50.03, 8.57), "Hamburg": (53.54, 9.98), "Immingham": (53.63, -0.19),
     "Zeebrugge": (51.33, 3.20), "London (Hayes)": (51.51, -0.42), "Madrid": (40.47, -3.56), "Southampton": (50.90, -1.40), "Bristol": (51.45, -2.59), "Dublin": (53.35, -6.20), "Liverpool": (53.45, -3.02)}
SEA = {("Zeebrugge", "Felixstowe"): [(51.5, 2.6), (51.8, 1.9)],
       ("Grangemouth", "Immingham"): [(56.1, -2.5), (55.0, -0.9), (54.0, 0.2)],
       ("Hamburg", "Immingham"): [(53.9, 8.7), (54.05, 7.4), (53.85, 4.5), (53.75, 1.2)],
       ("Dublin", "Liverpool"): [(53.42, -5.2), (53.55, -3.6)]}
ROAD = {("Glasgow", "Carlisle"): [(55.3, -3.45)], ("Carlisle", "Manchester"): [(54.05, -2.75)],
        ("Manchester", "Birmingham"): [(53.0, -2.2)], ("Birmingham", "London"): [(52.0, -1.0)], ("Birmingham", "London (Hayes)"): [(52.0, -1.1)],
        ("Immingham", "Birmingham"): [(53.2, -1.2)], ("London", "Dover"): [(51.3, 0.6)],
        ("Calais", "Lille"): [(50.8, 2.5)], ("Lille", "Brussels"): [(50.75, 3.8)], ("Southampton", "Bristol"): [(51.2, -2.0)],
        ("Liverpool", "Manchester"): [(53.45, -2.6)]}

def leg(sid, seq, mode, a, b, start, end):
    mid = (SEA if mode == "ship" else ROAD).get((a, b), [])
    if mode == "plane": mid = [((P[a][0] + P[b][0]) / 2 + 0.6, (P[a][1] + P[b][1]) / 2)]
    geom = [list(P[a]), *[list(m) for m in mid], list(P[b])]
    return {"shipment_id": sid, "seq": seq, "mode": mode, "from_name": a, "from_lat": P[a][0], "from_lon": P[a][1],
            "to_name": b, "to_lat": P[b][0], "to_lon": P[b][1], "geometry": geom, "planned_start": start, "planned_end": end}

NEW = [  # shipment, cargo, main mode, legs (mode, from, to, start, end), risk level, reason, event ids
 ("S-1007", "Chilled produce, 12 reefers", "ship", [("ship", "Zeebrugge", "Felixstowe", T(14, "22:00"), T(15, "07:00"))],
  5, "Confirmed port closure at Felixstowe on the next leg, inside its window", ["E-5"]),
 ("S-1008", "Whisky, 20 TEU", "ship", [("ship", "Grangemouth", "Immingham", T(14, "02:00"), T(15, "06:00")),
                                       ("truck", "Immingham", "Birmingham", T(15, "09:00"), T(15, "12:30"))],
  1, "No event on any remaining leg", []),
 ("S-1009", "Retail stock, 26 pallets", "truck", [("truck", "Glasgow", "Carlisle", T(15, "18:00"), T(15, "20:00")),
                                                  ("truck", "Carlisle", "Manchester", T(15, "20:30"), T(15, "22:30")),
                                                  ("truck", "Manchester", "Birmingham", T(16, "05:00"), T(16, "07:00")),
                                                  ("truck", "Birmingham", "London (Hayes)", T(16, "07:30"), T(16, "10:00"))],
  3, "Suspected road closure near Carlisle on the first legs, within 72 h", ["E-6"]),
 ("S-1010", "Medical devices, 8 pallets", "truck", [("truck", "Birmingham", "London", T(17, "15:30"), T(17, "18:30")),
                                                    ("truck", "London", "Dover", T(17, "20:00"), T(17, "22:00")),
                                                    ("truck", "Dover", "Calais", T(18, "00:00"), T(18, "02:00")),
                                                    ("truck", "Calais", "Lille", T(18, "02:30"), T(18, "04:00")),
                                                    ("truck", "Lille", "Brussels", T(18, "04:30"), T(18, "06:00"))],
  4, "Confirmed strike at Calais on a later leg, more than 24 h away", ["E-3"]),
 ("S-1011", "Aerospace parts, 3 pallets", "plane", [("plane", "London Heathrow", "Madrid", T(19, "14:00"), T(19, "16:20"))],
  2, "Suspected strike at Heathrow, more than 72 h before departure", ["E-7"]),
 ("S-1012", "Steel coil, 400 t", "ship", [("ship", "Hamburg", "Immingham", T(13, "22:00"), T(15, "04:00"))],
  1, "No event on any remaining leg", []),
 ("S-1013", "Furniture, 14 pallets", "truck", [("truck", "Southampton", "Bristol", T(14, "10:00"), T(14, "13:00"))],
  1, "No event on any remaining leg", []),
 ("S-1014", "Dairy, 6 reefers", "ship", [("ship", "Dublin", "Liverpool", T(14, "21:00"), T(15, "05:00")),
                                         ("truck", "Liverpool", "Manchester", T(15, "07:00"), T(15, "08:00"))],
  1, "No event on any remaining leg", []),
]
keep = lambda rows, key: [r for r in rows if r[key] < "S-1007"]
ships, legs, risk = keep(ships, "shipment_id"), keep(legs, "shipment_id"), keep(risk, "shipment_id")
for sid, cargo, mode, ls, level, reason, eids in NEW:
    ships.append({"shipment_id": sid, "cargo": cargo, "origin": ls[0][1], "destination": ls[-1][2], "mode": mode,
                  "eta": ls[-1][4], "is_demo_fleet": True})
    legs += [leg(sid, i + 1, *x) for i, x in enumerate(ls)]
    risk.append({"shipment_id": sid, "level": level, "reason": reason, "event_ids": eids})

events = [e for e in events if e["event_id"] <= "E-4"] + [
 {"event_id": "E-5", "type": "closure", "status": "confirmed", "location": "Port of Felixstowe", "lat": 51.96, "lon": 1.35,
  "window_start": T(15, "04:00"), "window_end": T(16, "04:00"), "is_fixture": True,
  "summary": "Port of Felixstowe suspends vessel and crane operations in high winds.", "radius_km": 20, "detected_at": T(14, "10:30")},
 {"event_id": "E-6", "type": "closure", "status": "suspected", "location": "M6 near Carlisle", "lat": 54.89, "lon": -2.93,
  "window_start": T(15, "12:00"), "window_end": T(16, "00:00"), "is_fixture": True,
  "summary": "Report of a planned overnight M6 closure near Carlisle for bridge works.", "radius_km": 15, "detected_at": T(14, "09:40")},
 {"event_id": "E-7", "type": "strike", "status": "suspected", "location": "London Heathrow", "lat": 51.47, "lon": -0.45,
  "window_start": T(19, "00:00"), "window_end": T(20, "00:00"), "is_fixture": True,
  "summary": "Ground handling staff at Heathrow are balloting on a one-day strike.", "radius_km": 15, "detected_at": T(14, "08:20")},
]
def cite(vid, eid, claim, host, title, at, official=False):
    return {"evidence_id": vid, "event_id": eid, "claim": "SAMPLE: " + claim, "url": f"https://{host}/sample/{vid.lower()}",
            "title": title, "retrieved_at": at, "published_at": at, "domain": host, "is_official": official}
evidence = [v for v in evidence if v["event_id"] <= "E-4"] + [
 cite("V-8", "E-5", "port suspends vessel operations as gusts pass the working limit", "felixstowe-port.invalid", "Sample port notice", T(14, "10:20"), True),
 cite("V-9", "E-5", "ships held off Felixstowe as storm closes the quay", "sample-news-g.invalid", "Sample source G", T(14, "10:45")),
 cite("V-10", "E-6", "overnight closure of the M6 near Carlisle reported for bridge works", "sample-news-h.invalid", "Sample source H", T(14, "09:35")),
 cite("V-11", "E-7", "ground handlers at Heathrow to vote on a one-day walkout", "sample-news-i.invalid", "Sample source I", T(14, "08:15")),
]
for t, rows in (("shipments", ships), ("legs", legs), ("disruption_events", events), ("evidence", evidence),
                ("shipment_risk", risk), ("scenario_changes", scen_changes)):
    save(t, rows)
# The moment these rows were written for. The app shifts every timestamp so that this is always "now".
(F / "clock.json").write_text(json.dumps({"as_of": T(14, "12:00")}, indent=2) + "\n")
print(len(ships), "shipments,", len(legs), "legs,", len(events), "events,", len(evidence), "evidence")

import subprocess
subprocess.run([sys.executable, str(F.parent.parent / "pipelines" / "risk_job.py"), "--fixtures", str(F), "--now", T(14, "12:00"),
                "--out", str(F / "shipment_risk.json")], check=True)
