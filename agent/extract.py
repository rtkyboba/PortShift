"""Disruption-event extractor: news snippet -> structured event (CONTRACTS.md section 4).

Runs the base model through llm.py with a fixed prompt (EXTRACTOR_USE_BASE=1 behaviour, the live
path). The Adaption fine-tune is evaluated offline in evals/; it is not served from here yet.
The model never outputs coordinates, status, costs or risk: coordinates come from the gazetteer and
status from the monitor's cross-check, both in code.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

from . import llm

EVENT_TYPES = ("strike", "closure", "weather", "warning", "congestion", "other")

SYSTEM = """You decide whether a web search result reports a disruption to freight movement, and if so extract it.

Reply with ONLY a JSON object or the single word null. JSON schema:
{"type": "strike|closure|weather|warning|congestion|other",
 "location": {"name": "the exact place named in the text"},
 "window": {"start": "YYYY-MM-DD or null", "end": "YYYY-MM-DD or null"},
 "summary": "one factual sentence from the text"}

Extract an event ONLY when the text reports a specific disruption (happening, announced, or recently happened)
that stops, slows or threatens freight at a NAMED place: a port, terminal, canal, strait, sea lane, airport,
border crossing, or a named road, bridge, tunnel, rail line or station.

Reply null when the text is any of these, even if it mentions ports, strikes or delays:
- statistics, results or recaps where disruptions are only past causes ("strikes weighed on Q3 throughput")
- funding, state aid, investment, land sales, contracts, partnerships, conferences, awards, sport, tourism
- recovery or resumption news ("traffic resumes", "carrier returns to the route", "back to near normal")
- speculation, analysis, risk commentary or warnings with no concrete development ("could become a target")
- a person's profile, CV or job page, a list of links, site navigation, or a page about something else
- a different meaning of the word ("vulture strike", "strike a deal"), or one vessel's legal or private matter
- a mass action with no named place ("dockworkers at 113 ports in 22 countries")
- condition reports or plans with no closure or restriction announced

Fields:
- type: strike = industrial action that is happening or has been called for given dates; warning = a threatened,
  balloted or deferred strike, or an official alert of a possible disruption; closure = a facility, lane or route
  closed or restricted (including security incidents that stop traffic); weather = storm, fog, flood, ice, snow, heat (also when weather is what closes a route);
  congestion = queues, waiting times, yard or berth occupancy, dwell times; other = attacks on shipping, conflict,
  accidents or anything else that disrupts freight.
- location.name: the most specific place named for THIS disruption (a bridge, station or terminal, not the
  nearest well-known port), in English: "Hamburger Hafen" -> "Port of Hamburg", "gare de Calais-Frethun" ->
  "Calais-Frethun station". If several places, the one the text is mainly about, or the first one listed.
- window: dates the disruption applies to, from the text. For a deferred strike, start is the new deadline.
  If no date is given, start is the publication date and end is null. Resolve "Monday", "next week" against
  the publication date. Do not drop an event because its dates are in the past.
- summary: one sentence in English, using only facts stated in the text.
Never output coordinates, status, costs or risk."""


def _iso(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text if "T" in text else text + "T00:00:00+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(text: str | None, published_at: str | None = None) -> dict | None:
    """Validate the model's reply; None when it is null, malformed or unusable."""
    if not text:
        return None
    body = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    if body.lower() == "null":
        return None
    try:
        data = json.loads(body)
    except ValueError:
        match = re.search(r"\{.*\}", body, re.S)
        try:
            data = json.loads(match.group(0)) if match else None
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return None
    name = (data.get("location") or {}).get("name") if isinstance(data.get("location"), dict) else None
    summary = data.get("summary")
    window = data.get("window") if isinstance(data.get("window"), dict) else {}
    start = _iso(window.get("start")) or _iso(published_at)
    if not (isinstance(name, str) and name.strip() and isinstance(summary, str) and summary.strip() and start):
        return None
    end = _iso(window.get("end"))
    if end is None:  # contract: unknown end means start + 72 h
        end = (datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if end < start:
        return None
    kind = data.get("type") if data.get("type") in EVENT_TYPES else "other"
    return {"type": kind, "location_name": name.strip(), "window_start": start, "window_end": end,
            "summary": summary.strip()[:300]}


def build_user(item: dict, today: str | None = None) -> str:
    """The model input. The same text is used for the base model and in the fine-tune training prompts."""
    return json.dumps({"source": item.get("domain") or item.get("url"), "title": item.get("title"),
                       "published_at": item.get("published_at"), "today": today,
                       "text": (item.get("snippet") or "")[:2500]}, ensure_ascii=False)


def training_prompt(item: dict, today: str | None = None) -> str:
    """Single-string prompt for instruction fine-tuning and for serving the fine-tune (no system role)."""
    return SYSTEM + "\n\nSearch result:\n" + build_user(item, today)


def _with_source(event, item):
    return None if event is None else {**event, "source_url": item["url"], "published_at": item.get("published_at")}


def extract_raw(item: dict, today: str | None = None, retries: int = 3, sleep=time.sleep) -> dict | None:
    """The model's reading of one search result, with no date filter. Retries when the call itself fails."""
    if not llm.available():
        return None
    text = None
    for attempt in range(retries + 1):  # complete() returns None on any failure (rate limit, timeout); "null" is a reply
        text = llm.complete(SYSTEM, build_user(item, today), max_tokens=300, timeout=60)
        if text is not None:
            break
        sleep(2 ** attempt)
    return _with_source(parse(text, item.get("published_at")), item)


def extract_via_endpoint(item: dict, today: str | None, url: str, model: str = "ft") -> dict | None:
    """Same as extract_raw through an OpenAI-compatible endpoint given the training prompt (fine-tune serving)."""
    import urllib.request
    body = {"model": model, "temperature": 0, "max_tokens": 300,
            "messages": [{"role": "user", "content": training_prompt(item, today)}]}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            text = json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception:
        return None
    return _with_source(parse(text, item.get("published_at")), item)


def ended_before(event: dict, today: str | None) -> bool:
    """True when the event's window ended before `today` (YYYY-MM-DD...). Decided in code, not by the model."""
    return bool(today) and event["window_end"][:10] < today[:10]


def extract(item: dict, today: str | None = None) -> dict | None:
    """item = a linkup.search result. Returns the parsed event plus its source, or None (also when it already ended)."""
    event = extract_raw(item, today)
    if event is None or ended_before(event, today):
        return None
    return event
