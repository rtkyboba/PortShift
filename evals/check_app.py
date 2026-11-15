"""Check what the RUNNING app actually shows against the honesty and citation rules.

  python evals/check_app.py [BASE_URL]        # default http://127.0.0.1:8000
Needs only the standard library. Fails (exit 1) when, for any shipment the app serves:
  - risk level > 1 but no event, or an event_id in the risk row that the app cannot show
  - an event with no evidence rows (no citation, no display)
  - an evidence row missing claim/url/title/retrieved_at/published_at, or with a bad url
  - a fixture event (is_fixture) whose url is not on a reserved .invalid host, or a live event on one
  - risk level 1 that still lists events
  - the page lacks the "demo fleet" label, "sample" badge text or "estimate, illustrative rates" label
  - /api/chat returns text that cites nothing for a shipment that has events
"""
import json, re, sys, urllib.request
from urllib.parse import urlparse

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
CIT = ["claim", "url", "title", "retrieved_at", "published_at"]


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.read().decode()


def post(path, obj):
    req = urllib.request.Request(BASE + path, json.dumps(obj).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    fails, notes = [], []
    shipments = json.loads(get("/api/shipments"))
    if not shipments:
        sys.exit("FAIL: /api/shipments returned no shipments")
    for s in shipments:
        sid, level = s["shipment_id"], s["risk"]["level"]
        d = json.loads(get(f"/api/shipments/{sid}"))
        events = {e["event_id"]: e for e in d.get("events", [])}
        ev_by = {}
        for ev in d.get("evidence", []):
            ev_by.setdefault(ev["event_id"], []).append(ev)
        if level == 1 and s["risk"]["event_ids"]:
            fails.append(f"{sid}: level 1 but lists events {s['risk']['event_ids']}")
        if level > 1 and not s["risk"]["event_ids"]:
            fails.append(f"{sid}: level {level} with no event_ids")
        for eid in s["risk"]["event_ids"]:
            if eid not in events:
                fails.append(f"{sid}: risk cites {eid} but the app cannot show it"); continue
            rows = ev_by.get(eid, [])
            if not rows:
                fails.append(f"{sid}/{eid}: event has no evidence (no citation, no display)")
            fixture = events[eid].get("is_fixture", False)
            for r in rows:
                miss = [k for k in CIT if k not in r or r[k] in ("", None) and k != "published_at"]
                if miss:
                    fails.append(f"{sid}/{r.get('evidence_id', '?')}: missing {miss}"); continue
                u = urlparse(r["url"])
                if u.scheme not in ("http", "https") or not u.hostname:
                    fails.append(f"{sid}/{r['evidence_id']}: bad url {r['url']}")
                elif fixture and not u.hostname.endswith(".invalid"):
                    fails.append(f"{sid}/{r['evidence_id']}: fixture event with a non-.invalid url (looks like an invented source)")
                elif not fixture and u.hostname.endswith(".invalid"):
                    fails.append(f"{sid}/{r['evidence_id']}: live event with a placeholder url")
                if fixture and not str(r["claim"]).startswith("SAMPLE:"):
                    notes.append(f"{r['evidence_id']}: fixture claim does not start with SAMPLE:")
    html = get("/")
    own = [p if p.startswith("/") else "/" + p for p in re.findall(r'src="([^"]+\.js)"', html)
           if not p.startswith(("http:", "https:", "//"))]
    page = html + "".join(get(p) for p in own)
    for label in ("demo fleet", "sample", "estimate, illustrative rates"):
        if label.lower() not in page.lower():
            fails.append(f'UI never shows the label "{label}"')
    hit = next((s for s in shipments if s["risk"]["event_ids"]), None)
    if hit:
        ans = post("/api/chat", {"message": "explain this shipment", "selected_ids": [hit["shipment_id"]]})
        if not ans.get("citations"):
            fails.append(f"chat about {hit['shipment_id']} (has events) returned no citations")
        for c in ans.get("citations", []):
            miss = [k for k in CIT if k not in c]
            if miss: fails.append(f"chat citation missing {miss}")
    for n in notes: print("NOTE", n)
    for f in fails: print("FAIL", f)
    print(f"{'FAIL' if fails else 'ok'}: {len(shipments)} shipments checked, {len(fails)} failures, {len(notes)} notes")
    sys.exit(bool(fails))


if __name__ == "__main__":
    main()
