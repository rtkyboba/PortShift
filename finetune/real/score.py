"""Score extractor predictions against the hand labels of real Linkup snippets (labels.jsonl).

    python finetune/real/score.py preds.jsonl [more_preds.jsonl ...]          # dev set (labels.jsonl)
    python finetune/real/score.py --test preds.jsonl ...                     # test set (test_labels.jsonl)

A predictions file has one line per snippet: {"url": ..., "pred": null | {"type", "location_name", "window_start", ...}}.
Ambiguous rows are left out of the headline numbers. Field scores are over true events the model also detected:
type must be one of the accepted types; location matches when an accepted keyword appears in the predicted name;
window start matches within one day (rows with no labelled start are not scored on it).
"""
import json
import pathlib
import sys
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent


def load_labels(path=HERE / "labels.jsonl"):
    return {r["url"]: r for r in map(json.loads, path.read_text().splitlines())}


def _day(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def score(labels: dict, preds: dict, include_ambiguous=False) -> dict:
    tp = fp = fn = tn = 0
    typ = loc = win = n_field = n_win = 0
    errors = []
    for url, lab in labels.items():
        if lab["ambiguous"] and not include_ambiguous:
            continue
        p = preds.get(url)
        if lab["event"] and p:
            tp += 1
            n_field += 1
            typ += p.get("type") in lab["types"]
            name = (p.get("location_name") or "").lower()
            ok_loc = any(k in name for k in lab["locations"])
            loc += ok_loc
            if lab["window_start"]:
                n_win += 1
                a, b = _day(p.get("window_start")), _day(lab["window_start"])
                win += bool(a and b and abs((a - b).days) <= 1)
            if p.get("type") not in lab["types"] or not ok_loc:
                errors.append(f"FIELD {lab['note']}: got {p.get('type')} @ {p.get('location_name')}")
        elif lab["event"]:
            fn += 1
            errors.append(f"MISS  {lab['note']}")
        elif p:
            fp += 1
            errors.append(f"FALSE {lab['note']}: got {p.get('type')} @ {p.get('location_name')}")
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"n": tp + fp + fn + tn, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "accuracy": round((tp + tn) / max(1, tp + fp + fn + tn), 3), "precision": round(prec, 3),
            "recall": round(rec, 3), "f1": round(f1, 3), "type": round(typ / max(1, n_field), 3),
            "location": round(loc / max(1, n_field), 3), "window_start": round(win / max(1, n_win), 3),
            "errors": errors}


def load_preds(path) -> dict:
    return {r["url"]: r["pred"] for r in map(json.loads, pathlib.Path(path).read_text().splitlines())}


if __name__ == "__main__":
    args = sys.argv[1:]
    test = "--test" in args
    labels = load_labels(HERE / ("test_labels.jsonl" if test else "labels.jsonl"))
    for path in [a for a in args if a != "--test"]:
        s = score(labels, load_preds(path))
        print(f"\n== {path}")
        print({k: v for k, v in s.items() if k != "errors"})
        for e in s["errors"]:
            print("  ", e)
