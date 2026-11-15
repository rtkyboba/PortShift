"""Collect raw Linkup results for the real-snippet eval set. One call per query, no rewording (credit budget).

    python finetune/real/collect.py --max-calls 8 > /dev/null

Writes finetune/real/raw_snippets.jsonl (gitignored: third-party text). Labels live in labels.jsonl, keyed by URL.
"""
import argparse, json, pathlib, sys
from datetime import date, timedelta
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent import linkup  # noqa: E402

QUERIES = [
    "Port of Rotterdam strike OR closure OR delays", "Hamburg port disruption", "Port of Antwerp strike OR closure",
    "Calais port strike", "Suez Canal closure OR restrictions", "Red Sea shipping disruption",
    "Singapore port congestion", "Los Angeles Long Beach port strike OR congestion",
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=8)
    a = ap.parse_args()
    out = pathlib.Path(__file__).with_name("raw_snippets.jsonl")
    seen = {json.loads(l)["url"] for l in out.read_text().splitlines()} if out.exists() else set()
    since = (date.today() - timedelta(days=7)).isoformat()
    n = 0
    with out.open("a") as f:
        for q in QUERIES[: a.max_calls]:
            data = linkup._post("/v1/search", {"q": q, "depth": "standard", "outputType": "searchResults",
                                               "maxResults": 10, "fromDate": since})
            n += 1
            for r in data.get("results", []):
                if r.get("type", "text") != "text" or not r.get("url") or r["url"] in seen:
                    continue
                seen.add(r["url"])
                f.write(json.dumps({"query": q, "url": r["url"], "title": r.get("name"), "snippet": r.get("content", ""),
                                    "published_at": linkup._published(r.get("publishedAt")), "retrieved_at": linkup._now(),
                                    "domain": linkup.domain_of(r["url"])}) + "\n")
    print(f"{n} linkup calls; {len(seen)} unique results in {out}", file=sys.stderr)

if __name__ == "__main__":
    main()
