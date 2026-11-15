"""Customer sites: where the operator delivers to (customer warehouses, distribution centres, stores).

A few sample sites stand in until the operator adds their own. Added sites are kept in a file on this server, like
the operator's own rates (`costing.py`); a Delta table is the durable home. They are places of kind `customer`,
so the planner routes to them like any other stop (by truck: they are not ports or airports).
"""
import json
import os

import costing
import planner

SAMPLES = [
    {"name": "Northgate Retail DC (Doncaster)", "customer": "Northgate Retail", "lat": 53.52, "lon": -1.08},
    {"name": "Harbour Foods depot (Avonmouth)", "customer": "Harbour Foods", "lat": 51.52, "lon": -2.67},
    {"name": "Kestrel Home DC (Milton Keynes)", "customer": "Kestrel Home", "lat": 52.04, "lon": -0.76},
    {"name": "Lumen Pharma hub (Antwerp)", "customer": "Lumen Pharma", "lat": 51.22, "lon": 4.45},
]


def _file() -> str:
    return os.path.join(costing._state_dir(), "customer_sites.json")


def _saved() -> list[dict]:
    try:
        with open(_file()) as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("name")]


def _write(rows: list[dict]) -> None:
    os.makedirs(costing._state_dir(), exist_ok=True)
    with open(_file(), "w") as f:
        json.dump(rows, f, indent=2)


def sites() -> list[dict]:
    """Every customer site, samples first, each a place of kind `customer`."""
    samples = [{**s, "kind": "customer", "is_sample": True, "note": ""} for s in SAMPLES]
    own = [{**r, "kind": "customer", "is_sample": False} for r in _saved()]
    return samples + own


def add(name: str, lat, lon, customer: str = "", note: str = "") -> dict:
    """Add a customer site. Raises ValueError on a bad or duplicate entry."""
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("Give the site a name.")
    try:
        lat, lon = round(float(lat), 4), round(float(lon), 4)
    except (TypeError, ValueError):
        raise ValueError("The site needs a latitude and longitude.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("That latitude or longitude is out of range.")
    taken = {p["name"].lower() for p in planner.PLACES} | {s["name"].lower() for s in sites()}
    if name.lower() in taken:
        raise ValueError(f"There is already a place called {name}.")
    row = {"name": name, "customer": (customer or "").strip()[:80], "note": (note or "").strip()[:160], "lat": lat, "lon": lon}
    _write(_saved() + [row])
    return {**row, "kind": "customer", "is_sample": False}


def remove(name: str) -> bool:
    """Remove a site the operator added. Samples cannot be removed. Returns whether anything was removed."""
    rows = _saved()
    keep = [r for r in rows if r["name"] != name]
    if len(keep) == len(rows):
        return False
    _write(keep)
    return True
