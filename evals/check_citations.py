"""Citation, freshness and confirmation checks over `evidence` + `disruption_events` rows.

  python evals/check_citations.py [DIR] [--online] [--max-age-h 72]
DIR holds evidence.json and disruption_events.json (default: demo/fixtures).
Checks:
  1. every evidence row has claim, url, title, retrieved_at, published_at
  2. url is well-formed http(s); non-fixture rows must not use placeholder hosts
  3. --online: non-fixture urls resolve (HEAD, then GET)
  4. freshness: retrieved_at parses and is not in the future; flags rows older than --max-age-h
  5. status=confirmed needs 2 distinct `domain` values or 1 evidence row with is_official=true
   (CONTRACTS.md section 1)
Fixture events (is_fixture=true) are exempt from 3 and 5's strictness but still reported.
Exit code 1 if any hard failure.
"""
import json, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = ["claim", "url", "title", "retrieved_at", "published_at"]
PLACEHOLDER = ("example.com", "example.invalid", ".invalid", "localhost")

def domain(u): return (urlparse(u).hostname or "").lower().removeprefix("www.")
def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))

def resolves(url):
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": "portshift-eval"})
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status < 400: return True
        except Exception:
            pass
    return False

def run(d, online, max_age_h):
    ev = json.loads((d / "evidence.json").read_text())
    events = {e["event_id"]: e for e in json.loads((d / "disruption_events.json").read_text())}
    now = datetime.now(timezone.utc)
    fails, warns = [], []
    by_event = {}
    for r in ev:
        rid = r.get("evidence_id", "?")
        fixture = events.get(r.get("event_id"), {}).get("is_fixture", False)
        miss = [k for k in REQUIRED if not r.get(k)]
        if miss: fails.append(f"{rid}: missing {miss}"); continue
        u = urlparse(r["url"])
        if u.scheme not in ("http", "https") or not u.hostname:
            fails.append(f"{rid}: bad url {r['url']}"); continue
        if not fixture and any(p in domain(r["url"]) for p in PLACEHOLDER):
            fails.append(f"{rid}: placeholder url on a non-fixture event")
        if online and not fixture and not resolves(r["url"]):
            fails.append(f"{rid}: url does not resolve {r['url']}")
        try:
            age = (now - ts(r["retrieved_at"])).total_seconds() / 3600
            if age < -0.1: fails.append(f"{rid}: retrieved_at in the future")
            elif age > max_age_h: warns.append(f"{rid}: stale ({age:.0f} h old)")
        except ValueError:
            fails.append(f"{rid}: unparseable retrieved_at")
        by_event.setdefault(r["event_id"], {"d": set(), "off": False})
        by_event[r["event_id"]]["d"].add(r.get("domain") or domain(r["url"]))
        by_event[r["event_id"]]["off"] |= bool(r.get("is_official"))
    for eid, e in events.items():
        info = by_event.get(eid, {"d": set(), "off": False}); doms = info["d"]
        if not doms:
            fails.append(f"{eid}: event has no evidence (no citation, no display)")
        elif e["status"] == "confirmed" and len(doms) < 2 and not info["off"]:
            (warns if e.get("is_fixture") else fails).append(f"{eid}: confirmed on {len(doms)} domain(s), none flagged is_official")
    return fails, warns

if __name__ == "__main__":
    a = sys.argv[1:]
    online = "--online" in a
    age = float(a[a.index("--max-age-h") + 1]) if "--max-age-h" in a else 72
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] != "--max-age-h")]
    d = Path(pos[0]) if pos else Path(__file__).resolve().parents[1] / "demo" / "fixtures"
    fails, warns = run(d, online, age)
    for w in warns: print("WARN", w)
    for f in fails: print("FAIL", f)
    print(f"{'FAIL' if fails else 'ok'}: {len(fails)} failures, {len(warns)} warnings")
    sys.exit(bool(fails))
