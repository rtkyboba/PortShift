"""Run an extractor over the real snippets and write predictions for score.py.

    python finetune/real/predict.py out.jsonl                       # agent.extract with LLM_* from the env
    python finetune/real/predict.py out.jsonl --endpoint http://127.0.0.1:8091/v1/chat/completions --model ft

The date filter (drop events that already ended) is NOT applied: labels count past events as events.
"""
import argparse, json, pathlib, sys
from concurrent.futures import ThreadPoolExecutor
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent import extract  # noqa: E402

TODAY = "2026-11-15"

def run_one(item, a):
    raw = getattr(extract, "extract_raw", None)
    if a.endpoint:
        return extract.extract_via_endpoint(item, TODAY, a.endpoint, a.model)
    return raw(item, today=TODAY) if raw else extract.extract(item, today=TODAY)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("--endpoint"); ap.add_argument("--model", default="ft")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--set", choices=["dev", "test"], default="dev", help="dev = raw_snippets.jsonl, test = test_raw.jsonl")
    a = ap.parse_args()
    items = [json.loads(l) for l in (ROOT / "finetune/real" / ("test_raw.jsonl" if a.set == "test" else "raw_snippets.jsonl")).read_text().splitlines()]
    with ThreadPoolExecutor(a.workers) as pool:
        preds = list(pool.map(lambda it: run_one(it, a), items))
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps({"url": it["url"], "pred": p}) + "\n" for it, p in zip(items, preds)))
    print(f"{sum(p is not None for p in preds)} events from {len(items)} snippets -> {out}")

if __name__ == "__main__":
    main()
