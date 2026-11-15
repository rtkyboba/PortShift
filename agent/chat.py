"""Chat for the app: three intents (explain, cost to reschedule, suggest a plan).

How an answer is built:
  1. Intent from the message (plain keywords, so it is predictable and testable).
  2. Facts from code: plan.py options, cost.py formulas, evidence rows. Never from the LLM.
  3. The LLM (llm.py) only writes wording around those facts. Its text is rejected if it contains
     a figure it was not given, and the option list is always printed by code.
  4. No LLM key, a failure, or a rejected text: a plain template is used, so chat always works.

The user's limits (risk level, extra cost, extra delay) can be set in the sentence ("suggest routes,
max risk 2, under EUR 3000"), or passed as the `preferences` object by the UI. They persist for
the running process.
"""
import json
import os
import re

from . import cost, llm, plan, store
from .plan import RISK_NAMES, Preferences

_session = Preferences()

SUGGEST_WORDS = ("suggest", "route", "reroute", "plan", "alternative", "option", "recommend", "avoid",
                 "what should", "what can i do", "best way", "how do i get around")
COST_WORDS = ("cost", "price", "how much", "expensive", "cheaper", "another date", "move this", "reschedule",
              "postpone", "delay it")

SYSTEM = (
    "You are PortShift's assistant for a logistics operations coordinator. Answer from CONTEXT only. "
    "Write at most {limit}. Plain sentences, no markdown, no lists: the app prints option tables itself. "
    "Never state a number, date, source or shipment fact that is not in CONTEXT, and never round or "
    "recompute figures. Money figures are estimates from illustrative rates; say 'estimate' when you "
    "mention one. Call the result a 'suggested plan', never 'optimal'. If CONTEXT cannot answer the "
    "question, say so briefly."
)


# ---------------------------------------------------------------- limits from the sentence
def parse_preferences(message: str, base: Preferences) -> tuple[Preferences, bool]:
    """Read 'max risk 2', 'under EUR 3000', 'no more than 12 hours delay' etc. from the message."""
    text = message.lower().replace(",", "")
    prefs = Preferences(**base.to_dict())
    changed = False

    limiter = r"(?:at most|up to|max(?:imum)?|no more than|no higher than|below|under|within|<=|≤)"
    m = (re.search(r"risk[^.\d]{0,25}?" + limiter + r"\s*(?:level\s*)?([1-5])\b", text)
         or re.search(limiter + r"\s*risk\s*(?:level\s*)?(?:to|of|at|=)?\s*(?:level\s*)?([1-5])\b", text)
         or re.search(r"(?:set|change|make|lower|raise)[^.\d]{0,20}risk[^.\d]{0,15}?\bto\s*(?:level\s*)?([1-5])\b", text)
         or re.search(r"risk(?:\s*level)?\s*([1-5])\s*(?:or\s*(?:lower|less|below)|and\s*below)", text)
         or re.search(r"risk\s*(?:level\s*)?(?:limit|tolerance)\s*(?:of|is|to|=)?\s*([1-5])\b", text))
    if m:
        prefs.max_risk, changed = int(m.group(1)), True
    elif re.search(r"\b(lowest|minimum|zero|no) risk\b|\bonly clear\b", text):
        prefs.max_risk, changed = 1, True

    if re.search(r"(no|unlimited)\s+(cost|price|budget)\s*(limit|cap)?|unlimited budget", text):
        prefs.max_extra_cost, changed = None, True
    elif re.search(r"cost|price|budget|eur|€|spend|pay", text):
        # only take a figure that sits next to a cost word or a limiter, never a bare shipment number
        m = re.search(r"(?:(?:cost|price|budget|spend|pay)[^.\d]{0,25}?|" + limiter + r"\s*)(?:eur|€)?\s*(\d+(?:\.\d+)?)\s*(k)?", text)
        if m and (re.search(r"eur|€|euro", text) or re.search(r"(cost|price|budget)", text)):
            value = float(m.group(1)) * (1000 if m.group(2) else 1)
            prefs.max_extra_cost, changed = value, True

    m = (re.search(r"(?:delay|late|later|wait)[^.\d]{0,25}?" + limiter + r"?\s*(\d+(?:\.\d+)?)\s*(h|hours?|d|days?)\b", text)
         or re.search(limiter + r"\s*(\d+(?:\.\d+)?)\s*(h|hours?|d|days?)\s*(?:of\s*)?(?:extra\s*)?(?:delay|late|wait)", text))
    if m:
        value = float(m.group(1)) * (24 if m.group(2).startswith("d") else 1)
        prefs.max_delay_hours, changed = value, True
    return prefs, changed


# ---------------------------------------------------------------- intents
def classify(message: str) -> str:
    text = message.lower()
    wants_suggest = any(w in text for w in SUGGEST_WORDS)
    wants_cost = any(w in text for w in COST_WORDS)
    if wants_suggest and not re.search(r"what does it cost|how much|cost to|price of", text):
        return "suggest_plan"
    if wants_cost:
        return "cost_to_reschedule"
    if wants_suggest:
        return "suggest_plan"
    return "explain"


def _citations(event_ids: list[str], db: dict) -> list[dict]:
    seen, out = set(), []
    for row in db["evidence"]:
        if row["event_id"] in event_ids and row["evidence_id"] not in seen:
            seen.add(row["evidence_id"])
            out.append({k: row.get(k) for k in ("claim", "url", "title", "retrieved_at", "published_at")})
    return out


def _money(value: float) -> str:
    return f"EUR {value:,.0f}"


def _risk(level: int) -> str:
    return f"{level} ({RISK_NAMES[level]})"


def _sentence(text: str) -> str:
    text = (text or "").strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _label(row: dict) -> str:
    return f"{row['shipment_id']} {row['origin']} to {row['destination']} ({row['mode']})"


# ---------------------------------------------------------------- deterministic text
def _option_line(o: dict, recommended: bool) -> str:
    mark = "Recommended: " if recommended else ""
    if o["kind"] == "keep":
        body = f"{o['label']}: no extra cost, risk stays {_risk(o['resulting_risk'])}"
    else:
        body = (f"{o['label']}: +{_money(o['extra_cost'])} (estimate), +{o['delay_hours']:g} h, "
                f"risk after {_risk(o['resulting_risk'])}")
    flag = "inside your limits" if o["within_limits"] else "outside your limits: " + "; ".join(o["violations"])
    return f"- {mark}{body} ({flag})."


def plan_block(result: dict) -> str:
    lines = [f"Your limits: {Preferences.from_dict(result['preferences']).describe()}."]
    for row in result["shipments"]:
        lines.append("")
        lines.append(f"{_label(row)}: risk {_risk(row['current_risk'])}. {_sentence(row['reason'])}")
        order = sorted(row["options"], key=lambda o: o["id"] != row["recommended_id"])
        for o in order:
            lines.append(_option_line(o, o["id"] == row["recommended_id"]))
        if row["status"] == "outside_limits":
            lines.append("- No option fits all your limits; the least-bad one is marked Recommended. "
                         "Loosen a limit to see more.")
        elif row["status"] == "no_action_needed":
            lines.append("- Nothing needs to change inside your limits.")
    lines.append("")
    lines.append(f"Suggested plan total: +{_money(result['scenario']['cost_delta'])} (estimate, illustrative rates).")
    return "\n".join(lines)


def _explain_text(row: dict, db: dict) -> str:
    event = row["event"]
    out = f"{_label(row)} is at risk level {_risk(row['current_risk'])}. {_sentence(row['reason'])}"
    if event:
        ids = [e["evidence_id"] for e in db["evidence"] if e["event_id"] == event["event_id"]]
        out += (f" The disruption is a {event['status']} {event['type']} at {event['location']} "
                f"({event['window_start'][:10]} to {event['window_end'][:10]}), backed by {len(ids)} source(s).")
        if event.get("is_fixture"):
            out += " This event is a sample, not a live finding."
    return out


# ---------------------------------------------------------------- LLM wording with a figure guard
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    out = set()
    for token in _NUM.findall(text):
        try:
            out.add(round(float(token.replace(",", ""))))
        except ValueError:
            pass
    return out


_URL = re.compile(r"https?://[^\s)\]>\"']+|\bwww\.[^\s)\]>\"']+", re.I)
_LEAK = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}|\bdapi[0-9a-f]{16,}|Answer from CONTEXT only|Never state a number, date, source", re.I)


def _secrets() -> list[str]:
    return [v for k, v in os.environ.items() if len(v) >= 8 and re.search(r"KEY|TOKEN|SECRET|PASSWORD", k, re.I)]


def _grounded(text: str, context: str) -> bool:
    """True if every figure of 10 or more, and every link, in the text also appears in the context, and the text
    reveals neither these instructions nor a key. A model that obeys text planted in the question fails this."""
    allowed = _numbers(context)
    if not all(n in allowed for n in _numbers(text) if n >= 10):
        return False
    if any(u.rstrip(".,;") not in context for u in _URL.findall(text)):
        return False
    return not (_LEAK.search(text) or any(secret in text for secret in _secrets()))


def _wording(question: str, intent: str, prefs: Preferences, context: dict, fallback: str, limit: str) -> tuple[str, bool]:
    if not llm.available():
        return fallback, False
    ctx = json.dumps(context, default=str)
    user = json.dumps({"question": question, "intent": intent, "preferences": prefs.to_dict(), "CONTEXT": context},
                      default=str)
    text = llm.complete(SYSTEM.format(limit=limit), user)
    if text and _grounded(text, ctx + json.dumps(prefs.to_dict())):
        return text, True
    return fallback, False


# ---------------------------------------------------------------- entry point
def answer(message: str, selected_ids: list[str] | None = None, preferences: dict | None = None,
           db: dict | None = None) -> dict:
    global _session
    db = store.resolve(db)
    selected_ids = [s for s in (selected_ids or []) if s]
    if not selected_ids:  # a shipment named in the message counts as selected
        selected_ids = list(dict.fromkeys(re.findall(r"\bS-\d{4}\b", message.upper())))
    if preferences:
        _session = Preferences.from_dict({**_session.to_dict(), **preferences})
    _session, limits_changed = parse_preferences(message, _session)
    prefs = _session
    intent = classify(message)
    lowered = message.lower()
    only_limits = limits_changed and not any(w in lowered for w in SUGGEST_WORDS + COST_WORDS)
    base = {"preferences": prefs.to_dict(), "intent": intent}

    if only_limits:
        text = f"Limits updated: {prefs.describe()}. Ask me to suggest a plan and I will respect them."
        return {**base, "intent": "set_limits", "text": text, "citations": [], "plan": None, "llm_used": False}

    try:
        if intent == "suggest_plan":
            result = plan.suggest_plan(selected_ids or None, prefs, db)
            if not result["shipments"]:
                return {**base, "text": "No shipment is currently at risk, so there is nothing to re-plan.",
                        "citations": [], "plan": result, "llm_used": False}
            event_ids = [r["event"]["event_id"] for r in result["shipments"] if r["event"]]
            lead_fallback = (f"Here is a suggested plan for {len(result['shipments'])} shipment(s), "
                             f"chosen as the cheapest option inside your limits.")
            lead, used = _wording(message, intent, prefs, {"plan": result}, lead_fallback, "two short sentences")
            return {**base, "text": lead + "\n\n" + plan_block(result), "citations": _citations(event_ids, db),
                    "plan": result, "llm_used": used}

        if not selected_ids:
            if intent == "cost_to_reschedule":
                return {**base, "text": "Select a shipment on the map first, or ask me to suggest a plan for "
                        "all at-risk shipments.", "citations": [], "plan": None, "llm_used": False}
            at_risk = sorted(((int(r["level"]), r["shipment_id"], r["reason"]) for r in db["shipment_risk"]
                              if int(r["level"]) > 1), reverse=True)
            if not at_risk:
                return {**base, "text": "Every shipment is clear.", "citations": [], "plan": None, "llm_used": False}
            fallback = "At-risk shipments: " + " ".join(f"{sid} is {_risk(lvl)}: {why}." for lvl, sid, why in at_risk)
            text, used = _wording(message, intent, prefs, {"at_risk": at_risk}, fallback, "four sentences")
            return {**base, "text": text, "citations": [], "plan": None, "llm_used": used}

        if intent == "cost_to_reschedule":
            lines, rows, event_ids = [], [], []
            result = plan.suggest_plan(selected_ids, prefs, db)
            for row in result["shipments"]:
                rows.append(row)
                if row["event"]:
                    event_ids.append(row["event"]["event_id"])
                resched = next((o for o in row["options"] if o["kind"] == "reschedule"), None)
                if resched:
                    lines.append(f"Moving {_label(row)} past the disruption means delaying it by "
                                 f"{resched['delay_days']} days: +{_money(resched['extra_cost'])} (estimate, illustrative "
                                 f"rates), new start {resched['new_planned_start'][:10]}. "
                                 + ("That is inside your limits." if resched["within_limits"]
                                    else "That is outside your limits: " + "; ".join(resched["violations"]) + "."))
                else:
                    day = cost.reschedule_cost(row["shipment_id"], 1, db)
                    lines.append(f"{_label(row)} has no disruption to wait out, so a date change only adds cost: "
                                 f"one day later is about {_money(day['cost'])} (estimate, illustrative rates).")
            fallback = " ".join(lines)
            text, used = _wording(message, intent, prefs, {"shipments": rows}, fallback, "three sentences")
            return {**base, "text": text, "citations": _citations(event_ids, db), "plan": result, "llm_used": used}

        # explain
        rows = [plan.options_for(sid, db) for sid in selected_ids]
        flat = [{"shipment_id": r["shipment"]["shipment_id"], "origin": r["shipment"]["origin"],
                 "destination": r["shipment"]["destination"], "mode": r["shipment"]["mode"],
                 "current_risk": r["risk"], "reason": r["reason"], "event": r["event"]} for r in rows]
        fallback = " ".join(_explain_text(r, db) for r in flat)
        text, used = _wording(message, intent, prefs, {"shipments": flat}, fallback, "four sentences")
        event_ids = [r["event"]["event_id"] for r in flat if r["event"]]
        return {**base, "text": text, "citations": _citations(event_ids, db), "plan": None, "llm_used": used}
    except KeyError as error:
        return {**base, "text": f"I could not find that shipment ({error}).", "citations": [], "plan": None,
                "llm_used": False}
