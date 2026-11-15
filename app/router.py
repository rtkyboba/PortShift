"""Read an operator's message into one structured request for Ask PortShifter.

  {"intent", "goal", "budget_eur", "corridor", "shipment_ids",
   "shipments": [{"stops": [names], "cargo", "when"}],   # new shipments
   "details": [{"ref", "cargo", "when"}]}                # cargo or timing added to shipments already being planned

Two readers:
  * the fine-tuned request reader (finetune/router/), when ROUTER_ENDPOINT points at it: an OpenAI-compatible
    chat-completions URL, for example finetune/serve_local.py serving the adapter. It gets the exact prompt it
    was trained on.
  * fixed patterns, always available, and the fallback whenever the model is not configured, does not answer,
    or answers something that fails the checks below.
A model reply is only used if it is well formed AND everything in it can be found in the message: shipment ids,
the budget figure, the cargo count, and every word of every stop. So the model can route and split a sentence,
but it cannot introduce a place, a number or a shipment the operator did not type. It never chooses an option,
a route or a cost; those stay in code.
"""
import json
import os
import re
import urllib.request

import assistant
import data
import newplan
import planner

from reader_prompt import CORRIDORS, GOALS, INTENTS, PROMPT, UNIT_TYPES, WHEN_KINDS  # noqa: E402

_FLEET = re.compile(r"\b(optimi[sz]e|reschedul\w*|rerout\w*|re-rout\w*|re-?plan\w*|plan|fix|sort out|handle|resolve|deal with|take care of|tidy up|work through|go through)\b"
                    r"[^.?!]*\b(everything|every (disrupted |affected )?shipment|all( of)?( the| my)?( affected| disrupted)? (shipments|loads)|all of (it|them)|"
                    r"the (whole |entire )?fleet|whole fleet|them all|it all|the lot)\b", re.I)
_CHECK = re.compile(r"\b(check|search|scan|look|monitor|sweep|refresh)\b[^.?!]*\b(disruptions?|news|strikes?|closures?|live|web|online|sources?|wires)\b|\brun (a )?(live )?check\b", re.I)
_NEW = re.compile(r"\bnew (shipments?|loads?|deliver(y|ies)|jobs?|consignments?|work)\b|\b(plan|schedule|add|create|set up|book|send|ship|move)\b[^.?!]*\b\w[\w ()]*\s+(to|->)\s+\w", re.I)
_ATTENTION = re.compile(r"needs? (me|my attention|attention)|do first|deal with first|priorit|urgent|what now|on fire|start this morning|act on immediately|top of my list|"
                        r"most (pressing|important|critical)|what should i (do|look at)", re.I)
_ID = re.compile(r"\bS-\d+\b", re.I)
_CORRIDOR_WORDS = {"North Sea ports": ("north sea", "rotterdam", "antwerp", "hamburg"), "Channel crossing": ("channel", "calais", "dover"),
                   "Suez / Red Sea": ("suez", "red sea"), "Asia hubs": ("asia", "singapore", "shanghai", "ningbo"),
                   "US ports and freight": ("us ports", "american ports", "los angeles", "long beach", "dallas", " la ")}


def _blank(intent: str) -> dict:
    return {"intent": intent, "goal": None, "budget_eur": None, "corridor": None, "shipment_ids": [], "shipments": [], "details": []}


def goal_and_budget(text: str) -> tuple[str | None, float | None]:
    risk = re.search(r"(low|least|less|minim|reduc|avoid|safe)\w*\W+(\w+\W+){0,3}(risk|disruption)|safest|safer|safely|safety", text, re.I)
    cost = re.search(r"(low|least|cheap|minim|less|reduc|keep)\w*\W+(\w+\W+){0,3}(cost|spend)|cheap|tight budget|save money|as little as", text, re.I)
    m = re.search(r"(?:under|below|within|budget(?: of)?|max(?:imum)?(?: of)?|no more than|up to|capped at|more than)\s*(?:eur|€|euros?)?\s*([\d][\d,.]*)\s*(k)?", text, re.I)
    total = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1) if m else None
    goal = "balanced" if risk and cost else "least_risk" if risk else "least_cost" if cost else None
    return goal, (total if total and total > 0 else None)


def corridor_of(text: str) -> str | None:
    low = f" {text.lower()} "
    return next((c for c, words in _CORRIDOR_WORDS.items() if c.lower() in low or any(w in low for w in words)), None)


def _slim(cargo):
    return {"units": cargo["units"], "unit_type": cargo["unit_type"]} if cargo else None


def by_patterns(message: str, expecting: str | None = None) -> dict:
    """expecting = "shipment_details" while the chat is waiting for the cargo or timing of shipments it is planning."""
    ids = [i.upper() for i in dict.fromkeys(_ID.findall(message))]
    details = newplan.details_of(message)
    if details and (expecting == "shipment_details" or (not newplan._HOP.search(message) and not ids and not _FLEET.search(message)
                                                         and not re.search(r"\bstock\b|how many|how much|what|which|why|\?", message, re.I))):
        return {**_blank("shipment_details"), "details": [{"ref": d["ref"], "cargo": _slim(d["cargo"]), "when": d["when"]} for d in details]}
    if _FLEET.search(message):
        goal, budget = goal_and_budget(message)
        return {**_blank("plan_fleet"), "goal": goal, "budget_eur": budget}
    if _CHECK.search(message):
        return {**_blank("live_check"), "corridor": corridor_of(message)}
    if _NEW.search(message) and not ids:
        places = planner.PLACES
        return {**_blank("plan_new_shipments"), "shipments": [{"stops": s["names"], "cargo": _slim(s["cargo"]), "when": s["when"]}
                                                              for s in newplan.parse(message, places)]}
    if _ATTENTION.search(message):
        return _blank("needs_attention")
    if assistant._GREETING.match(message):
        return _blank("greeting")
    if re.search(r"what can you|who are you|what do you do|^\s*help\b|how do (you work|i use you)|what are you|what can i ask", message, re.I):
        return _blank("help")
    if ids:
        return {**_blank("shipment_question"), "shipment_ids": ids}
    if not assistant.in_scope(message, [], data.shipments(), data.events()):
        return _blank("out_of_scope")
    if re.search(r"\bstock\b|stockpile|inventory|on hand|dispatch orders?|pallets (do we have|at)", message, re.I):
        return _blank("stock_question")
    return _blank("fleet_question")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _number_in(value, message: str) -> bool:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return False
    found = set()
    for digits, k in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*(k)?", message.lower()):
        try:
            found.add(float(digits.replace(",", "")) * (1000 if k else 1))
            found.add(float(digits.replace(",", "")))
        except ValueError:
            pass
    return n in found


def checked(reply, message: str) -> dict | None:
    """The model's reply as a request, or None if it is malformed or contains anything not in the message."""
    if not isinstance(reply, dict) or reply.get("intent") not in INTENTS:
        return None
    goal, budget, corridor = reply.get("goal"), reply.get("budget_eur"), reply.get("corridor")
    ids, shipments = reply.get("shipment_ids") or [], reply.get("shipments") or []
    if goal not in (None, *GOALS) or corridor not in (None, *CORRIDORS) or not isinstance(ids, list) or not isinstance(shipments, list):
        return None
    if budget is not None and not _number_in(budget, message):
        return None
    said = _words(message)
    if any(not isinstance(i, str) or not _ID.fullmatch(i) or i.lower() not in message.lower() for i in ids):
        return None

    def cargo_ok(cargo):
        return cargo is None or (isinstance(cargo, dict) and cargo.get("unit_type") in UNIT_TYPES and _number_in(cargo.get("units"), message))

    def when_ok(when):
        return when is None or (isinstance(when, dict) and when.get("kind") in WHEN_KINDS and isinstance(when.get("text"), str)
                                and _words(when["text"]) and _words(when["text"]) <= said)

    def clean(cargo, when):
        return ({"units": float(cargo["units"]), "unit_type": cargo["unit_type"]} if cargo else None,
                {"kind": when["kind"], "text": when["text"].strip()} if when else None)

    out, extra = [], []
    for s in shipments:
        stops, cargo, when = (s or {}).get("stops"), (s or {}).get("cargo"), (s or {}).get("when")
        if not isinstance(stops, list) or len(stops) < 2 or any(not isinstance(x, str) or not _words(x) or not _words(x) <= said for x in stops):
            return None
        if not cargo_ok(cargo) or not when_ok(when):
            return None
        c, w = clean(cargo, when)
        out.append({"stops": [x.strip() for x in stops], "cargo": c, "when": w})
    details = reply.get("details") or []
    if not isinstance(details, list):
        return None
    for d in details:
        ref, cargo, when = (d or {}).get("ref"), (d or {}).get("cargo"), (d or {}).get("when")
        if ref is not None:
            m = re.fullmatch(r"NEW-(\d+)", str(ref))
            ordinal = {1: r"first|1st", 2: r"second|2nd", 3: r"third|3rd", 4: r"fourth|4th"}
            if not m or not (str(ref).lower() in message.lower() or re.search(rf"\b({ordinal.get(int(m.group(1)), 'x^')})\b", message, re.I)):
                return None
        if not cargo_ok(cargo) or not when_ok(when) or (cargo is None and when is None):
            return None
        c, w = clean(cargo, when)
        extra.append({"ref": ref, "cargo": c, "when": w})
    if (reply["intent"] == "plan_new_shipments" and not out) or (reply["intent"] == "shipment_details" and not extra):
        return None
    return {"intent": reply["intent"], "goal": goal, "budget_eur": float(budget) if budget is not None else None, "corridor": corridor,
            "shipment_ids": [i.upper() for i in ids], "shipments": out, "details": extra}


def ask_model(message: str, url: str, timeout: float = 15.0) -> dict | None:
    """The raw reply of a request-reader endpoint, parsed, or None."""
    body = json.dumps({"model": os.environ.get("ROUTER_MODEL", "request-reader"), "temperature": 0, "max_tokens": 400,
                       "messages": [{"role": "user", "content": PROMPT + message}]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=timeout) as r:
            text = json.load(r)["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def _drop_empty(reply):
    """The model sometimes appends a shipment entry with no stops: that carries nothing, so it is dropped."""
    if isinstance(reply, dict) and isinstance(reply.get("shipments"), list):
        reply = {**reply, "shipments": [x for x in reply["shipments"] if isinstance(x, dict) and x.get("stops")]}
    return reply


def with_model_split(patterns: dict, model: dict | None) -> dict | None:
    """The patterns' reading of a new-shipments message, with the stops of each shipment taken from the model.
    On held-out wording the fixed patterns are better at saying what a message is and at cargo and timing, and the
    fine-tuned reader is much better at splitting a sentence into shipments and stops (finetune/RESULTS.md), so
    each does its part. Where both found the same number of shipments, cargo and timing stay with the patterns
    and the model only fills what they left empty. None when the model has no usable split."""
    if not model or model["intent"] != "plan_new_shipments" or not model["shipments"]:
        return None
    ships = model["shipments"]
    if len(ships) == len(patterns["shipments"]):
        ships = [{"stops": m["stops"], "cargo": q["cargo"] or m["cargo"], "when": q["when"] or m["when"]} for m, q in zip(ships, patterns["shipments"])]
    return {**patterns, "shipments": ships}


def read(message: str, expecting: str | None = None) -> dict:
    """{"request", "source": model | patterns, "why"}: how the message was read, and by what.
    The patterns always read it first. When the request reader is configured (ROUTER_ENDPOINT) and the message is
    about new shipments, the reader splits it into shipments and stops; its answer is checked against the message."""
    typed = (message or "").strip()[:1000]
    ships, events = data.shipments(), data.events()
    message = assistant.meant(typed, ships, events)  # typing slips, shorthand and loose shipment numbers put right
    out = _read(message, expecting)
    return {**out, "understood_as": message if message != typed else None}


def _read(message: str, expecting: str | None) -> dict:
    request = by_patterns(message, expecting)
    url = os.environ.get("ROUTER_ENDPOINT")
    if not url or not message:
        return {"request": request, "source": "patterns", "why": "read by fixed patterns (no request reader is configured)"}
    if request["intent"] != "plan_new_shipments":
        return {"request": request, "source": "patterns", "why": "read by fixed patterns (the request reader is used for splitting new shipments)"}
    reply = ask_model(message, url)
    merged = with_model_split(request, checked(_drop_empty(reply), message))
    if merged:
        return {"request": merged, "source": "model", "why": "the fine-tuned request reader split this into shipments and stops; every place, figure and date was checked against your message"}
    why = "the request reader did not answer" if reply is None else "the request reader's answer failed the checks"
    return {"request": request, "source": "patterns", "why": why + ", so the fixed patterns were used"}
