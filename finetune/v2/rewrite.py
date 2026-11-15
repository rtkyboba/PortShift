"""Diversify v2 training rows: Llama (LLM_ENDPOINT) rewrites a row's text in a new style, keeping its facts.

    python finetune/v2/rewrite.py --share 0.6 --workers 3     # train_v2.jsonl -> train_v2b.jsonl + adaption_train_v2b.jsonl

A rewrite is kept only if (1) every protected string (place names and date phrases from the original) is still
present, and (2) the strict base extractor still agrees with the row's label on event vs null. Otherwise the row
keeps its original text, so labels never drift. Rewrites are cached in rewrite_cache.jsonl, so a rerun is cheap.
"""
import argparse, json, pathlib, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from agent import extract, llm  # noqa: E402
import make_dataset_v2 as gen  # noqa: E402

STYLES = ["a short wire-service news item", "a trade-press article lead (shipping/logistics magazine)",
          "a carrier customer advisory", "a local newspaper report", "a press release from the operator or authority",
          "a blog post by a logistics consultant", "a news aggregator summary", "a social media post by a freight forwarder"]
MONTH_RE = "|".join(gen.MONTHS + gen.MONTHS_DE + gen.MONTHS_FR + gen.MONTHS_NL + gen.MONTHS_ES)
DATE_RE = re.compile(rf"((?:{'|'.join(gen.WEEKDAYS)}), )?\d{{1,2}}\.? (?:de )?(?:{MONTH_RE})|(?:{MONTH_RE}) \d{{1,2}}")
PLACE_NAMES = sorted({n for pool in (gen.PORTS, gen.WATERWAYS, gen.AIRPORTS, gen.ROADS, gen.RAIL, gen.BORDERS)
                      for p in pool for n in (p[0], p[1], p[2]) if n} | {r[0] for r in gen.NEAR_PORT_ROADS}
                     | {r[1] for r in gen.NEAR_PORT_ROADS}, key=len, reverse=True)

SYSTEM = ("You rewrite short news texts for a dataset. Keep every fact exactly: same places, dates, numbers, who did "
          "what, and whether something is happening, planned, threatened, over, or only speculated. Do not add any new "
          "disruption, date or place. Keep the language of the original. Reply with only the rewritten text.")


def protected(text: str) -> list[str]:
    found, rest = [], text
    for name in PLACE_NAMES:  # longest first, so "Port of Hamburg" wins over "Hamburg"
        if name in rest:
            found.append(name); rest = rest.replace(name, " ")
    return found + [m.group(0) for m in DATE_RE.finditer(text)]


def rewrite_one(row, rng):
    clean = row["meta"]["clean"]; keep = protected(clean)
    style = rng.choice(STYLES)
    user = (f"Rewrite this as {style}, 2 to 4 sentences, and add one sentence of neutral background that adds no new "
            f"events or dates. These strings must appear exactly as written: {json.dumps(keep, ensure_ascii=False)}.\n\n"
            f"Text: {clean}")
    text = None
    for a in range(4):
        text = llm.complete(SYSTEM, user, max_tokens=300, timeout=60)
        if text is not None:
            break
        time.sleep(2 ** a)
    if not text or any(k not in text for k in keep):
        return None, "protected string lost"
    it = {**row["meta"]["item"], "snippet": gen.noisy(text.strip())}
    pred = extract.extract_raw(it, row["meta"]["today"])
    if (pred is None) != (row["meta"]["label"] is None):
        return None, "extractor disagrees with label"
    return {"text": text.strip(), "item": it, "style": style}, "ok"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--share", type=float, default=0.6)
    ap.add_argument("--workers", type=int, default=3); ap.add_argument("--limit", type=int)
    ap.add_argument("--in", dest="src", default="train_v2.jsonl"); ap.add_argument("--out", default="train_v2b.jsonl")
    a = ap.parse_args()
    rows = [json.loads(l) for l in (HERE / a.src).read_text().splitlines()]
    cache_path = HERE / "rewrite_cache.jsonl"
    cache = {json.loads(l)["key"]: json.loads(l) for l in cache_path.read_text().splitlines()} if cache_path.exists() else {}
    rng = random.Random(7)  # same seed: the chosen share is reproducible per input file
    chosen = [i for i in range(len(rows)) if rng.random() < a.share][: a.limit]
    todo = [i for i in chosen if rows[i]["prompt"] not in cache]
    print(f"{len(chosen)} rows chosen, {len(todo)} to rewrite")

    def work(i):
        out, why = rewrite_one(rows[i], random.Random(i))
        return i, out, why
    with ThreadPoolExecutor(a.workers) as pool, cache_path.open("a") as cf:
        for n, (i, out, why) in enumerate(pool.map(work, todo), 1):
            rec = {"key": rows[i]["prompt"], "out": out, "why": why}
            cache[rec["key"]] = rec; cf.write(json.dumps(rec, ensure_ascii=False) + "\n"); cf.flush()
            if n % 100 == 0:
                print(f"  {n}/{len(todo)}", flush=True)
    from collections import Counter
    whys = Counter(cache[rows[i]["prompt"]]["why"] for i in chosen)
    out_rows = []
    for i, r in enumerate(rows):
        rec = cache.get(r["prompt"]) if i in set(chosen) else None
        if rec and rec["out"]:
            it = rec["out"]["item"]
            r = {**r, "prompt": extract.training_prompt(it, r["meta"]["today"]),
                 "meta": {**r["meta"], "item": it, "clean": rec["out"]["text"], "rewritten": rec["out"]["style"]}}
        out_rows.append(r)
    (HERE / a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows))
    (HERE / ("adaption_" + a.out)).write_text("".join(
        json.dumps({"prompt": r["prompt"], "completion": r["completion"]}, ensure_ascii=False) + "\n" for r in out_rows))
    print("results:", dict(whys), "->", sum("rewritten" in r["meta"] for r in out_rows), "rows rewritten of", len(out_rows))


if __name__ == "__main__":
    main()
