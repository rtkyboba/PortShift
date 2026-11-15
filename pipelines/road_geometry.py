"""Replace hand-placed truck leg geometry in demo/fixtures/legs.json with real road routes.

    python pipelines/road_geometry.py            # fetch from OSRM, simplify, rewrite legs.json
    python pipelines/road_geometry.py --dry-run  # print what would change

Truck legs were 2-3 hand-placed points, so some crossed water (S-1005 Felixstowe to Dover cut across the Thames
estuary). This asks the public OSRM demo router (router.project-osrm.org, driving profile) once per truck leg,
sending only the two endpoint coordinates (public ports and cities), simplifies the line to about 1 km, and stores
it as [lat, lon] points. Run it again only when truck legs change; the app and the risk job just read geometry.
A leg OSRM cannot route (e.g. no road) keeps its old geometry. One request per second (OSRM usage policy).
"""
import argparse, json, math, pathlib, time, urllib.request

LEGS = pathlib.Path(__file__).resolve().parents[1] / "demo" / "fixtures" / "legs.json"
OSRM = "https://router.project-osrm.org/route/v1/driving/{a};{b}?overview=full&geometries=geojson"


def simplify(pts, tol):
    """Douglas-Peucker on [lat, lon] points, tolerance in degrees."""
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    def dist(p):
        dx, dy = b[1] - a[1], b[0] - a[0]
        if dx == dy == 0:
            return math.hypot(p[1] - a[1], p[0] - a[0])
        t = max(0, min(1, ((p[1] - a[1]) * dx + (p[0] - a[0]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(p[1] - (a[1] + t * dx), p[0] - (a[0] + t * dy))
    i, d = max(((i, dist(p)) for i, p in enumerate(pts[1:-1], 1)), key=lambda x: x[1])
    if d <= tol:
        return [a, b]
    return simplify(pts[: i + 1], tol)[:-1] + simplify(pts[i:], tol)


def road(leg):
    url = OSRM.format(a=f"{leg['from_lon']},{leg['from_lat']}", b=f"{leg['to_lon']},{leg['to_lat']}")
    req = urllib.request.Request(url, headers={"User-Agent": "portshift-demo-seed/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    if data.get("code") != "Ok" or not data.get("routes"):
        return None, None
    route = data["routes"][0]
    pts = [[round(lat, 4), round(lon, 4)] for lon, lat in route["geometry"]["coordinates"]]
    tol = 0.01 if route["distance"] < 600_000 else 0.03  # ~1 km, coarser for very long legs
    pts = simplify(pts, tol)
    pts[0], pts[-1] = [leg["from_lat"], leg["from_lon"]], [leg["to_lat"], leg["to_lon"]]  # end exactly at the stops
    return pts, route["distance"] / 1000


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    legs = json.loads(LEGS.read_text())
    for leg in legs:
        if leg["mode"] != "truck":
            continue
        pts, km = road(leg)
        time.sleep(1)
        if not pts:
            print(f"{leg['shipment_id']} {leg['seq']} {leg['from_name']} -> {leg['to_name']}: no road route, kept")
            continue
        print(f"{leg['shipment_id']} {leg['seq']} {leg['from_name']} -> {leg['to_name']}: {len(leg.get('geometry') or [])} -> {len(pts)} points, {km:.0f} km by road")
        leg["geometry"] = pts
    if not a.dry_run:
        LEGS.write_text(json.dumps(legs, indent=2) + "\n")


if __name__ == "__main__":
    main()
