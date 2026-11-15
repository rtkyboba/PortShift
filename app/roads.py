"""Road routes for truck legs the planner suggests: the line on the map and the distance driven.

route(a, b) asks the public OSRM demo router (router.project-osrm.org, driving profile, OpenStreetMap data) for the
road between two places and returns (geometry, km), or None. Only the two end coordinates are sent. Results are
kept: a seed file shipped with the app (road_cache.json, the routes between the built-in places used most), and a
file in the state folder for anything looked up since. A failed or slow lookup is remembered for the session and
the planner falls back to the straight line times its road factor, and says so.

Off under pytest and with PORTSHIFT_ROADS=0, so tests and offline runs are deterministic.
"""
import json
import math
import os
import pathlib
import sys
import threading
import time
import urllib.request

OSRM = "https://router.project-osrm.org/route/v1/driving/{a};{b}?overview=full&geometries=geojson"
SEED = pathlib.Path(__file__).resolve().parent / "road_cache.json"
_lock = threading.Lock()
_cache: dict | None = None
_failed: set[str] = set()
_last_call = 0.0


def enabled() -> bool:
    return os.environ.get("PORTSHIFT_ROADS", "0" if "pytest" in sys.modules else "1") == "1"


def _state_file() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PORTSHIFT_STATE") or pathlib.Path(__file__).resolve().parent.parent / ".portshift_live") / "road_cache.json"


def _key(a, b) -> str:
    return f"{a[0]:.3f},{a[1]:.3f}>{b[0]:.3f},{b[1]:.3f}"


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = {}
        for path in (SEED, _state_file()):
            try:
                _cache.update(json.loads(path.read_text()))
            except (OSError, ValueError):
                pass
    return _cache


def simplify(pts: list, tol: float) -> list:
    """Douglas-Peucker on [lat, lon] points, tolerance in degrees (iterative, so long routes do not recurse deeply)."""
    if len(pts) < 3:
        return pts
    keep, stack = {0, len(pts) - 1}, [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        a, b = pts[i], pts[j]
        dx, dy = b[1] - a[1], b[0] - a[0]
        best, far = 0.0, None
        for k in range(i + 1, j):
            p = pts[k]
            if dx == dy == 0:
                d = math.hypot(p[1] - a[1], p[0] - a[0])
            else:
                t = max(0, min(1, ((p[1] - a[1]) * dx + (p[0] - a[0]) * dy) / (dx * dx + dy * dy)))
                d = math.hypot(p[1] - (a[1] + t * dx), p[0] - (a[0] + t * dy))
            if d > best:
                best, far = d, k
        if far is not None and best > tol:
            keep.add(far)
            stack += [(i, far), (far, j)]
    return [pts[k] for k in sorted(keep)]


def fetch(a, b, timeout: float = 5.0):
    """One OSRM request: (geometry, km) or None."""
    global _last_call
    wait = 1.0 - (time.time() - _last_call)  # the demo router asks for at most one request a second
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()
    url = OSRM.format(a=f"{a[1]},{a[0]}", b=f"{b[1]},{b[0]}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "portshift-demo/1.0"}), timeout=timeout) as r:
        data = json.loads(r.read())
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    best = data["routes"][0]
    pts = [[round(lat, 4), round(lon, 4)] for lon, lat in best["geometry"]["coordinates"]]
    pts = simplify(pts, 0.01 if best["distance"] < 600_000 else 0.03)
    pts[0], pts[-1] = [a[0], a[1]], [b[0], b[1]]
    return pts, round(best["distance"] / 1000, 1)


def route(a, b):
    """(geometry, km) by road between two [lat, lon] points, or None (not enabled, no road, or the lookup failed)."""
    if not enabled():
        return None
    key = _key(a, b)
    with _lock:
        cache = _load()
        if key in cache:
            hit = cache[key]
            return (hit["geometry"], hit["km"]) if hit else None
        back = cache.get(_key(b, a))  # the same road the other way is close enough for a sketch planner
        if back:
            return list(reversed(back["geometry"])), back["km"]
        if key in _failed:
            return None
        try:
            got = fetch(a, b)
        except Exception:
            _failed.add(key)
            return None
        cache[key] = {"geometry": got[0], "km": got[1]} if got else None
        try:
            path = _state_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            seed = json.loads(SEED.read_text()) if SEED.exists() else {}
            path.write_text(json.dumps({k: v for k, v in cache.items() if k not in seed}))
        except (OSError, ValueError):
            pass
        return got
