"""Check the running app's chat answers against the honesty rules, over HTTP (standard library only).

  python evals/check_chat.py [BASE_URL] [--rates DIR]     # default http://127.0.0.1:8000, DIR=demo/fixtures
For every shipment it asks the three supported questions plus two out-of-scope ones, and fails when:
  * a citation is missing a field, or its url is not one of that shipment's evidence urls (invented source)
  * a shipment that has events is explained or planned with no citation at all
  * any money figure appears without the words "estimate" and "illustrative" in the same answer
  * a reschedule cost for "N days" is not N * per_delay_day + rebooking_fee from cost_rates (the contract formula)
  * the text says "confirmed" or "suspected" about a shipment whose events are not that status
  * an out-of-scope question or an empty selection produces a figure or a citation
The comparison is on the data the app serves, so it works for the template fallback and for an LLM-worded agent.
"""
import json, re, sys, urllib.request
from pathlib import Path

CIT = ["claim", "url", "title", "retrieved_at", "published_at"]
MONEY = re.compile(r"(?:EUR|USD|GBP|€|\$)\s?\d[\d,]*(?:\.\d+)?")


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=15) as r:
        return json.load(r)


def ask(base, message, ids):
    req = urllib.request.Request(base + "/api/chat", json.dumps({"message": message, "selected_ids": ids}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def check_answer(label, ans, urls, statuses, fails):
    text, cites = ans.get("text", ""), ans.get("citations", [])
    for c in cites:
        miss = [k for k in CIT if k not in c]
        if miss:
            fails.append(f"{label}: citation missing {miss}")
        elif urls is not None and c["url"] not in urls:
            fails.append(f"{label}: citation url not in the evidence table (invented source?): {c['url']}")
    if MONEY.search(text) and not ("estimate" in text.lower() and "illustrative" in text.lower()):
        fails.append(f"{label}: money figure without 'estimate, illustrative rates'")
    low = text.lower()
    for word in ("confirmed", "suspected"):
        if statuses is not None and re.search(rf"\b{word}\b", low) and word not in statuses:
            fails.append(f"{label}: says '{word}' but the shipment's events are {sorted(statuses) or 'none'}")


def main():
    args = sys.argv[1:]
    rates_dir = Path(args[args.index("--rates") + 1]) if "--rates" in args else Path(__file__).resolve().parents[1] / "demo" / "fixtures"
    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--rates")]
    base = (pos[0] if pos else "http://127.0.0.1:8000").rstrip("/")
    rates = {r["mode"]: r for r in json.loads((rates_dir / "cost_rates.json").read_text())}
    fails, asked = [], 0
    for s in get(base, "/api/shipments"):
        sid = s["shipment_id"]
        d = get(base, f"/api/shipments/{sid}")
        urls = {e["url"] for e in d.get("evidence", [])}
        statuses = {e["status"] for e in d.get("events", [])}
        has_events = bool(d.get("events"))
        for intent, msg in (("explain", "explain why this is at risk"), ("plan", "suggest a plan")):
            ans = ask(base, msg, [sid]); asked += 1
            check_answer(f"{sid}/{intent}", ans, urls, statuses, fails)
            if has_events and not ans.get("citations"):
                fails.append(f"{sid}/{intent}: shipment has events but the answer cites nothing")
        ans = ask(base, "what does it cost to reschedule by 3 days", [sid]); asked += 1
        check_answer(f"{sid}/cost", ans, urls, statuses, fails)
        r = rates.get(d["mode"])
        if r:
            want = 3 * r["per_delay_day"] + r["rebooking_fee"]
            figures = {float(m.group().split()[-1].replace(",", "")) for m in MONEY.finditer(ans.get("text", ""))}
            if want not in figures:
                fails.append(f"{sid}/cost: expected {want:,.0f} (3 x {r['per_delay_day']:g} + {r['rebooking_fee']:g}) in the answer, got {sorted(figures)}")
    first = get(base, "/api/shipments")[0]["shipment_id"]
    for label, msg, ids in (("out-of-scope", "what is the weather in Paris", [first]), ("out-of-scope", "write me a poem", [first]),
                            ("no-selection", "what does it cost to reschedule by 3 days", [])):
        ans = ask(base, msg, ids); asked += 1
        if MONEY.search(ans.get("text", "")) or ans.get("citations"):
            fails.append(f"{label} '{msg}': produced a figure or citation it cannot back")
    for f in fails:
        print("FAIL", f)
    print(f"{'FAIL' if fails else 'ok'}: {asked} questions, {len(fails)} failures")
    sys.exit(bool(fails))


if __name__ == "__main__":
    main()
