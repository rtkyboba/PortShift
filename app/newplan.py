"""Plan new shipments from a sentence.

"Help me plan these new shipments with my current fleet: London warehouse to Southampton port, Brussels
warehouse to London warehouse and end at Glasgow" becomes a list of shipments, each a list of stops. Every
stop is matched to a known place (the built-in places and the operator's own), then planner.py suggests
routes for each: by road, sea and air where that makes sense, priced from the rate tables and scored by the
risk job against today's disruptions. The current fleet is checked for shipments already running the same lane.

The sentence is read with fixed patterns and place names are matched by spelling. No model is involved, no
figure is invented, and a name that cannot be placed is reported, never guessed. Nothing is created here.
"""
import difflib
import re

import costing
import data
import planner
import when as timing

KIND_WORDS = {"port": "port", "harbour": "port", "harbor": "port", "docks": "port", "airport": "airport",
              "warehouse": "warehouse", "depot": "warehouse", "dc": "warehouse", "hub": "warehouse"}
KIND_ORDER = {"warehouse": 0, "port": 1, "airport": 2}
_CARGO = re.compile(r"\b(?:carrying |with |of )?(\d+(?:\.\d+)?)\s*(pallets?|teu|reefers?|trailers?|tonnes?|40 ?ft(?: containers?)?|20 ?ft(?: containers?)?|containers?)\b", re.I)
_CARGO_UNIT = {"pallet": "pallet", "teu": "container_20", "reefer": "reefer", "trailer": "trailer", "tonne": "tonne",
               "container": "container_20", "20ft": "container_20", "40ft": "container_40"}
_JOIN = re.compile(r"\s*(?:,\s*)?\b(?:and\s+)?(?:then\s+)?(?:end(?:s|ing)?|finish(?:es|ing)?|terminat\w+)\s+(?:up\s+)?(?:at|in)\b|"
                   r"\s*(?:,\s*)?\b(?:and\s+)?(?:then\s+)?(?:on(?:ward)?\s+to|then\s+to|then)\b", re.I)
_VIA = re.compile(r"\s+(?:via|through|by way of)\s+", re.I)
_SPLIT = re.compile(r"[;\n]+|,\s*(?:and\s+)?|\s+and\s+(?=[^,;\n]*?\bto\b)", re.I)
_HOP = re.compile(r"\s+to\s+|\s*(?:->|→|=>|>)\s*", re.I)
_PREAMBLE = re.compile(r"\b(fleet|shipments?|following|deliver(?:y|ies)|loads?|jobs?|routes?)\b\s*[:,-]?", re.I)


def _tokens(name: str) -> tuple[list[str], str | None]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    kind = next((KIND_WORDS[w] for w in words if w in KIND_WORDS), None)
    return [w for w in words if w not in KIND_WORDS and w not in ("the", "our", "my", "a", "at", "in", "of", "from")], kind


def resolve(name: str, places: list[dict]) -> dict | None:
    """The known place this name means, or None. Every word of the name must match a word of the place
    (small spelling slips allowed); a kind word (port, airport, warehouse) picks between places in one town."""
    want, kind = _tokens(name)
    if not want:
        return None
    best = None
    for p in places:
        have, _ = _tokens(p["name"])
        ratios = [max((difflib.SequenceMatcher(None, w, h).ratio() for h in have), default=0) for w in want]
        if min(ratios) < 0.8:
            continue
        rank = (0 if kind and p["kind"] == kind else 1 if not kind else 2, -sum(ratios) / len(ratios),
                KIND_ORDER.get(p["kind"], 3), len(have))
        if best is None or rank < best[0]:
            best = (rank, p)
    return best[1] if best else None


_ALL = re.compile(r"(?:[,;.]|\band\b)?\s*\b(?:all|both|each|every one)\b(?: of (?:them|these))?(?: (?:shipments?|loads?))?\s+(?P<rest>[^;]+)$", re.I)
_REF = re.compile(r"\bNEW-(\d+)\b|\b(first|second|third|fourth|1st|2nd|3rd|4th)\b(?: (?:one|shipment|load))?", re.I)
_ORDINAL = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}


def cargo_of(text: str) -> tuple[dict | None, tuple[int, int] | None]:
    """The cargo named in the text ("12 reefers", "20 pallets of whisky") and where it is, or (None, None)."""
    m = _CARGO.search(text)
    if not m:
        return None, None
    unit = re.sub(r"\s+|containers?$", "", m.group(2).lower()).rstrip("s") or "container"
    return {"units": float(m.group(1)), "unit_type": _CARGO_UNIT.get(unit, "pallet")}, m.span()


def _cut(text: str, span) -> str:
    return (text[:span[0]] + " " + text[span[1]:]).strip(" .,-") if span else text


def details_of(text: str) -> list[dict]:
    """A reply that fills in what a shipment still needs: [{ref: "NEW-2" | None, cargo, when}].
    "NEW-1: 20 pallets by Friday; NEW-2: 4 reefers asap", "the second one leaves tomorrow", or just "20 pallets, asap"
    (ref None: it applies to every shipment still missing that detail)."""
    parts = [p for p in re.split(r"[;\n]+|(?=\bNEW-\d+\b)", text) if p.strip()]
    out = []
    for part in parts:
        m = _REF.search(part)
        ref = f"NEW-{m.group(1) or _ORDINAL[m.group(2).lower()]}" if m else None
        cargo, _ = cargo_of(part)
        when, _ = timing.find(part)
        if cargo or when:
            out.append({"ref": ref, "cargo": cargo, "when": when})
    return out


def parse(text: str, places: list[dict]) -> list[dict]:
    """[{text, stops: [place], unresolved: [name], names, cargo, when}] for each shipment described in the message.
    Cargo and timing said once for all of them ("... all 10 pallets, arriving by Friday") fill in each shipment
    that does not have its own."""
    body = text.strip().rstrip(".!? ")
    head = _HOP.split(body, maxsplit=1)[0]  # everything before the first "to": the ask, then the first place
    cut = [m.end() for m in _PREAMBLE.finditer(head)]
    if ":" in head:
        body = body[body.index(":") + 1:]
    elif cut:
        body = body[cut[-1]:]
    shared_cargo = shared_when = None
    m = _ALL.search(body)
    if m and not _HOP.search(m.group("rest")):
        shared_cargo, _ = cargo_of(m.group("rest"))
        shared_when, _ = timing.find(m.group("rest"))
        if shared_cargo or shared_when:
            body = body[:m.start()]
    body = _JOIN.sub(" to ", body)
    out = []
    segments = []
    for seg in _SPLIT.split(body):  # "A to B, 20 pallets, by Friday": the parts with no journey in them belong to the shipment before
        if seg and seg.strip() and segments and not _HOP.search(_JOIN.sub(" to ", seg)):
            segments[-1] += " " + seg.strip()
        elif seg and seg.strip():
            segments.append(seg)
    for seg in segments:
        seg = re.sub(r"\b(etc|and so on|please|thanks?)\b\.?", "", seg or "", flags=re.I).strip(" .,-")
        when, span = timing.find(seg)
        seg = _cut(seg, span)
        cargo, span = cargo_of(seg)
        seg = _cut(seg, span)
        seg = re.sub(r"\b(?:with|carrying|of|and|,)\s*$", "", seg).strip(" .,-")
        if cargo:
            cargo["weight_kg"] = None
        main, *via = _VIA.split(seg, maxsplit=1)  # "A to B via X" calls at X before B
        hops = _HOP.split(main)
        if via:
            hops = hops[:-1] + _HOP.split(via[0]) + hops[-1:]
        names = [re.sub(r"^(?:\d+[.)]\s*)?(?:a |one |another )?(?:new )?(?:shipment |load )?(?:going |running )?(?:from )?", "", n.strip(), flags=re.I).strip()
                 for n in hops]
        names = [n for n in names if n]
        if len(names) < 2:
            continue
        stops, unresolved = [], []
        for n in names:
            p = resolve(n, places)
            if p is None:
                unresolved.append(n)
            elif not stops or stops[-1]["name"] != p["name"]:
                stops.append(p)
        out.append({"text": seg, "stops": stops, "unresolved": unresolved, "cargo": cargo, "names": names, "when": when})
    for item in out:
        if item["cargo"] is None and shared_cargo:
            item["cargo"] = {**shared_cargo, "weight_kg": None}
        item["when"] = item["when"] or shared_when
    return out


def _same_lane(stops: list[dict], ships: list[dict]) -> list[dict]:
    """Current shipments that call near this shipment's first stop and, later, near its last."""
    a, b = [stops[0]["lat"], stops[0]["lon"]], [stops[-1]["lat"], stops[-1]["lon"]]
    out = []
    for s in ships:
        calls = ([[s["legs"][0]["from_lat"], s["legs"][0]["from_lon"]]] + [[l["to_lat"], l["to_lon"]] for l in s["legs"]]) if s["legs"] else []
        first = next((i for i, c in enumerate(calls) if data._km(c, a) <= 30), None)
        if first is not None and any(data._km(c, b) <= 30 for c in calls[first + 1:]):
            out.append({"shipment_id": s["shipment_id"], "origin": s["origin"], "destination": s["destination"],
                        "cargo": s["cargo"], "departs": s["legs"][0]["planned_start"], "risk_level": s["risk"]["level"]})
    return out


def from_request(shipments: list[dict], places: list[dict]) -> list[dict]:
    """Shipments already split into stop names and cargo (by the request reader): match each name to a place."""
    out = []
    for s in shipments:
        stops, unresolved = [], []
        for n in s.get("stops") or []:
            p = resolve(n, places)
            if p is None:
                unresolved.append(n)
            elif not stops or stops[-1]["name"] != p["name"]:
                stops.append(p)
        cargo = s.get("cargo")
        when = s.get("when") if isinstance(s.get("when"), dict) and s["when"].get("kind") in timing.KINDS else None
        out.append({"text": " to ".join(s.get("stops") or []), "stops": stops, "unresolved": unresolved, "names": list(s.get("stops") or []),
                    "cargo": {"units": cargo["units"], "unit_type": cargo["unit_type"], "weight_kg": None} if cargo else None,
                    "when": {"kind": when["kind"], "text": str(when.get("text") or "")} if when else None})
    return out


def apply_details(shipments: list[dict], details: list[dict]) -> list[dict]:
    """Fill in cargo and timing from a details reply. A detail with a ref goes to that shipment; one without goes
    to every shipment still missing that detail."""
    out = [dict(s) for s in shipments]
    for d in details or []:
        m = re.fullmatch(r"NEW-(\d+)", str(d.get("ref") or ""), re.I)
        targets = [out[int(m.group(1)) - 1]] if m and 0 < int(m.group(1)) <= len(out) else ([] if m else out)
        for t in targets:
            if d.get("cargo") and (m or not t.get("cargo")):
                t["cargo"] = d["cargo"]
            if d.get("when") and (m or not t.get("when")):
                t["when"] = d["when"]
    return out


NOT_BY_AIR = {"container_20", "container_40", "reefer", "trailer", "tonne"}
NEED = {"cargo": "what it carries and how much (for example 20 pallets, 4 reefers or 2 trailers)",
        "when": "when it should happen (for example arrive by Friday 17:00, leave tomorrow 08:00, as soon as possible, or no deadline)"}


def plan(text: str, preferences: dict | None = None, own_places: list[dict] | None = None, shipments: list[dict] | None = None,
         details: list[dict] | None = None) -> dict:
    """Plans for the shipments in a message (or already split in `shipments`, with `details` filling gaps). A shipment
    is only planned once it has its stops, its cargo and its timing; what is missing is listed so the chat can ask."""
    places = [p for p in (own_places or []) if p.get("name") and p.get("kind") in planner.CHANGE_HOURS] + planner.PLACES
    parsed = from_request(apply_details(shipments, details), places) if shipments else parse(text, places)
    ships = data.shipments()
    now = data._now()
    n_events = len(data._rows("disruption_events"))
    shipments, n_routes, own = [], 0, False
    for i, item in enumerate(parsed, 1):
        when = timing.resolve(item["when"], now)
        cargo = item["cargo"]
        missing = (["cargo"] if cargo is None else []) + (["when"] if when is None or when["problem"] else [])
        row = {"ref": f"NEW-{i}", "text": item["text"], "stops": item["stops"], "unresolved": item["unresolved"],
               "cargo": planner.clean_cargo(cargo) if cargo else None, "when": when, "missing": missing,
               "request": {"stops": item["names"], "cargo": {"units": cargo["units"], "unit_type": cargo["unit_type"]} if cargo else None,
                           "when": item["when"]},
               "routes": [], "recommended_id": None, "same_lane": [], "problem": None}
        if item["unresolved"]:
            row["problem"] = "I could not place " + ", ".join(f'"{n}"' for n in item["unresolved"]) + ". Use a known place or add it under My places."
        elif len(item["stops"]) < 2:
            row["problem"] = "A shipment needs two different places."
        elif not missing:
            arrive = when["at"] if when["kind"] == "arrive_by" else None
            res = planner.suggest(item["stops"], ["truck"] * (len(item["stops"]) - 1), when["at"] if when["kind"] == "depart_at" else None,
                                  preferences, own_places, cargo, arrive, "arrive" if arrive else "depart")
            if cargo["unit_type"] in NOT_BY_AIR:  # containers, trailers and bulk do not go in an aircraft hold
                res["routes"] = [r for r in res["routes"] if not any(l["mode"] == "plane" for l in r["legs"])] or res["routes"]
            for r in res["routes"]:  # why a route cannot meet the arrive-by date, if it cannot
                r["late"] = next((t for t in r["problems"] if t.startswith("Too late")), None) or next((v for v in r["violations"] if "arrive-by" in v), None)
            possible = [r for r in res["routes"] if not [t for t in r["problems"] if not t.startswith("Too late")]]  # can physically be done
            on_time = [r for r in possible if not r["late"]]
            row["routes"] = [r for r in res["routes"] if not r["problems"]] or possible or res["routes"]
            if on_time and any(r["id"] == res["recommended_id"] for r in on_time):
                row["recommended_id"] = res["recommended_id"]
            elif on_time:
                row["recommended_id"] = min(on_time, key=lambda r: (not r["within_limits"], r["cost"]))["id"]
            else:  # nothing makes the date: suggest the cheapest that can be done, and say it is late
                row["recommended_id"] = min(row["routes"], key=lambda r: r["cost"])["id"]
            row["cannot_meet_deadline"] = next(r for r in row["routes"] if r["id"] == row["recommended_id"])["late"]
            row["depart_at"] = res["depart_at"]
            row["same_lane"] = _same_lane(item["stops"], ships)
            n_routes += len(row["routes"])
            own = own or any(r["cost_basis"] != "default" for r in row["routes"])
        row["label"] = " → ".join(p["name"] for p in item["stops"]) or item["text"]
        shipments.append(row)
    needs = [{"ref": s["ref"], "label": s["label"], "missing": s["missing"],
              "problem": s["when"]["problem"] if s["when"] and s["when"]["problem"] else None} for s in shipments if not s["problem"] and s["missing"]]
    ok = [s for s in shipments if not s["problem"] and not s["missing"]]
    lanes = [f"{x['shipment_id']} already runs {s['stops'][0]['name']} to {s['stops'][-1]['name']}" for s in ok for x in s["same_lane"]]
    steps = [
        {"text": f"Read {len(shipments)} new shipment{'' if len(shipments) == 1 else 's'} from your message",
         "detail": "; ".join(s["label"] for s in shipments) or "none found"},
        {"text": f"Placed the stops on the map: {sum(len(s['stops']) for s in shipments)} matched to known places",
         "detail": "; ".join(s["problem"] for s in shipments if s["problem"]) or "every name matched a known place"},
        {"text": f"Built {n_routes} routes: by road, by sea and by air where each makes sense",
         "detail": "trucks take the ferry where there is water to cross; nothing is routed through a place that cannot handle the mode"},
        {"text": "Priced every leg from the rate tables",
         "detail": ("your own rates where they apply, illustrative defaults elsewhere" if own else "illustrative default rates")
                   + "; for the cargo and the timing you gave for each shipment"},
        {"text": f"Scored every route against today's {n_events} disruptions with the risk job", "detail": "the same deterministic rules the fleet is scored with"},
        {"text": f"Checked your {len(ships)} current shipments for the same lanes",
         "detail": ("; ".join(lanes) + ". PortShift has no vehicle capacity data, so it cannot say whether there is room on them."
                    if lanes else "none of them runs one of these lanes")},
        {"text": f"Plans ready for {len(ok)} shipment{'' if len(ok) == 1 else 's'}", "detail": "nothing is created until you approve"},
    ]
    return {"shipments": shipments, "steps": steps, "planned": len(ok), "currency": costing.CURRENCY, "needs": needs,
            "complete": not needs, "need_text": NEED,
            "note": "Suggested routes, not optimal ones, and estimates, not quotes. Approving records each plan as a tentative "
                    "planned shipment; nothing is booked and no carrier is contacted."}
