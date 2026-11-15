"""Monitor: for each corridor, search -> extract -> place -> cross-check -> write.

    python -m agent.monitor                 # all default corridors, writes to the default sink
    python -m agent.monitor --corridor "Suez / Red Sea"

Steps per corridor (AGENTS.md section 7, agent slice 2):
  1. search   each query through linkup.search (it retries on 429 and rewords on empty results)
  2. extract  each result with extract.extract (base model; the model never gives coordinates or status)
  3. place    resolve the named location in the gazetteer; events it cannot place are dropped and counted
  4. cross-check  events at the same place, of the same type, with overlapping windows are one event.
              Status is `confirmed` with two independent domains or one official source, else `suspected`
  5. write    disruption_events and evidence rows (is_fixture = false) through the sink, plus an
              agent_runs record of what the run did.
Rescoring shipments is the risk job's work (pipelines/); the run record sets `needs_rescore`.
Nothing is invented: every evidence row is a URL that Linkup returned, with its retrieval time.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone

from . import extract as extract_mod
from . import gazetteer, linkup
from .sink import default_sink

OFFICIAL_SUFFIXES = (".gov", ".gov.uk", ".gouv.fr", ".europa.eu", ".gov.sg", ".gob.es", ".gov.eg", ".go.id",
                     ".gov.au", ".bund.de")
OFFICIAL_DOMAINS = {"portofrotterdam.com", "portofantwerpbruges.com", "hamburg-port-authority.de", "hpa.hamburg.de",
                    "suezcanal.gov.eg", "doverport.co.uk", "portoflosangeles.org", "polb.com", "fraport.com",
                    "mpa.gov.sg", "felixstowe.com", "calais-port.fr", "eurotunnel.com", "bison-fute.gouv.fr"}

DEFAULT_CORRIDORS = [
    {"name": "North Sea ports", "queries": ["Port of Rotterdam strike OR closure OR delays", "Port of Antwerp strike OR closure",
                                            "Hamburg port disruption"]},
    {"name": "Channel crossing", "queries": ["Calais port strike", "Dover Calais disruption"]},
    {"name": "Suez / Red Sea", "queries": ["Suez Canal closure OR restrictions", "Red Sea shipping disruption"]},
    {"name": "Asia hubs", "queries": ["Singapore port congestion", "Shanghai Ningbo port closure typhoon"]},
    {"name": "US ports and freight", "queries": ["Los Angeles Long Beach port strike OR congestion", "Dallas freight delays"]},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_official(domain: str) -> bool:
    d = (domain or "").lower()
    # government suffixes only at the END of the host: "news.gov.attacker.example" is not a government site
    return d in OFFICIAL_DOMAINS or any(d.endswith(s) for s in OFFICIAL_SUFFIXES) or bool(re.search(r"(?:^|\.)gov(?:\.[a-z]{2})?$", d))


def _hash(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:8]


def _overlap(a: dict, b: dict, slack_days: int = 3) -> bool:
    pad = timedelta(days=slack_days)
    f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return f(a["window_start"]) - pad <= f(b["window_end"]) and f(b["window_start"]) - pad <= f(a["window_end"])


def cross_check(items: list[dict]) -> list[dict]:
    """Group placed extractions into events, with their evidence and a confirmed/suspected status."""
    groups: list[dict] = []
    for item in items:
        for group in groups:
            if group["place"] == item["place"] and group["type"] == item["type"] and _overlap(group, item):
                group["items"].append(item)
                group["window_start"] = min(group["window_start"], item["window_start"])
                group["window_end"] = max(group["window_end"], item["window_end"])
                break
        else:
            groups.append({"place": item["place"], "type": item["type"], "lat": item["lat"], "lon": item["lon"],
                           "window_start": item["window_start"], "window_end": item["window_end"], "items": [item]})
    for group in groups:
        domains = {i["domain"] for i in group["items"]}
        group["domains"] = domains
        group["official"] = any(is_official(d) for d in domains)
        group["status"] = "confirmed" if group["official"] or len(domains) >= 2 else "suspected"
    return groups


def build_rows(groups: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    events, evidence = [], []
    for g in groups:
        event_id = "L-" + _hash(g["place"], g["type"], g["window_start"][:10])
        summary = g["items"][0]["summary"]
        events.append({"event_id": event_id, "type": g["type"], "status": g["status"], "location": g["place"],
                       "lat": g["lat"], "lon": g["lon"], "radius_km": 25.0, "window_start": g["window_start"],
                       "window_end": g["window_end"], "summary": summary, "detected_at": _iso(now),
                       "is_fixture": False})
        seen = set()
        for i in g["items"]:
            if i["source_url"] in seen:
                continue
            seen.add(i["source_url"])
            evidence.append({"evidence_id": "V-" + _hash(i["source_url"], event_id), "event_id": event_id,
                             "claim": i["summary"], "url": i["source_url"], "title": i["title"],
                             "retrieved_at": i["retrieved_at"], "published_at": i["published_at"],
                             "domain": i["domain"], "is_official": is_official(i["domain"])})
    return events, evidence


def run_corridor_record(corridor: dict, sink=None, now: datetime | None = None, search_fn=None,
                        extract_fn=None, write_run: bool = True) -> dict:
    """Run one corridor and return the full run record (also written to the sink as agent_runs)."""
    now = now or _now()
    search_fn = search_fn or linkup.search
    extract_fn = extract_fn or extract_mod.extract
    sink = sink if sink is not None else default_sink()
    record = {"run_id": "R-" + _hash(corridor["name"], _iso(now)), "corridor": corridor["name"],
              "started_at": _iso(now), "finished_at": None, "queries_run": 0, "results_seen": 0, "events_extracted": 0,
              "events_dropped": 0, "dropped_reasons": [], "event_ids": [], "needs_rescore": False, "error": None,
              "steps": []}
    placed = []
    try:
        for query in corridor["queries"]:
            results = search_fn(query, from_date=_iso(now - timedelta(days=7))[:10])
            step = {"query": query, "results": len(results), "extracted": 0, "dropped": []}
            record["queries_run"] += 1
            record["results_seen"] += len(results)
            for item in results:
                event = extract_fn(item, today=_iso(now)[:10])
                if event is None:
                    continue
                place = gazetteer.resolve(event["location_name"])
                if place is None:
                    reason = f"unknown place '{event['location_name']}'"
                    step["dropped"].append(reason)
                    record["dropped_reasons"].append(reason)
                    record["events_dropped"] += 1
                    continue
                step["extracted"] += 1
                record["events_extracted"] += 1
                placed.append({**event, "place": place[0], "lat": place[1], "lon": place[2], "title": item["title"],
                               "domain": item["domain"], "retrieved_at": item["retrieved_at"]})
            record["steps"].append(step)
        events, evidence = build_rows(cross_check(placed), now)
        if events:
            sink.write("disruption_events", events, ["event_id"])
            sink.write("evidence", evidence, ["evidence_id"])
            record["event_ids"] = [e["event_id"] for e in events]
            record["needs_rescore"] = True
    except Exception as error:  # a failed corridor must not stop the others
        record["error"] = f"{type(error).__name__}: {error}"
    record["finished_at"] = _iso(_now())
    if write_run:
        try:
            sink.write("agent_runs", [{**{k: v for k, v in record.items() if k != "steps"},
                                       "steps_json": json.dumps(record["steps"])}], ["run_id"])
        except Exception:  # the table may not exist in Delta yet; the record is still returned
            pass
    return record


def run_corridor(corridor: dict, **kwargs) -> list[str]:
    """CONTRACTS.md signature: returns the event_ids written."""
    return run_corridor_record(corridor, **kwargs)["event_ids"]


def run(corridors: list[dict] | None = None, **kwargs) -> list[dict]:
    sink = kwargs.pop("sink", None) or default_sink()
    return [run_corridor_record(c, sink=sink, **kwargs) for c in (corridors or DEFAULT_CORRIDORS)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corridor", help="run only the corridor with this name")
    a = ap.parse_args(argv)
    if not linkup.available():
        print("LINKUP_API_KEY is not set: no live search, nothing to do (and nothing is invented).")
        return 2
    from . import llm
    if not llm.available():
        print("No LLM configured (LLM_ENDPOINT, OLLAMA_MODEL or ANTHROPIC_API_KEY): cannot extract events.")
        return 2
    corridors = [c for c in DEFAULT_CORRIDORS if not a.corridor or c["name"] == a.corridor]
    sink = default_sink()
    print(f"writing to {sink.describe()}")
    for rec in run(corridors, sink=sink):
        print(f"{rec['corridor']}: {rec['queries_run']} queries, {rec['results_seen']} results, "
              f"{rec['events_extracted']} placed, {rec['events_dropped']} dropped, events {rec['event_ids']}"
              + (f", ERROR {rec['error']}" if rec["error"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
