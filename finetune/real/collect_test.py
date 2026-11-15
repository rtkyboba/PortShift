"""Collect a second, untouched real test set (different queries from collect.py). One call per query, no rewording.

    python finetune/real/collect_test.py      # 6 Linkup calls -> finetune/real/test_raw.jsonl (gitignored)

Labels go in test_labels.jsonl and are written before any model is run on these rows.
"""
import json, pathlib, sys
from datetime import date, timedelta
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent import linkup  # noqa: E402

QUERIES = ["Port of Felixstowe disruption OR delays", "Le Havre port strike", "Panama Canal restrictions",
           "Strait of Hormuz shipping", "Busan port strike OR congestion", "Dover Eurotunnel freight delays"]

out = pathlib.Path(__file__).with_name("test_raw.jsonl")
since = (date.today() - timedelta(days=7)).isoformat()
seen, rows = set(), []
for q in QUERIES:
    data = linkup._post("/v1/search", {"q": q, "depth": "standard", "outputType": "searchResults", "maxResults": 10, "fromDate": since})
    for r in data.get("results", []):
        if r.get("type", "text") != "text" or not r.get("url") or r["url"] in seen:
            continue
        seen.add(r["url"])
        rows.append({"query": q, "url": r["url"], "title": r.get("name"), "snippet": r.get("content", ""),
                     "published_at": linkup._published(r.get("publishedAt")), "retrieved_at": linkup._now(), "domain": linkup.domain_of(r["url"])})
out.write_text("".join(json.dumps(r) + "\n" for r in rows))
print(f"{len(QUERIES)} linkup calls; {len(rows)} results -> {out}")
