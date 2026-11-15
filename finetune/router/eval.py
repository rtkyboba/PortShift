"""Score a request reader on finetune/router/heldout.jsonl.

  python finetune/router/eval.py --reader patterns
  python finetune/router/eval.py --url http://127.0.0.1:8092/v1/chat/completions            # a model's raw replies
  python finetune/router/eval.py --url http://127.0.0.1:8092/v1/chat/completions --as-used  # as the app uses it:
                                                                 # checked against the message, patterns as fallback
Metrics: intent accuracy; whole request exactly right; and each field on the rows where it matters (goal and
budget on plan_fleet, corridor on live_check, ids on shipment_question, stops, cargo and timing on plan_new_shipments,
the whole reply on shipment_details,
and precision and recall of out_of_scope). Stops are compared ignoring case and a leading "the" or "our".
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
os.environ.setdefault("PORTSHIFT_DEMO_CLOCK", "0")
sys.path.insert(0, str(HERE.parents[1] / "app"))
import router  # noqa: E402


def norm_stop(s):
    return re.sub(r"^(the|our|my)\s+", "", str(s).strip().lower())


def norm(req):
    if not isinstance(req, dict):
        return None
    def cargo_of(c):
        try:
            return (float(c["units"]), c["unit_type"]) if c else None
        except (KeyError, TypeError, ValueError):
            return "bad"

    def when_of(w):
        try:
            return (w["kind"], re.sub(r"\s+", " ", str(w["text"]).strip().lower())) if w else None
        except (KeyError, TypeError):
            return "bad"
    ships = [([norm_stop(x) for x in (s or {}).get("stops") or []], cargo_of((s or {}).get("cargo")), when_of((s or {}).get("when")))
             for s in req.get("shipments") or []]
    details = [((d or {}).get("ref"), cargo_of((d or {}).get("cargo")), when_of((d or {}).get("when"))) for d in req.get("details") or []]
    budget = req.get("budget_eur")
    try:
        budget = float(budget) if budget is not None else None
    except (TypeError, ValueError):
        budget = "bad"
    return {"intent": req.get("intent"), "goal": req.get("goal"), "budget_eur": budget, "corridor": req.get("corridor"),
            "shipment_ids": sorted(str(i).upper() for i in req.get("shipment_ids") or []), "shipments": ships, "details": details}


def score(rows, preds):
    n = len(rows)
    out = {"rows": n, "intent": 0, "exact": 0}
    field = {"goal": [0, 0], "budget": [0, 0], "corridor": [0, 0], "ids": [0, 0], "stops": [0, 0], "cargo": [0, 0], "when": [0, 0], "details": [0, 0]}
    tp = fp = fn = unusable = 0
    for row, pred in zip(rows, preds):
        g, p = norm(row["request"]), norm(pred)
        if p is None:
            unusable += 1
            p = {"intent": None, "goal": None, "budget_eur": None, "corridor": None, "shipment_ids": [], "shipments": [], "details": []}
        out["intent"] += g["intent"] == p["intent"]
        out["exact"] += g == p
        tp += g["intent"] == "out_of_scope" and p["intent"] == "out_of_scope"
        fp += g["intent"] != "out_of_scope" and p["intent"] == "out_of_scope"
        fn += g["intent"] == "out_of_scope" and p["intent"] != "out_of_scope"
        checks = {"plan_fleet": [("goal", g["goal"] == p["goal"]), ("budget", g["budget_eur"] == p["budget_eur"])],
                  "live_check": [("corridor", g["corridor"] == p["corridor"])],
                  "shipment_question": [("ids", g["shipment_ids"] == p["shipment_ids"])],
                  "shipment_details": [("details", g["details"] == p["details"])],
                  "plan_new_shipments": [("stops", [x[0] for x in g["shipments"]] == [x[0] for x in p["shipments"]]),
                                         ("cargo", [x[1] for x in g["shipments"]] == [x[1] for x in p["shipments"]]),
                                         ("when", [x[2] for x in g["shipments"]] == [x[2] for x in p["shipments"]])]}
        for name, ok in checks.get(g["intent"], []):
            field[name][0] += bool(ok)
            field[name][1] += 1
    out["intent"], out["exact"] = round(out["intent"] / n, 3), round(out["exact"] / n, 3)
    out.update({k: round(a / b, 3) if b else None for k, (a, b) in field.items()})
    out["out_of_scope_precision"] = round(tp / (tp + fp), 3) if tp + fp else None
    out["out_of_scope_recall"] = round(tp / (tp + fn), 3) if tp + fn else None
    out["unusable_replies"] = unusable
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reader", choices=["patterns"])
    ap.add_argument("--url")
    ap.add_argument("--as-used", action="store_true")
    ap.add_argument("--out", help="write the predictions here (JSONL)")
    a = ap.parse_args()
    rows = [json.loads(l) for l in (HERE / "heldout.jsonl").read_text().splitlines() if l.strip()]
    if a.url and a.as_used:
        os.environ["ROUTER_ENDPOINT"] = a.url
        results = [router.read(r["message"]) for r in rows]
        preds = [x["request"] for x in results]
        print("read by the model:", sum(x["source"] == "model" for x in results), "of", len(rows), "(the rest fell back to patterns)")
    elif a.url:
        preds = [router.ask_model(r["message"], a.url, timeout=60) for r in rows]
    else:
        preds = [router.by_patterns(r["message"]) for r in rows]
    if a.out:
        Path(a.out).write_text("".join(json.dumps(p) + "\n" for p in preds))
    print(json.dumps(score(rows, preds), indent=1))
