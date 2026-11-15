"""Keep only trustworthy rows from an Adaption expand/augment download.

    python finetune/v2/filter_expanded.py adaption_expand_raw.jsonl     # -> expand_kept.jsonl + a report

A generated row is kept when (1) its completion is the word null or valid strict-schema JSON, (2) its prompt
carries a search result we can read back (the training prompt's JSON block), and (3) the strict base extractor
(LLM_ENDPOINT) agrees with the completion on event vs null and, for events, on type. Kept rows are rebuilt with
agent.extract.training_prompt, so the prompt text is exactly the live one.
"""
import json, pathlib, re, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from agent import extract  # noqa: E402

TYPES = set(extract.EVENT_TYPES)
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_completion(text: str):
    t = (text or "").strip()
    if t == "null":
        return "null"
    try:
        o = json.loads(t)
    except ValueError:
        return None
    ok = (isinstance(o, dict) and o.get("type") in TYPES and isinstance(o.get("location"), dict)
          and isinstance(o["location"].get("name"), str) and o["location"]["name"].strip()
          and isinstance(o.get("window"), dict) and isinstance(o.get("summary"), str) and o["summary"].strip()
          and all(v is None or (isinstance(v, str) and DAY.match(v)) for v in (o["window"].get("start"), o["window"].get("end"))))
    return o if ok else None


def read_item(prompt: str):
    m = re.search(r"Search result:\s*(\{.*\})\s*$", prompt or "", re.S)
    if not m:
        return None, None
    try:
        u = json.loads(m.group(1))
    except ValueError:
        return None, None
    if not isinstance(u, dict) or not u.get("text"):
        return None, None
    item = {"url": "https://generated.invalid/" + str(abs(hash(u["text"])) % 10**8), "domain": u.get("source") or "generated.invalid",
            "title": u.get("title"), "snippet": u["text"], "published_at": u.get("published_at")}
    return item, u.get("today")


def judge(row):
    comp = valid_completion(row.get("completion"))
    if comp is None:
        return None, "bad completion"
    item, today = read_item(row.get("prompt"))
    if item is None:
        return None, "unreadable prompt"
    pred = extract.extract_raw(item, today)
    if (pred is None) != (comp == "null"):
        return None, "extractor disagrees (event vs null)"
    if comp != "null" and pred["type"] != comp["type"]:
        return None, "extractor disagrees (type)"
    return {"prompt": extract.training_prompt(item, today), "completion": row["completion"].strip(),
            "meta": {"kind": "adaption_expand", "synthetic": True, "item": item, "today": today,
                     "label": None if comp == "null" else comp}}, "kept"


def main():
    src = HERE / sys.argv[1]
    rows = []
    for line in src.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rows.append({"prompt": r.get("prompt") or r.get("input") or "", "completion": r.get("completion") or r.get("output") or ""})
    with ThreadPoolExecutor(3) as pool:
        res = list(pool.map(judge, rows))
    kept = [k for k, _ in res if k]
    print(f"{len(rows)} rows: {dict(Counter(w for _, w in res))}; null share among kept "
          f"{sum(k['completion'] == 'null' for k in kept) / max(1, len(kept)):.0%}")
    (HERE / "expand_kept.jsonl").write_text("".join(json.dumps(k, ensure_ascii=False) + "\n" for k in kept))


if __name__ == "__main__":
    main()
