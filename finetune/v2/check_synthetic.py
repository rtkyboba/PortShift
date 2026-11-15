"""Run the base extractor (strict prompt) on synthetic rows and report agreement with their labels, by kind.

    python finetune/v2/check_synthetic.py heldout_v2.jsonl --n 120
"""
import argparse, json, pathlib, sys, random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent import extract  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--n", type=int, default=120)
ap.add_argument("--endpoint"); ap.add_argument("--workers", type=int, default=2)
a = ap.parse_args()
rows = [json.loads(l) for l in (pathlib.Path(__file__).parent / a.file).read_text().splitlines()]
random.Random(1).shuffle(rows); rows = rows[: a.n]
def run(r):
    it, today = r["meta"]["item"], r["meta"]["today"]
    return extract.extract_via_endpoint(it, today, a.endpoint) if a.endpoint else extract.extract_raw(it, today)
with ThreadPoolExecutor(a.workers) as p:
    preds = list(p.map(run, rows))
by = defaultdict(lambda: [0, 0]); det = typ = n_ev = 0; bad = []
for r, p in zip(rows, preds):
    lab = r["meta"]["label"]; ok = (lab is None) == (p is None)
    by[r["meta"]["kind"]][0] += ok; by[r["meta"]["kind"]][1] += 1; det += ok
    if lab and p:
        n_ev += 1; typ += p["type"] == lab["type"]
        if p["type"] != lab["type"]: bad.append(f"TYPE {r['meta']['kind']}: want {lab['type']} got {p['type']} | {r['meta']['clean'][:110]}")
    elif not ok:
        bad.append(f"DET  {r['meta']['kind']}: want {'event' if lab else 'null'} | {r['meta']['clean'][:110]}")
print(f"detection agreement {det}/{len(rows)}, type {typ}/{n_ev}")
for k, (o, n) in sorted(by.items()): print(f"  {k:22s} {o}/{n}")
for b in bad: print(" ", b)
