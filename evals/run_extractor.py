"""Run an extractor over finetune/heldout_prompts.jsonl and write predictions for extractor_eval.py.

  python evals/run_extractor.py --backend http --url URL --model NAME --out preds_base.jsonl
  python evals/run_extractor.py --backend oracle --out preds_oracle.jsonl     # perfect answers, for testing the pipeline
  python evals/run_extractor.py --backend null   --out preds_null.jsonl       # always "no disruption" floor
  python evals/extractor_eval.py preds_base.jsonl preds_ft.jsonl

`http` talks to any OpenAI-compatible chat-completions endpoint (Databricks model serving, vLLM, Ollama...).
URL is the full chat-completions URL; the bearer token is read from --token-env (default EXTRACTOR_TOKEN).
Run it once with the base model and once with the fine-tune, using the same prompts, then compare.
Output: one JSON object (or null) per line, same order as the held-out file. Prediction text that is not
valid JSON counts as null and is reported, so a model that rambles is penalised rather than skipped.
"""
import argparse, json, os, re, sys, time, urllib.request
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "finetune" / "heldout_prompts.jsonl"


def load_rows():
    return [json.loads(l) for l in PROMPTS.read_text().splitlines() if l.strip()]


def parse(text):
    """Return (event_or_None, ok). ok=False when the reply was not parseable JSON or the word null."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t).strip()
    if t.lower() == "null":
        return None, True
    m = re.search(r"\{.*\}", t, re.S)
    for cand in (t, m.group(0) if m else None):
        if cand:
            try:
                obj = json.loads(cand)
                return (obj, True) if isinstance(obj, dict) else (None, False)
            except ValueError:
                pass
    return None, False


def call_http(url, model, token, prompt, retries=3):
    body = json.dumps({"model": model, "temperature": 0, "max_tokens": 400,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=60) as r:
                return json.load(r)["choices"][0]["message"]["content"]
        except Exception as e:
            if i == retries - 1:
                raise RuntimeError(f"endpoint failed after {retries} tries: {e}")
            time.sleep(2 ** i)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["http", "oracle", "null"], required=True)
    ap.add_argument("--url"); ap.add_argument("--model", default="")
    ap.add_argument("--token-env", default="EXTRACTOR_TOKEN")
    ap.add_argument("--limit", type=int); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.backend == "http" and not a.url:
        sys.exit("--url is required for the http backend")
    rows = load_rows()[: a.limit]
    token = os.environ.get(a.token_env)
    preds, bad = [], 0
    for i, r in enumerate(rows, 1):
        if a.backend == "oracle":
            text = r["completion"]
        elif a.backend == "null":
            text = "null"
        else:
            text = call_http(a.url, a.model, token, r["prompt"])
        event, ok = parse(text)
        bad += not ok
        preds.append(event)
        if a.backend == "http" and i % 10 == 0:
            print(f"{i}/{len(rows)}", file=sys.stderr)
    Path(a.out).write_text("".join(json.dumps(p) + "\n" for p in preds))
    print(f"wrote {len(preds)} predictions to {a.out}; unparseable replies: {bad}")
    if a.limit:
        print("note: --limit set; the scorer needs predictions for every held-out row", file=sys.stderr)


if __name__ == "__main__":
    main()
