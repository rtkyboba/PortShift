"""Score an extractor against finetune/heldout.jsonl.

Predictions: a JSONL file with one event JSON (or null) per line, in the same order as the
held-out file (so base and fine-tune can be run elsewhere and compared here).
  python evals/extractor_eval.py preds_base.jsonl preds_ft.jsonl
  python evals/extractor_eval.py --selftest      # checks the scorer itself
Metrics: detection F1 (event vs null), and exact-match accuracy per field on correctly detected
events: type, location name, window start, window end.
"""
import json, sys
from pathlib import Path

HELD = Path(__file__).resolve().parents[1] / "finetune" / "heldout.jsonl"
FIELDS = ["type", "location", "window_start", "window_end"]

def load(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]

def field(e, f):
    if f == "location": return (e.get("location") or {}).get("name")
    if f.startswith("window_"): return (e.get("window") or {}).get(f[7:])
    return e.get(f)

def score(gold, pred):
    assert len(gold) == len(pred), f"{len(pred)} predictions for {len(gold)} rows"
    tp = fp = fn = 0
    hits = {f: 0 for f in FIELDS}
    for g, p in zip(gold, pred):
        gd, pd = g is not None, p is not None
        tp += gd and pd; fp += (not gd) and pd; fn += gd and not pd
        if gd and pd:
            for f in FIELDS:
                hits[f] += field(g, f) == field(p, f)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    n = max(tp, 1)
    return {"detect_f1": round(f1, 3), "precision": round(prec, 3), "recall": round(rec, 3),
            **{f"{f}_acc": round(hits[f] / n, 3) for f in FIELDS}}

def main(argv):
    gold = [r["output"] for r in load(HELD)]
    if argv == ["--selftest"]:
        assert score(gold, gold)["detect_f1"] == 1.0
        none = [None] * len(gold)
        assert score(gold, none)["detect_f1"] == 0.0
        print("selftest ok"); return
    for path in argv:
        print(path, score(gold, load(path)))

if __name__ == "__main__":
    main(sys.argv[1:])
