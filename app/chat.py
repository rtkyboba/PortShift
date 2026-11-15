"""Chat entry point: three intents only (explain a shipment, cost to reschedule, suggested plan).

Uses the agent's answer() when `agent.chat` exists and works. Otherwise a deterministic,
no-LLM fallback over app/data.py answers from the contract tables. Every figure comes from
the cost_rates formula (CONTRACTS.md section 5); nothing is invented.

answer(message, selected_ids) -> {"text": str, "citations": [{claim, url, title, retrieved_at, published_at}]}
"""
import math
import pathlib
import re
import sys
from datetime import datetime

import data

# The agent package lives at the repo root; uvicorn runs from app/, so add the root to the path.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

try:  # Ryan's agent; may not exist yet
    from agent.chat import answer as agent_answer
except ImportError:
    agent_answer = None

COST_NOTE = "estimate, illustrative rates"
HELP = ("Select a shipment on the map, then ask me one of three things: "
        "explain it (why is it at risk?), the cost to reschedule it (how much?), "
        "or a suggested plan (what should I do?).")

INTENTS = [  # checked in order
    ("plan", ("plan", "suggest", "what should")),
    ("cost", ("cost", "reschedule", "reroute", "re-route", "how much", "price")),
    ("explain", ("explain", "why", "risk", "what happened", "what's wrong")),
]


def detect_intent(message: str) -> str | None:
    m = message.lower()
    for name, words in INTENTS:
        if any(w in m for w in words):
            return name
    return None


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _citations(detail: dict) -> list[dict]:
    keys = ("claim", "url", "title", "retrieved_at", "published_at")
    return [{k: e[k] for k in keys} for e in detail["evidence"]]


def _window_days(detail: dict) -> int | None:
    ev = detail["events"]
    if not ev:
        return None
    span = max(_ts(e["window_end"]) for e in ev) - min(_ts(e["window_start"]) for e in ev)
    return max(1, math.ceil(span.total_seconds() / 86400))


def _rate(mode: str) -> dict | None:
    return next((r for r in data.cost_rates() if r["mode"] == mode), None)


def _delay_days(message: str, detail: dict) -> tuple[int | None, str]:
    m = re.search(r"(\d+)\s*(?:-\s*)?days?\b", message.lower())
    if m:
        return int(m.group(1)), "the delay you asked for"
    for sc in data.scenarios():
        for c in sc["changes"]:
            if c["shipment_id"] == detail["shipment_id"] and c["change_type"] == "reschedule":
                return c["delay_days"], f"the tentative plan {sc['scenario_id']}"
    return _window_days(detail), "the length of the disruption window"


def _extra_km(message: str, detail: dict) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*km", message.lower())
    if m:
        return float(m.group(1))
    for sc in data.scenarios():
        for c in sc["changes"]:
            if c["shipment_id"] == detail["shipment_id"] and c.get("extra_km") is not None:
                return float(c["extra_km"])
    return None


def _money(v: float, cur: str) -> str:
    return f"{cur} {v:,.0f}"


def _explain(d: dict) -> dict:
    lvl = d["risk"]["level"]
    head = f"{d['shipment_id']} ({d['cargo']}, {d['origin']} to {d['destination']}): "
    if not lvl:
        return {"text": head + "not scored yet, so I have no evidence to explain.", "citations": []}
    parts = [head + f"level {lvl}. {d['risk']['reason']}."]
    for e in d["events"]:
        parts.append(f"{e['type'].capitalize()} at {e['location']}: {e['summary']} "
                     f"It is {e['status']} ({e['basis']['text']}).")
    if not d["events"]:
        parts.append("No events affect it.")
    if any(e["is_fixture"] for e in d["events"]):
        parts.append("These events are samples.")
    return {"text": " ".join(parts), "citations": _citations(d)}


def _cost(message: str, d: dict) -> dict:
    sid, rate = d["shipment_id"], _rate(d["mode"])
    if not rate:
        return {"text": f"I have no cost rates for {d['mode']}, so I can't price {sid}.", "citations": []}
    cur = rate["currency"]
    days, basis = _delay_days(message, d)
    parts = []
    if days is None:
        parts.append(f"{sid} has no disruption to wait out. Tell me a delay, for example 'cost to reschedule by 2 days'.")
    else:
        cost = days * rate["per_delay_day"] + rate["rebooking_fee"]
        parts.append(f"Rescheduling {sid} ({d['mode']}) by {days} day(s), based on {basis}: "
                     f"{days} x {_money(rate['per_delay_day'], cur)} + {_money(rate['rebooking_fee'], cur)} "
                     f"rebooking = {_money(cost, cur)}.")
    if re.search(r"re-?route|extra km|\bkm\b", message.lower()):
        km = _extra_km(message, d)
        if km is None:
            parts.append("For a reroute I need the extra distance, for example 'reroute, 300 km extra'.")
        else:
            parts.append(f"Reroute: {km:g} km x {rate['per_extra_km']} = {_money(km * rate['per_extra_km'], cur)}.")
    parts.append(f"({COST_NOTE})")
    return {"text": " ".join(parts), "citations": _citations(d)}


def _plan(details: list[dict]) -> dict:
    """Greedy: highest risk first; reschedule each shipment at level 3+ past its disruption window."""
    ranked = sorted(details, key=lambda d: -(d["risk"]["level"] or 0))
    lines, cites, total, cur = [], [], 0.0, "EUR"
    for d in ranked:
        lvl, rate, days = d["risk"]["level"] or 0, _rate(d["mode"]), _window_days(d)
        if lvl < 3 or not rate or days is None:
            lines.append(f"{d['shipment_id']}: level {lvl}, no change needed.")
            continue
        cur = rate["currency"]
        cost = days * rate["per_delay_day"] + rate["rebooking_fee"]
        total += cost
        lines.append(f"{d['shipment_id']}: reschedule by {days} day(s) to clear the window, {_money(cost, cur)}.")
        cites += _citations(d)
    seen, uniq = set(), []
    for c in cites:
        if c["url"] not in seen:
            seen.add(c["url"])
            uniq.append(c)
    text = "Suggested plan (greedy heuristic, tentative, nothing is booked). " + " ".join(lines)
    if total:
        text += f" Total {_money(total, cur)} ({COST_NOTE})."
    return {"text": text, "citations": uniq}


def fallback_answer(message: str, selected_ids: list[str]) -> dict:
    intent = detect_intent(message)
    details = [d for d in (data.shipment_detail(i) for i in selected_ids) if d]
    if not intent or not details:
        return {"text": HELP, "citations": []}
    if intent == "plan":
        return _plan(details)
    outs = [_cost(message, d) if intent == "cost" else _explain(d) for d in details]
    return {"text": " ".join(o["text"] for o in outs), "citations": [c for o in outs for c in o["citations"]]}


def answer(message: str, selected_ids: list[str], preferences: dict | None = None) -> dict:
    """preferences = optional user limits {max_risk, max_extra_cost, max_delay_hours} (see CONTRACTS.md section 5)."""
    if agent_answer is not None:
        try:
            if preferences is None:  # keep the original two-argument call for callers without limits
                return agent_answer(message, selected_ids)
            return agent_answer(message, selected_ids, preferences)
        except Exception:
            pass
    return fallback_answer(message, selected_ids)
