"""Costing: look a rate up, then show the arithmetic. No model produces any figure here.

How it prices (the way a transport management system does, kept small):
  * rate cards   - a rate per partner, mode, unit and (optionally) lane, with validity dates.
                   Unit depends on the mode: per container by sea, per kg of chargeable weight by air,
                   per km (full truck) or per pallet (part load) by road.
  * surcharges   - fuel, terminal handling, emissions, security: a percentage of the base, per unit, or flat.
  * delay terms  - a daily charge per unit once the free days run out (demurrage and detention, waiting
                   time, storage) and a rebooking fee.
  * late penalty - per day past the date promised to the customer (shipment_terms).

Lookup order for any rate: the operator's own rate where one applies (their partner, their lane, valid on
the day), else the default. Defaults are illustrative and every line says which was used. Market
benchmarks (rates.py) never price anything. One currency (EUR); nothing is converted.

Every function returns cost lines: {label, formula, amount, rate_source, partner, rate_id, note}. The
browser shows them as they are and never recomputes.
"""
import json
import math
import os
import re
from datetime import date, datetime, timedelta

import data

CURRENCY = "EUR"
UNITS = {"container_20": "container (20 ft)", "container_40": "container (40 ft)", "reefer": "reefer container",
         "tonne": "tonne", "km": "truck", "pallet": "pallet", "kg": "kg chargeable"}
MODE_UNITS = {"ship": ["container_20", "container_40", "reefer", "tonne"], "truck": ["km", "pallet"], "plane": ["kg"]}
CARGO_TYPES = {"pallet": "pallets", "container_20": "20 ft containers", "container_40": "40 ft containers",
               "reefer": "reefer containers", "trailer": "trailers", "tonne": "tonnes"}
EST_KG = {"pallet": 300.0, "container_20": 12000.0, "container_40": 20000.0, "reefer": 15000.0, "trailer": 18000.0,
          "tonne": 1000.0}  # used only when a weight is not given, and the line says so
VOLUMETRIC_KG_PER_M3 = 167.0
PALLETS_PER_TRUCK, PALLETS_PER_20FT, FULL_TRUCK_FROM, TONNES_PER_TRUCK = 26, 10, 20, 25
TABLES = ("rate_cards", "surcharges", "delay_charges")
BASES = ("percent_of_base", "per_unit", "flat")


def _state_dir():
    return os.environ.get("PORTSHIFT_STATE") or str(data._here.parent / ".portshift_live")


def _m(v: float) -> str:
    if abs(v - round(v)) < 0.00005:
        return f"{CURRENCY} {v:,.0f}"
    return f"{CURRENCY} {v:,.2f}" if abs(v) >= 1 else f"{CURRENCY} {v:.4f}".rstrip("0")


def _n(v: float) -> str:
    return f"{v:,.0f}" if abs(v - round(v)) < 0.005 else f"{v:,.1f}"


def _plural(n: float, word: str) -> str:
    if n != 1 and word.startswith("container ("):
        word = "containers" + word[len("container"):]
    elif n != 1 and not word.endswith("chargeable"):
        word += "s"
    return f"{_n(n)} {word}"


# ---- the tables ---------------------------------------------------------------------------------

def defaults(table: str) -> list[dict]:
    return data.optional_rows(table)


def operator() -> dict:
    """The operator's own rows. Kept in a file on this server for now; a Delta table is the durable home."""
    try:
        with open(os.path.join(_state_dir(), "my_rates.json")) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    return {t: [r for r in saved.get(t, []) if isinstance(r, dict)] for t in TABLES}


def _num(v, name, whole=False):
    try:
        x = float(v if v not in (None, "") else 0)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if x < 0 or math.isnan(x) or math.isinf(x):
        raise ValueError(f"{name} must be zero or more")
    return int(x) if whole else x


def _text(v, limit=80):
    return (str(v).strip()[:limit] or None) if v is not None else None


def _day(v, name):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ValueError(f"{name} must be a date (YYYY-MM-DD)")


def clean(body: dict) -> dict:
    """Validate what the operator sent. Raises ValueError with a sentence the UI can show."""
    out = {t: [] for t in TABLES}
    for i, r in enumerate(body.get("rate_cards") or []):
        mode, unit = r.get("mode"), r.get("unit")
        if mode not in MODE_UNITS or unit not in MODE_UNITS[mode]:
            raise ValueError(f"Rate {i + 1}: choose a mode and a unit that goes with it")
        if not _text(r.get("partner")):
            raise ValueError(f"Rate {i + 1}: say which partner the rate is with")
        row = {"rate_id": _text(r.get("rate_id")) or f"R-M{i + 1}", "partner": _text(r.get("partner")), "mode": mode,
               "origin": _text(r.get("origin")), "destination": _text(r.get("destination")), "unit": unit,
               "base_rate": _num(r.get("base_rate"), "Rate"), "per_km": _num(r.get("per_km"), "Per km"),
               "min_charge": _num(r.get("min_charge"), "Minimum charge"), "currency": CURRENCY,
               "valid_from": _day(r.get("valid_from"), "Valid from"), "valid_to": _day(r.get("valid_to"), "Valid to"),
               "source": "operator", "note": _text(r.get("note"), 200)}
        if not row["base_rate"] and not row["per_km"]:
            raise ValueError(f"Rate {i + 1}: enter a rate")
        if row["valid_from"] and row["valid_to"] and row["valid_to"] < row["valid_from"]:
            raise ValueError(f"Rate {i + 1}: valid to is before valid from")
        out["rate_cards"].append(row)
    ids = [r["rate_id"] for r in out["rate_cards"]]
    for i, r in enumerate(out["rate_cards"]):
        if ids.index(r["rate_id"]) != i:
            r["rate_id"] = f"R-M{i + 1}-{i}"
    for i, r in enumerate(body.get("delay_charges") or []):
        mode, unit = r.get("mode"), r.get("unit") or None
        if mode not in MODE_UNITS or (unit and unit not in MODE_UNITS[mode]):
            raise ValueError(f"Delay terms {i + 1}: choose a mode and a unit that goes with it")
        out["delay_charges"].append({
            "mode": mode, "unit": unit, "partner": _text(r.get("partner")),
            "free_days": _num(r.get("free_days"), "Free days", whole=True),
            "per_unit_per_day": _num(r.get("per_unit_per_day"), "Charge per day"),
            "rebooking_fee": _num(r.get("rebooking_fee"), "Rebooking fee"),
            "label": _text(r.get("label")) or "Delay charge", "source": "operator"})
    for i, r in enumerate(body.get("surcharges") or []):
        if r.get("mode") not in MODE_UNITS or r.get("basis") not in BASES or not _text(r.get("code")):
            raise ValueError(f"Surcharge {i + 1}: needs a code, a mode and a basis")
        out["surcharges"].append({
            "code": _text(r.get("code"), 12).upper(), "label": _text(r.get("label")) or _text(r.get("code")),
            "mode": r["mode"], "partner": _text(r.get("partner")), "basis": r["basis"],
            "value": _num(r.get("value"), "Surcharge value"), "applies_to_units": r.get("applies_to_units") or None,
            "source": "operator"})
    return out


def save_operator(body: dict) -> dict:
    rows = clean(body)
    os.makedirs(_state_dir(), exist_ok=True)
    with open(os.path.join(_state_dir(), "my_rates.json"), "w") as f:
        json.dump(rows, f, indent=2)
    return rows


# ---- lookups ------------------------------------------------------------------------------------

def _same(a, b) -> bool:
    return bool(a) and bool(b) and str(a).strip().casefold() == str(b).strip().casefold()


def _in_place(needle, place) -> bool:
    return not needle or (bool(place) and str(needle).strip().casefold() in str(place).casefold())


def validity(row: dict, when: datetime) -> str:
    d = when.date().isoformat()
    if row.get("valid_from") and d < row["valid_from"]:
        return "not yet valid"
    if row.get("valid_to") and d > row["valid_to"]:
        return "expired"
    return "active"


def _partner_ok(row: dict, partner: str | None) -> bool:
    """A rate with a partner applies to that partner's shipments. When planning (no carrier yet) any applies."""
    return partner is None or not row.get("partner") or _same(row["partner"], partner)


def rate_for(mode, unit, frm, to, km, when, partner, op) -> tuple[dict | None, str]:
    for src, rows in (("operator", op["rate_cards"]), ("default", defaults("rate_cards"))):
        fits = [r for r in rows if r["mode"] == mode and r["unit"] == unit and validity(r, when) == "active"
                and _in_place(r.get("origin"), frm) and _in_place(r.get("destination"), to)
                and (src == "default" or _partner_ok(r, partner))]
        if fits:  # the most specific lane first, then the cheapest for this distance
            return min(fits, key=lambda r: (-(bool(r.get("origin")) + bool(r.get("destination"))),
                                            r["base_rate"] + (r.get("per_km") or 0) * km)), src
    return None, "default"


def surcharges_for(mode, unit, partner, op) -> list[tuple[dict, str]]:
    out: dict[str, tuple[dict, str]] = {}
    for src, rows in (("default", defaults("surcharges")), ("operator", op["surcharges"])):
        for r in rows:
            if r["mode"] != mode or (r.get("applies_to_units") and unit not in r["applies_to_units"]):
                continue
            if src == "operator" and not _partner_ok(r, partner):
                continue
            out[r["code"]] = (r, src)  # the operator's row replaces the default with the same code
    return list(out.values())


def delay_for(mode, unit, partner, op) -> tuple[dict | None, str]:
    for src, rows in (("operator", op["delay_charges"]), ("default", defaults("delay_charges"))):
        fits = [r for r in rows if r["mode"] == mode and (not r.get("unit") or r["unit"] == unit)
                and (src == "default" or _partner_ok(r, partner))]
        if fits:
            return max(fits, key=lambda r: (bool(r.get("unit")), bool(r.get("partner")))), src
    return None, "default"


# ---- what is billed -----------------------------------------------------------------------------

_CARGO = re.compile(r"(\d+(?:\.\d+)?)\s*(TEU|reefers?|pallets?|trailers?|t)\b", re.I)
_CARGO_UNIT = {"teu": "container_20", "reefer": "reefer", "pallet": "pallet", "trailer": "trailer", "t": "tonne"}


def terms_of(ship: dict) -> dict:
    """The shipment's commercial terms: what is carried, with whom, and the date promised to the customer.
    From shipment_terms; where a shipment has no row, the unit count is read from its cargo text."""
    row = next((t for t in defaults("shipment_terms") if t["shipment_id"] == ship["shipment_id"]), None)
    if row:
        return row
    m = _CARGO.search(ship.get("cargo") or "")
    units, kind = (float(m.group(1)), _CARGO_UNIT[m.group(2).lower().rstrip("s")]) if m else (1.0, "pallet")
    return {"shipment_id": ship["shipment_id"], "carrier": None, "units": units, "unit_type": kind, "weight_kg": None,
            "volume_m3": None, "promised_by": None, "late_penalty_per_day": 0.0}


def billing(mode: str, cargo: dict) -> dict:
    """What the carrier bills for this cargo in this mode: a quantity, a unit, and how it was arrived at."""
    units, kind = float(cargo.get("units") or 1), cargo.get("unit_type") or "pallet"
    if mode == "ship":
        if kind in ("container_20", "container_40", "reefer", "tonne"):
            return {"qty": units, "unit": kind, "note": None}
        if kind == "trailer":
            return {"qty": units, "unit": "container_40", "note": "each trailer priced as a 40 ft unit"}
        n = math.ceil(units / PALLETS_PER_20FT)
        return {"qty": n, "unit": "container_20", "note": f"{_n(units)} pallets fill {n} x 20 ft container at {PALLETS_PER_20FT} pallets each"}
    if mode == "truck":
        if kind == "pallet" and units < FULL_TRUCK_FROM:
            return {"qty": units, "unit": "pallet", "note": "part load, priced per pallet"}
        if kind == "pallet":
            n = math.ceil(units / PALLETS_PER_TRUCK)
            return {"qty": n, "unit": "km", "note": f"{_n(units)} pallets is a full load: {_plural(n, 'truck')} at {PALLETS_PER_TRUCK} pallets each"}
        if kind == "tonne":
            n = math.ceil(units / TONNES_PER_TRUCK)
            return {"qty": n, "unit": "km", "note": f"{_n(units)} t needs {_plural(n, 'truck')} at {TONNES_PER_TRUCK} t each"}
        return {"qty": units, "unit": "km", "note": f"one truck per {UNITS.get(kind, kind)}"}
    weight = cargo.get("weight_kg")
    note = None
    if not weight:
        weight = units * EST_KG.get(kind, 300.0)
        note = f"weight not given: estimated at {_n(EST_KG.get(kind, 300.0))} kg per {UNITS.get(kind, kind)}"
    volumetric = (cargo.get("volume_m3") or 0) * VOLUMETRIC_KG_PER_M3
    if volumetric > weight:
        return {"qty": round(volumetric), "unit": "kg",
                "note": f"chargeable weight is the volumetric weight: {cargo['volume_m3']:g} m3 x {VOLUMETRIC_KG_PER_M3:g} kg = {_n(volumetric)} kg, more than the actual {_n(weight)} kg"}
    return {"qty": round(weight), "unit": "kg", "note": note or "chargeable weight is the actual weight"}


def _line(label, formula, amount, row=None, src="default", note=None) -> dict:
    return {"label": label, "formula": formula, "amount": round(amount, 2), "rate_source": src,
            "partner": (row or {}).get("partner") if src == "operator" else None,
            "rate_id": (row or {}).get("rate_id"), "note": note}


def _done(lines: list[dict]) -> dict:
    used = {l["rate_source"] for l in lines if l["rate_source"] in ("default", "operator")}
    basis = "operator" if used == {"operator"} else "mixed" if "operator" in used else "default"
    return {"cost": round(sum(l["amount"] for l in lines), 2), "currency": CURRENCY, "cost_lines": lines, "cost_basis": basis,
            "cost_note": {"operator": "estimate, your rates", "mixed": "estimate, your rates where you have them, illustrative rates elsewhere",
                          "default": "estimate, illustrative rates"}[basis]}


def _surcharge_lines(base: float, b: dict, mode, partner, op, percent_only=False) -> list[dict]:
    lines = []
    for s, src in surcharges_for(mode, b["unit"], partner, op):
        if percent_only and s["basis"] != "percent_of_base":
            continue  # a detour adds distance, not another port call or another booking
        if s["basis"] == "percent_of_base":
            lines.append(_line(s["label"], f"{s['value']:g}% of {_m(base)}", base * s["value"] / 100, s, src))
        elif s["basis"] == "per_unit":
            lines.append(_line(s["label"], f"{_plural(b['qty'], UNITS[b['unit']])} x {_m(s['value'])}", b["qty"] * s["value"], s, src))
        else:
            lines.append(_line(s["label"], "flat", s["value"], s, src))
    return lines


# ---- the three things that get priced -----------------------------------------------------------

def freight(mode, cargo, frm, to, km, when, partner=None, op=None) -> dict:
    """One leg: looked-up base rate x what is billed, with its minimum charge, plus surcharges."""
    op = op or operator()
    b = billing(mode, cargo)
    row, src = rate_for(mode, b["unit"], frm, to, km, when, partner, op)
    if not row:
        return _done([_line(f"Freight, {frm} to {to}", f"no {mode} rate per {UNITS[b['unit']]}", 0.0, None, "none", b["note"])])
    per_km, base_rate, unit = row.get("per_km") or 0, row["base_rate"], UNITS[b["unit"]]
    each = base_rate + per_km * km
    how = (_m(base_rate) if not per_km else f"{_m(per_km)} per km x {_n(km)} km" if not base_rate
           else f"({_m(base_rate)} + {_m(per_km)} per km x {_n(km)} km)")
    base, formula = b["qty"] * each, f"{_plural(b['qty'], unit)} x {how}"
    if base < (row.get("min_charge") or 0):
        base, formula = row["min_charge"], formula + f" = {_m(b['qty'] * each)}, below the minimum charge of {_m(row['min_charge'])}"
    lane = " (lane rate)" if row.get("origin") or row.get("destination") else ""
    lines = [_line(f"Freight, {frm} to {to}{lane}", formula, base, row, src, b["note"])]
    return _done(lines + _surcharge_lines(base, b, mode, partner, op))


def _late(ship, terms, new_eta: datetime) -> list[dict]:
    if not terms.get("promised_by") or not terms.get("late_penalty_per_day"):
        return []
    over = (new_eta - data._ts(terms["promised_by"])).total_seconds() / 86400
    if over <= 0:
        return []
    days = math.ceil(over)
    return [_line("Late delivery penalty", f"{_plural(days, 'day')} past the date promised to the customer "
                  f"({data._ts(terms['promised_by']):%d %b %H:%M}) x {_m(terms['late_penalty_per_day'])} per day",
                  days * terms["late_penalty_per_day"], None, "shipment", "from this shipment's terms (demo fleet)")]


def reschedule(ship: dict, days: int, op=None) -> dict:
    """Wait it out: the daily charge for the days beyond the free days, the rebooking fee, and the late penalty."""
    op = op or operator()
    terms = terms_of(ship)
    b = billing(ship["mode"], terms)
    row, src = delay_for(ship["mode"], b["unit"], terms.get("carrier"), op)
    lines = []
    if row:
        free = int(row.get("free_days") or 0)
        charged = max(0, days - free)
        how = f"{_plural(charged, 'chargeable day')} ({_plural(days, 'day')} less {_plural(free, 'free day')})" if free else _plural(charged, "day")
        lines.append(_line(row.get("label") or "Delay charge",
                           f"{_plural(b['qty'], UNITS[b['unit']])} x {_m(row['per_unit_per_day'])} per day x {how}",
                           b["qty"] * row["per_unit_per_day"] * charged, row, src, b["note"]))
        lines.append(_line("Rebooking fee", "flat, per booking", row["rebooking_fee"], row, src))
    else:
        lines.append(_line("Delay charge", f"no delay terms for {ship['mode']}", 0.0, None, "none"))
    lines += _late(ship, terms, data._ts(ship["eta"]) + timedelta(days=days))
    return _done(lines)


def reroute(ship: dict, extra_km: float, extra_hours: float, op=None) -> dict:
    """Go around: the extra distance at the rate's per-km part, surcharges on it, an amendment fee, late penalty."""
    op = op or operator()
    terms = terms_of(ship)
    partner, mode = terms.get("carrier"), ship["mode"]
    b = billing(mode, terms)
    when = data._now()
    row, src = rate_for(mode, b["unit"], ship["origin"], ship["destination"], extra_km, when, partner, op)
    note = b["note"]
    if row and not row.get("per_km"):  # a flat lane rate has no distance part: the detour is priced at the default
        row, src = rate_for(mode, b["unit"], None, None, extra_km, when, None, {"rate_cards": []})
        note = "your lane rate is flat, so the extra distance uses the default per-km rate"
    lines = []
    if row:
        base = b["qty"] * (row.get("per_km") or 0) * extra_km
        lines.append(_line("Extra distance", f"{_plural(b['qty'], UNITS[b['unit']])} x {_m(row.get('per_km') or 0)} per km x {_n(extra_km)} km",
                           base, row, src, note))
        lines += _surcharge_lines(base, b, mode, partner, op, percent_only=True)
    else:
        lines.append(_line("Extra distance", f"no {mode} rate per {UNITS[b['unit']]}", 0.0, None, "none"))
    drow, dsrc = delay_for(mode, b["unit"], partner, op)
    if drow:
        lines.append(_line("Amendment fee", "flat, per booking", drow["rebooking_fee"], drow, dsrc))
    lines += _late(ship, terms, data._ts(ship["eta"]) + timedelta(hours=extra_hours or 0))
    return _done(lines)


def price_option(ship: dict, option: dict, op=None) -> dict:
    """An option from the planner heuristic (keep / reschedule / reroute), priced here with its lines."""
    kind = option.get("kind")
    if kind == "reschedule" and option.get("delay_days"):
        c = reschedule(ship, int(option["delay_days"]), op)
    elif kind == "reroute" and option.get("extra_km") is not None:
        c = reroute(ship, float(option["extra_km"]), float(option.get("delay_hours") or 0), op)
    else:
        c = {"cost": 0.0, "currency": CURRENCY, "cost_lines": [], "cost_basis": "default", "cost_note": "no change, no extra cost"}
    return {**option, "extra_cost": c["cost"], "cost_lines": c["cost_lines"], "cost_basis": c["cost_basis"], "cost_note": c["cost_note"]}


def view(now: datetime) -> dict:
    """Everything the My rates screen shows: the operator's rows with their status, and the defaults beside them."""
    op = operator()
    for r in op["rate_cards"]:
        r["status"] = validity(r, now)
    return {"mine": op, "defaults": {t: defaults(t) for t in TABLES}, "units": UNITS, "mode_units": MODE_UNITS,
            "cargo_types": CARGO_TYPES, "currency": CURRENCY,
            "carriers": sorted({t["carrier"] for t in defaults("shipment_terms") if t.get("carrier")}),
            "today": now.date().isoformat(),
            "stored": "Kept on this server. Tentative: a Delta table is the durable home.",
            "note": "Your rate is used wherever one applies (your partner, your lane, valid on the day). Everything else "
                    "uses the illustrative defaults. Reported market rates never price a shipment. One currency (EUR); nothing is converted."}
