"""Market rates: what current freight rates are being reported at, with a source for every line.

Live, each topic is one Linkup search (agent/linkup.py) and every result is shown in the source's own words
with its URL and the time it was retrieved. No model extracts or computes a figure here.
Without LINKUP_API_KEY the rows come from demo/fixtures/market_rates.json and carry is_fixture = true, so the
UI shows a "sample" badge.

These are published benchmarks and reports, not quotes from a carrier. They do not feed the cost formula:
estimates come from the rate tables in costing.py (the operator's own rates, else illustrative defaults).
"""
import sys
import time

import data

TOPICS = [
    {"id": "ocean-asia-europe", "mode": "ship", "label": "Container shipping, Asia to North Europe",
     "query": "container spot freight rate Shanghai to Rotterdam per 40ft this week World Container Index"},
    {"id": "ocean-short-sea", "mode": "ship", "label": "Short-sea and ferry, UK and near Continent",
     "query": "short sea container and ferry freight rates UK to Europe current"},
    {"id": "air", "mode": "plane", "label": "Air freight",
     "query": "air cargo freight rates per kg this week Europe TAC Index"},
    {"id": "road", "mode": "truck", "label": "Road freight, UK and Europe",
     "query": "European road freight rate index latest quarter haulage rates per km"},
]
TTL_SECONDS = 30 * 60
_cache: dict = {"at": 0.0, "value": None}


def _linkup():
    root = str(data._here.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from agent import linkup
    return linkup


def _live() -> list[dict] | None:
    """One search per topic. None when live search is not configured or returned nothing at all."""
    try:
        linkup = _linkup()
        if not linkup.available():
            return None
        topics = []
        for t in TOPICS:
            rows = linkup.search(t["query"], max_results=3)
            topics.append({**t, "items": [{"claim": r["snippet"].strip()[:400], "url": r["url"], "title": r["title"],
                                           "domain": r["domain"], "retrieved_at": r["retrieved_at"],
                                           "published_at": r["published_at"], "is_fixture": False}
                                          for r in rows if r.get("snippet") and r.get("url")]})
        return topics if any(t["items"] for t in topics) else None
    except Exception:
        return None


def _sample() -> list[dict]:
    try:
        rows = data._rows("market_rates")
    except OSError:
        rows = []
    return [{**t, "items": [{k: r[k] for k in ("claim", "url", "title", "domain", "retrieved_at", "published_at", "is_fixture")}
                            for r in rows if r["topic"] == t["id"]]} for t in TOPICS]


def market_rates(refresh: bool = False) -> dict:
    if not refresh and _cache["value"] and time.time() - _cache["at"] < TTL_SECONDS and _cache["value"]["live"]:
        return _cache["value"]
    live = _live()
    value = {
        "live": live is not None,
        "topics": live if live is not None else _sample(),
        "our_rates": data.optional_rows("rate_cards"),  # the default rate cards estimates fall back on
        "note": "Published benchmarks and reports, in the source's own words. Not quotes from a carrier. "
                "PortShift's cost estimates do not use them: they use your own rates where you have entered them, "
                "and illustrative defaults otherwise (see My rates).",
    }
    _cache.update(at=time.time(), value=value)
    return value
