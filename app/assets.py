"""The operator's own transport: vehicles they run, and space they have booked with carriers.

Two kinds of record, as operators keep them:
- a **vehicle**: a truck (the usual case), or a ship or plane the operator owns or charters;
- **booked capacity**: space agreed with a carrier on a lane (a sea allocation or an air allotment).

Status is worked out from the bookings and the clock, never typed: Off road (set by hand, until a date),
In transit (a booking covers now), Allocated (a booking starts later), else Available.

A sample fleet stands in until the operator adds their own. Added records and bookings are kept in files on this
server, like the operator's own rates (`costing.py`); Delta tables are the durable home.
"""
import json
import math
import os
from datetime import datetime, timezone

import costing
import data
import planner

MODES = ("truck", "ship", "plane")
UNITS = ("pallet", "container_20", "container_40", "trailer", "kg")
MAX_EMPTY_KM = 300  # a truck is not offered for a pickup further than this from its depot
STATUS = {"available": "Available", "allocated": "Allocated", "in_transit": "In transit", "off_road": "Off road"}

# (id, name, registration, body, pallets, payload kg, home depot, reefer, ADR, EUR per km, EUR per day)
_TRUCKS = [
    ("TR-01", "Artic 01", "SN24 KXA", "curtainsider", 26, 25000, "Glasgow warehouse", False, False, 1.05, 180),
    ("TR-02", "Artic 02", "SN24 KXB", "curtainsider", 26, 25000, "Glasgow warehouse", False, True, 1.05, 180),
    ("TR-03", "Reefer 03", "SK73 LLF", "refrigerated", 26, 23500, "Edinburgh warehouse", True, False, 1.25, 210),
    ("TR-04", "Artic 04", "YK24 PDO", "curtainsider", 26, 25000, "Leeds warehouse", False, False, 1.05, 180),
    ("TR-05", "Rigid 05", "MX73 HTU", "box, tail lift", 14, 9000, "Manchester warehouse", False, False, 0.85, 140),
    ("TR-06", "Artic 06", "BX24 RNE", "curtainsider", 26, 25000, "Birmingham warehouse", False, False, 1.05, 180),
    ("TR-07", "Artic 07", "BX24 RNF", "curtainsider", 26, 25000, "Birmingham warehouse", False, True, 1.05, 180),
    ("TR-08", "Reefer 08", "LK73 VZG", "refrigerated", 26, 23500, "London warehouse (Hayes)", True, False, 1.25, 210),
    ("TR-09", "Rigid 09", "WU24 CJA", "box, tail lift", 14, 9000, "Bristol warehouse", False, False, 0.85, 140),
    ("TR-10", "Artic 10", "FR-482-KM", "curtainsider", 33, 24500, "Lille warehouse", False, False, 0.98, 170),
]
# (id, carrier, service, mode, from, to, capacity, unit, cut-off hours, rate, rate unit)
_SPACE = [
    ("CAP-01", "Evercore Line", "North Sea shuttle", "ship", "Rotterdam", "Felixstowe", 12, "container_40", 24, 780, "container_40"),
    ("CAP-02", "Channel RoRo", "Short straits ferry", "ship", "Calais", "Dover", 8, "trailer", 2, 240, "trailer"),
    ("CAP-03", "Clyde Feeder", "West coast feeder", "ship", "Greenock", "Liverpool", 10, "container_20", 24, 410, "container_20"),
    ("CAP-04", "Northair Cargo", "Daily freighter", "plane", "Brussels Airport", "Glasgow Airport", 4000, "kg", 6, 1.45, "kg"),
    ("CAP-05", "Northair Cargo", "Daily freighter", "plane", "London Heathrow", "Frankfurt Airport", 3000, "kg", 6, 1.30, "kg"),
]


def samples() -> list[dict]:
    trucks = [{"asset_id": i, "record": "vehicle", "mode": "truck", "name": n, "registration": reg, "body": body,
               "capacity": pal, "capacity_unit": "pallet", "payload_kg": kg, "base": base, "reefer": reefer, "adr": adr,
               "cost_per_km": per_km, "cost_per_day": per_day, "off_road_until": None, "note": "", "is_sample": True}
              for i, n, reg, body, pal, kg, base, reefer, adr, per_km, per_day in _TRUCKS]
    space = [{"asset_id": i, "record": "capacity", "mode": mode, "name": f"{carrier} · {service}", "carrier": carrier,
              "service": service, "origin": frm, "destination": to, "capacity": cap, "capacity_unit": unit,
              "cutoff_hours": cutoff, "rate": rate, "rate_unit": rate_unit, "note": "", "is_sample": True}
             for i, carrier, service, mode, frm, to, cap, unit, cutoff, rate, rate_unit in _SPACE]
    return trucks + space


def _path(name: str) -> str:
    return os.path.join(costing._state_dir(), name)


def _load(name: str) -> list[dict]:
    try:
        with open(_path(name)) as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _save(name: str, rows: list[dict]) -> None:
    os.makedirs(costing._state_dir(), exist_ok=True)
    with open(_path(name), "w") as f:
        json.dump(rows, f, indent=2)


def bookings() -> list[dict]:
    return _load("fleet_bookings.json")


def _records() -> list[dict]:
    """Samples (with any hand-set changes the operator made to them) and the operator's own records."""
    saved = _load("fleet_assets.json")
    changed = {r["asset_id"]: r for r in saved if r.get("is_sample")}
    removed = {r["asset_id"] for r in saved if r.get("removed")}
    out = [changed.get(s["asset_id"], s) for s in samples() if s["asset_id"] not in removed]
    return out + [r for r in saved if not r.get("is_sample") and not r.get("removed")]


def _ts(v) -> datetime | None:
    if not v:
        return None
    try:
        t = data._ts(str(v))
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def _overlaps(b: dict, start: datetime, end: datetime) -> bool:
    return _ts(b["start"]) < end and start < _ts(b["end"])


def status_of(rec: dict, mine: list[dict], now: datetime) -> tuple[str, dict | None]:
    """(status key, the booking that explains it)."""
    off = _ts(rec.get("off_road_until"))
    if rec["record"] == "vehicle" and off and off > now:
        return "off_road", None
    current = next((b for b in mine if _ts(b["start"]) <= now < _ts(b["end"])), None)
    if current:
        return "in_transit", current
    later = sorted((b for b in mine if _ts(b["start"]) > now), key=lambda b: b["start"])
    return ("allocated", later[0]) if later else ("available", None)


def view() -> dict:
    now, all_b = data._now(), bookings()
    places = {p["name"]: p for p in planner.PLACES}
    out = []
    for r in _records():
        mine = [b for b in all_b if b["asset_id"] == r["asset_id"]]
        key, why = status_of(r, mine, now)
        row = {**r, "status": key, "status_label": STATUS[key], "bookings": sorted(mine, key=lambda b: b["start"]),
               "busy_with": why["label"] if why else None, "free_from": why["end"] if why else None}
        if r["record"] == "capacity":  # space is shared: what is in use right now, rather than one job at a time
            used = sum(b.get("units") or 0 for b in mine if _ts(b["end"]) > now)
            row.update(used=used, free=max(0, r["capacity"] - used),
                       status="available" if used < r["capacity"] else "allocated")
            row["status_label"] = f"{_n(row['free'])} of {_n(r['capacity'])} free"
        else:
            row["place"] = places.get(r.get("base"))
        out.append(row)
    counts = {k: sum(1 for r in out if r["record"] == "vehicle" and r["status"] == k) for k in STATUS}
    return {"assets": out, "counts": counts, "bookings": sorted(all_b, key=lambda b: b["start"], reverse=True),
            "is_sample": any(r.get("is_sample") for r in out), "units": UNITS, "modes": MODES, "status_names": STATUS,
            "stored": "this app's files on the server",
            "note": "Demo fleet: sample vehicles and booked capacity stand in for yours. Status is worked out from the "
                    "bookings below. Reserving a vehicle here holds it in PortShift only; nothing is sent to a carrier or driver."}


def _n(v) -> str:
    return f"{v:,.0f}" if float(v) == int(v) else f"{v:,.1f}"


# ---- adding and changing records ----------------------------------------------------------------

def _num(v, name, low=0.0, high=1e7, whole=False, required=False):
    if v in (None, ""):
        if required:
            raise ValueError(f"{name} is needed.")
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number.")
    if not (low <= n <= high) or math.isnan(n):
        raise ValueError(f"{name} must be between {low:g} and {high:g}.")
    return int(n) if whole else n


def _text(v, limit=80) -> str:
    return str(v or "").strip()[:limit]


def clean(body: dict) -> dict:
    """A record as stored, from what the form sent. Raises ValueError with a sentence the operator can act on."""
    record = body.get("record") if body.get("record") in ("vehicle", "capacity") else "vehicle"
    mode = body.get("mode") if body.get("mode") in MODES else "truck"
    unit = body.get("capacity_unit") if body.get("capacity_unit") in UNITS else ("pallet" if mode == "truck" else "kg" if mode == "plane" else "container_40")
    out = {"record": record, "mode": mode, "capacity": _num(body.get("capacity"), "Capacity", 0.1, 1e6, required=True),
           "capacity_unit": unit, "note": _text(body.get("note"), 160)}
    if record == "vehicle":
        out["name"] = _text(body.get("name"))
        if not out["name"]:
            raise ValueError("Give the vehicle a name or fleet number.")
        base = _text(body.get("base"))
        known = {p["name"] for p in planner.PLACES}
        if base not in known:
            raise ValueError("Choose where it is based from the list of places.")
        off = _text(body.get("off_road_until"), 30)
        if off and not _ts(off):
            raise ValueError("Off road until must be a date.")
        out.update(registration=_text(body.get("registration"), 20), body=_text(body.get("body"), 40), base=base,
                   payload_kg=_num(body.get("payload_kg"), "Payload", 0, 5e8), reefer=bool(body.get("reefer")),
                   adr=bool(body.get("adr")), cost_per_km=_num(body.get("cost_per_km"), "Cost per km", 0, 1000),
                   cost_per_day=_num(body.get("cost_per_day"), "Cost per day", 0, 1e6), off_road_until=off or None)
    else:
        if mode == "truck":
            raise ValueError("Booked capacity is for sea or air. Add a truck as a vehicle.")
        out.update(carrier=_text(body.get("carrier")), service=_text(body.get("service")), origin=_text(body.get("origin")),
                   destination=_text(body.get("destination")), cutoff_hours=_num(body.get("cutoff_hours"), "Cut-off", 0, 240) or 0,
                   rate=_num(body.get("rate"), "Rate", 0, 1e6), rate_unit=unit)
        if not out["carrier"]:
            raise ValueError("Say which carrier the space is booked with.")
        kind = planner.MODE_KIND[mode]
        ok = {p["name"] for p in planner.PLACES if p["kind"] == kind}
        for end in ("origin", "destination"):
            if out[end] not in ok:
                raise ValueError(f"Choose the {end} from the list of {kind}s.")
        out["name"] = f"{out['carrier']} · {out['service'] or 'booked space'}"
    return out


def add(body: dict) -> dict:
    row = clean(body)
    saved = _load("fleet_assets.json")
    prefix = {"truck": "TR", "ship": "SH", "plane": "PL"}[row["mode"]] if row["record"] == "vehicle" else "CAP"
    taken = {r["asset_id"] for r in samples()} | {r.get("asset_id") for r in saved}
    n = 11
    while f"{prefix}-{n:02d}" in taken:
        n += 1
    row.update(asset_id=f"{prefix}-{n:02d}", is_sample=False)
    _save("fleet_assets.json", saved + [row])
    return row


def update(asset_id: str, body: dict) -> dict:
    current = next((r for r in _records() if r["asset_id"] == asset_id), None)
    if current is None:
        raise KeyError(asset_id)
    row = {**clean({**current, **body, "record": current["record"]}), "asset_id": asset_id, "is_sample": bool(current.get("is_sample"))}
    saved = [r for r in _load("fleet_assets.json") if r.get("asset_id") != asset_id]
    _save("fleet_assets.json", saved + [row])
    return row


def remove(asset_id: str) -> bool:
    current = next((r for r in _records() if r["asset_id"] == asset_id), None)
    if current is None:
        return False
    saved = [r for r in _load("fleet_assets.json") if r.get("asset_id") != asset_id]
    if current.get("is_sample"):
        saved.append({"asset_id": asset_id, "is_sample": True, "removed": True})
    _save("fleet_assets.json", saved)
    _save("fleet_bookings.json", [b for b in bookings() if b["asset_id"] != asset_id])
    return True


# ---- which of them can carry a leg ---------------------------------------------------------------

def _needs(rec: dict, cargo: dict) -> tuple[float, str | None]:
    """How much of this record's capacity the cargo takes, and why it cannot, if it cannot."""
    units, kind, kg = float(cargo.get("units") or 1), cargo.get("unit_type") or "pallet", cargo.get("weight_kg")
    unit = rec["capacity_unit"]
    if unit == "kg":
        return (float(kg) if kg else units * costing.EST_KG.get(kind, 300.0)), None  # no weight given: the costing estimate
    if unit == kind:
        return units, None
    if kind == "pallet" and unit == "trailer":
        return math.ceil(units / costing.PALLETS_PER_TRUCK), None
    if kind == "pallet" and unit in ("container_20", "container_40"):
        per = costing.PALLETS_PER_20FT * (2 if unit == "container_40" else 1)
        return math.ceil(units / per), None
    if kind == "trailer" and unit == "pallet":
        return units * costing.PALLETS_PER_TRUCK, None
    return 0, f"carries {unit.replace('_', ' ')}s, not {kind.replace('_', ' ')}s"


def candidates(legs: list[dict], cargo: dict | None, needs: dict | None = None) -> list[dict]:
    """For each leg, the operator's vehicles and booked space that could carry it, best first, each with why not."""
    cargo, needs = planner.clean_cargo(cargo), needs or {}
    now, all_b = data._now(), bookings()
    places = {p["name"]: p for p in planner.PLACES}
    out = []
    for leg in legs:
        start, end = _ts(leg["planned_start"]), _ts(leg["planned_end"])
        rows = []
        for r in _records():
            if r["mode"] != leg["mode"]:
                continue
            mine = [b for b in all_b if b["asset_id"] == r["asset_id"]]
            need, why = _needs(r, cargo)
            row = {"asset_id": r["asset_id"], "name": r["name"], "record": r["record"], "registration": r.get("registration"),
                   "capacity": r["capacity"], "capacity_unit": r["capacity_unit"], "needs": need, "is_sample": bool(r.get("is_sample"))}
            if r["record"] == "vehicle":
                off = _ts(r.get("off_road_until"))
                clash = next((b for b in mine if _overlaps(b, start, end)), None)
                if why is None and need > r["capacity"]:
                    why = f"holds {_n(r['capacity'])} {r['capacity_unit'].replace('_', ' ')}s, this needs {_n(need)}"
                if why is None and cargo.get("weight_kg") and r.get("payload_kg") and cargo["weight_kg"] > r["payload_kg"]:
                    why = f"payload {_n(r['payload_kg'])} kg, this weighs {_n(cargo['weight_kg'])} kg"
                if why is None and needs.get("reefer") and not r.get("reefer"):
                    why = "not refrigerated"
                if why is None and needs.get("adr") and not r.get("adr"):
                    why = "not certified for dangerous goods"
                if why is None and off and off > start:
                    why = f"off road until {off.strftime('%d %b').lstrip('0')}"
                if why is None and clash:
                    why = f"on {clash['label']} until {_ts(clash['end']).strftime('%d %b, %H:%M').lstrip('0')}"
                base = places.get(r.get("base"))
                empty_km = round(planner.km([base["lat"], base["lon"]], [leg["from_lat"], leg["from_lon"]]) * planner.ROAD_FACTOR) if base else 0
                if why is None and empty_km > MAX_EMPTY_KM:
                    why = f"based {_n(empty_km)} km away at {r.get('base')}"
                days = max(1, math.ceil(leg["hours"] / 24))
                cost = None
                if r.get("cost_per_km") is not None or r.get("cost_per_day") is not None:
                    cost = round((r.get("cost_per_km") or 0) * (leg["km"] + empty_km) + (r.get("cost_per_day") or 0) * days, 2)
                row.update(base=r.get("base"), empty_km=empty_km, cost=cost, sort=(empty_km, cost or 0),
                           cost_formula=f"{_n(leg['km'] + empty_km)} km ({_n(empty_km)} km empty from {r.get('base')}) x EUR {r.get('cost_per_km') or 0:g} + {days} day{'s' if days != 1 else ''} x EUR {r.get('cost_per_day') or 0:g}" if cost is not None else None)
            else:
                if r["origin"] != leg["from_name"] or r["destination"] != leg["to_name"]:
                    continue  # booked on another lane: not a candidate at all
                used = sum(b.get("units") or 0 for b in mine if _overlaps(b, start, end))
                free = r["capacity"] - used
                if why is None and need > free:
                    why = f"{_n(free)} {r['capacity_unit'].replace('_', ' ')}{'' if r['capacity_unit'] == 'kg' else 's'} free at that time, this needs {_n(need)}"
                cost = round(r["rate"] * need, 2) if r.get("rate") is not None and why is None else None
                row.update(free=free, cost=cost, sort=(0, cost or 0), carrier=r["carrier"],
                           cost_formula=f"{_n(need)} x EUR {r['rate']:g} per {r['capacity_unit'].replace('_', ' ')} (your booked rate)" if cost is not None else None)
            row.update(ok=why is None, why_not=why)
            rows.append(row)
        rows.sort(key=lambda x: (not x["ok"], x.pop("sort")))
        out.append({"seq": leg["seq"], "mode": leg["mode"], "from_name": leg["from_name"], "to_name": leg["to_name"],
                    "market_cost": leg.get("cost"), "candidates": rows,
                    "suggested_id": next((x["asset_id"] for x in rows if x["ok"]), None)})
    taken = set()  # the suggestion is greedy: nearest that fits, and one truck is not suggested for two overlapping legs
    for leg, src in zip(out, legs):
        for x in leg["candidates"]:
            if x["ok"] and (x["record"] == "capacity" or x["asset_id"] not in taken):
                leg["suggested_id"] = x["asset_id"]
                if x["record"] == "vehicle":
                    taken.add(x["asset_id"])
                break
        else:
            leg["suggested_id"] = None
    return out


def reserve(label: str, legs: list[dict], picks: dict, cargo: dict | None, needs: dict | None = None) -> dict:
    """Hold the chosen vehicle or space for each leg. picks: {seq: asset_id}. Raises ValueError if one no longer fits."""
    chosen = {int(k): v for k, v in (picks or {}).items() if v}
    if not chosen:
        raise ValueError("Choose a vehicle or booked space for at least one leg.")
    offered = {c["seq"]: c for c in candidates(legs, cargo, needs)}
    by_seq = {l["seq"]: l for l in legs}
    rows, seen = [], {}
    for seq, asset_id in chosen.items():
        leg, offer = by_seq.get(seq), offered.get(seq)
        cand = next((x for x in (offer or {}).get("candidates", []) if x["asset_id"] == asset_id), None)
        if leg is None or cand is None:
            raise ValueError(f"{asset_id} cannot carry leg {seq}.")
        if not cand["ok"]:
            raise ValueError(f"{cand['name']} cannot take leg {seq}: {cand['why_not']}.")
        if cand["record"] == "vehicle":
            for other in seen.get(asset_id, []):
                if _ts(other["planned_start"]) < _ts(leg["planned_end"]) and _ts(leg["planned_start"]) < _ts(other["planned_end"]):
                    raise ValueError(f"{cand['name']} is chosen for two legs that overlap.")
            seen.setdefault(asset_id, []).append(leg)
        rows.append({"asset_id": asset_id, "label": _text(label, 80) or "Planned shipment", "seq": seq, "mode": leg["mode"],
                     "from_name": leg["from_name"], "to_name": leg["to_name"], "start": leg["planned_start"],
                     "end": leg["planned_end"], "units": cand["needs"], "cost": cand.get("cost")})
    existing = bookings()
    ref = f"FB-{1001 + len({b['booking_ref'] for b in existing})}"
    made = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in rows:
        r.update(booking_ref=ref, created_at=made)
    _save("fleet_bookings.json", existing + rows)
    return {"booking_ref": ref, "bookings": rows, "note": "Held in PortShift only. Nothing is sent to a carrier or driver."}


def release(booking_ref: str) -> bool:
    rows = bookings()
    keep = [b for b in rows if b.get("booking_ref") != booking_ref]
    if len(keep) == len(rows):
        return False
    _save("fleet_bookings.json", keep)
    return True
