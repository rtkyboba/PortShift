import inspect
import pathlib
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import assets
import assistant
import briefing
import chat
import costing
import customers
import detour
import data
import fleet
import live
import newplan
import planner
import rates
import retrieve
import router
import stock
import whatif



def _load_env():
    """Keys live in the repo-root .env (AGENTS.md setup step 4). Read it once so a plain `uvicorn main:app`
    picks them up. Variables already set win. Not under pytest, where tests must stay on the fixtures."""
    import os
    import sys
    if "pytest" in sys.modules:
        return
    try:
        lines = (pathlib.Path(__file__).resolve().parent.parent / ".env").read_text().splitlines()
    except OSError:
        return
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env()
app = FastAPI(title="PortShift")


@app.middleware("http")
async def _forget_cached_reads_after_writes(request, call_next):
    """A write (any non-GET that succeeds) may change Delta tables: drop cached reads so the next read is fresh."""
    response = await call_next(request)
    if request.method not in ("GET", "HEAD", "OPTIONS") and response.status_code < 400:
        data.forget_rows()
    return response


class ChatIn(BaseModel):
    message: str
    selected_ids: list[str] = []
    preferences: dict | None = None  # the operator's limits, CONTRACTS.md section 5


class OptionsIn(BaseModel):
    shipment_id: str
    preferences: dict | None = None


class DecisionIn(BaseModel):
    shipment_id: str
    option: dict  # the chosen option as returned by /api/options
    preset: str | None = None


class RoutesIn(BaseModel):
    stops: list[dict]                 # each {name, kind: warehouse | port | airport, lat, lon}, in order
    modes: list[str] = []             # mode of each leg as drawn: truck | ship | plane (default truck)
    depart_at: str | None = None      # ISO time; default two hours from now (planning backwards: the earliest it may leave)
    arrive_by: str | None = None      # ISO time the cargo must arrive by, optional
    plan_from: str = "depart"         # depart | arrive (plan backwards from arrive_by)
    preferences: dict | None = None
    places: list[dict] = []           # the operator's own places, so suggestions can route through them
    cargo: dict | None = None         # {units, unit_type, weight_kg}; default 20 pallets


class PlanAllIn(BaseModel):
    preferences: dict | None = None
    goal: str = "balanced"            # balanced | low_cost | low_risk
    max_total_cost: float | None = None  # an optional budget for the whole fleet


class DispatchPlanIn(BaseModel):
    warehouse: str
    stops: list[dict]                 # where the stock goes, in order: places as in /api/places
    lines: list[dict]                 # [{stock_id, quantity}]
    preferences: dict | None = None
    depart_at: str | None = None
    places: list[dict] = []


class DispatchIn(BaseModel):
    warehouse: str
    lines: list[dict]
    route: dict                       # the chosen route from /api/dispatch/plan
    stops: list[str] = []


class AssistantIn(BaseModel):
    message: str
    history: list[dict] = []          # the last turns, each {role: user | assistant, text}
    selected: str | None = None       # the shipment open in the app, if any
    known_in_scope: bool = False      # the request reader already judged it in scope


class RouteIn(BaseModel):
    message: str
    expecting: str | None = None      # "shipment_details" while the chat waits for cargo or timing


class PlanNewIn(BaseModel):
    shipments: list[dict] = []        # already split: [{stops: [names], cargo, when}], as returned in each row's "request"
    details: list[dict] = []          # a details reply to fill gaps: [{ref, cargo, when}]
    message: str
    preferences: dict | None = None
    places: list[dict] = []           # the operator's own places


class PlannedIn(BaseModel):
    plans: list[dict]                 # each {ref, label, cargo, route}: a route as returned by /api/plan-new


class CheckIn(BaseModel):
    corridor: str | None = None


class MyRatesIn(BaseModel):
    rate_cards: list[dict] = []
    delay_charges: list[dict] = []
    surcharges: list[dict] = []


# Submitted choices. Held in this process only for now: tentative, nothing is booked or sent anywhere.
# A Delta table for these needs a CONTRACTS.md change first.
DECISIONS: list[dict] = []


@app.post("/api/options")
def api_options(body: OptionsIn):
    out = data.options(body.shipment_id, body.preferences)
    if not out:
        raise HTTPException(404)
    return out


@app.post("/api/options/routes")
def api_option_routes(body: OptionsIn):
    """What to draw on the map for each option of a shipment. Reroute lines are indicative."""
    out = detour.routes(body.shipment_id, body.preferences)
    if not out:
        raise HTTPException(404)
    return out


@app.get("/api/rates")
def api_rates(refresh: bool = False):
    """Reported market freight rates with a source per line (live Linkup search, else flagged samples)."""
    return rates.market_rates(refresh)


@app.get("/api/places")
def api_places():
    return planner.PLACES


@app.post("/api/routes")
def api_routes(body: RoutesIn):
    """Suggested routes through the stops. Estimates only; nothing is booked and no shipment is created."""
    stops = body.stops
    if len(stops) < 2 or len(stops) > 8:
        raise HTTPException(422, "Give between two and eight stops.")
    for p in stops + body.places:
        if not (isinstance(p.get("name"), str) and p.get("kind") in planner.CHANGE_HOURS
                and isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lon"), (int, float))):
            raise HTTPException(422, "Each place needs a name, a kind (warehouse, port or airport), lat and lon.")
    modes = [m if m in planner.SPEED_KMH else "truck" for m in body.modes][:len(stops) - 1]
    modes += ["truck"] * (len(stops) - 1 - len(modes))
    if body.plan_from == "arrive" and not body.arrive_by:
        raise HTTPException(422, "Planning backwards needs an arrive-by date.")
    return planner.suggest(stops, modes, body.depart_at, body.preferences, body.places, body.cargo, body.arrive_by, body.plan_from)


class WhatIfIn(BaseModel):
    message: str
    preferences: dict | None = None


@app.post("/api/whatif")
def api_whatif(body: WhatIfIn):
    """A hypothetical disruption run against the fleet: new levels, costs and a suggested plan. Nothing is saved."""
    try:
        return whatif.run(body.message, body.preferences)
    except ValueError as err:
        raise HTTPException(422, str(err))


@app.post("/api/briefing")
def api_briefing(body: PlanAllIn):
    """What the agent found and proposes, step by step, counted from the tables as they are now."""
    return briefing.build(body.preferences)


class FleetLegsIn(BaseModel):
    legs: list[dict]                  # the legs of a route from /api/routes
    cargo: dict | None = None
    needs: dict | None = None         # {reefer, adr}
    picks: dict = {}                  # reserve only: {leg seq: asset_id}
    label: str = ""


@app.get("/api/fleet")
def api_fleet():
    """The operator's vehicles and booked capacity, each with its status worked out from the bookings."""
    return assets.view()


@app.post("/api/fleet")
def api_fleet_add(body: dict):
    try:
        assets.add(body)
    except ValueError as err:
        raise HTTPException(422, str(err))
    return assets.view()


@app.put("/api/fleet/{asset_id}")
def api_fleet_update(asset_id: str, body: dict):
    try:
        assets.update(asset_id, body)
    except KeyError:
        raise HTTPException(404, "No such vehicle or booked capacity.")
    except ValueError as err:
        raise HTTPException(422, str(err))
    return assets.view()


@app.delete("/api/fleet/{asset_id}")
def api_fleet_remove(asset_id: str):
    if not assets.remove(asset_id):
        raise HTTPException(404, "No such vehicle or booked capacity.")
    return assets.view()


def _fleet_legs(legs: list[dict]) -> None:
    need = ("seq", "mode", "from_name", "to_name", "from_lat", "from_lon", "planned_start", "planned_end", "km", "hours")
    if not legs or any(not isinstance(l, dict) or any(k not in l for k in need) for l in legs):
        raise HTTPException(422, "Send the legs of a route as /api/routes returned them.")


@app.post("/api/fleet/candidates")
def api_fleet_candidates(body: FleetLegsIn):
    """For each leg of a route: which of the operator's vehicles and booked space can carry it, and why not."""
    _fleet_legs(body.legs)
    return assets.candidates(body.legs, body.cargo, body.needs)


@app.post("/api/fleet/reserve")
def api_fleet_reserve(body: FleetLegsIn):
    """Hold the chosen vehicles and space for these legs. 409 when one is no longer free."""
    _fleet_legs(body.legs)
    try:
        return assets.reserve(body.label, body.legs, body.picks, body.cargo, body.needs)
    except ValueError as err:
        raise HTTPException(409, str(err))


@app.delete("/api/fleet/bookings/{booking_ref}")
def api_fleet_release(booking_ref: str):
    if not assets.release(booking_ref):
        raise HTTPException(404, "No such booking.")
    return assets.view()


class CustomerSiteIn(BaseModel):
    name: str
    lat: float
    lon: float
    customer: str = ""
    note: str = ""


@app.get("/api/customers")
def api_customers():
    """Customer sites the operator delivers to: samples plus the ones they added."""
    return customers.sites()


@app.post("/api/customers")
def api_add_customer(body: CustomerSiteIn):
    try:
        return customers.add(body.name, body.lat, body.lon, body.customer, body.note)
    except ValueError as err:
        raise HTTPException(422, str(err))


@app.delete("/api/customers/{name}")
def api_remove_customer(name: str):
    if not customers.remove(name):
        raise HTTPException(404, "No customer site you added has that name (sample sites cannot be removed).")
    return customers.sites()


@app.get("/api/my-rates")
def api_my_rates():
    """The operator's own rate cards, delay terms and surcharges, with the defaults they replace."""
    return costing.view(data._now())


@app.put("/api/my-rates")
def api_save_my_rates(body: MyRatesIn):
    try:
        costing.save_operator(body.model_dump())
        retrieve.forget()  # the rates changed
    except ValueError as err:
        raise HTTPException(422, str(err))
    return costing.view(data._now())


@app.get("/api/decisions")
def api_decisions():
    return DECISIONS


@app.post("/api/decisions")
def api_decide(body: DecisionIn):
    if not data.shipment_detail(body.shipment_id):
        raise HTTPException(404)
    o = body.option
    row = {"decision_id": f"D-{len(DECISIONS) + 1}", "shipment_id": body.shipment_id, "status": "tentative",
           "option_id": o.get("id"), "kind": o.get("kind"), "label": o.get("label"), "extra_cost": o.get("extra_cost"),
           "cost_lines": o.get("cost_lines") or [], "cost_note": o.get("cost_note"),
           "delay_hours": o.get("delay_hours"), "resulting_risk": o.get("resulting_risk"), "preset": body.preset,
           "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    DECISIONS.append(row)
    return row


@app.get("/api/source")
def api_source():
    return {"source": data.source()}


@app.get("/api/shipments")
def api_shipments():
    return data.shipments()


@app.get("/api/shipments/{sid}")
def api_shipment(sid: str):
    d = data.shipment_detail(sid)
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/summary")
def api_summary():
    return data.summary()


@app.get("/api/events")
def api_events():
    return data.events()


@app.post("/api/plan-all")
def api_plan_all(body: PlanAllIn):
    """The agent plans every affected shipment and returns one proposal for approval. Nothing is written."""
    return fleet.plan_all(body.preferences, body.goal, body.max_total_cost)


# Planned shipments the operator approved. Held in this process only, like DECISIONS: tentative, nothing is booked.
PLANNED: list[dict] = []


@app.get("/api/stock")
def api_stock():
    """What each warehouse holds and what is still available, with the dispatch orders so far."""
    return stock.view()


@app.post("/api/dispatch/plan")
def api_dispatch_plan(body: DispatchPlanIn):
    """Routes for sending the chosen stock. Checks the allocation against availability. Nothing is recorded."""
    for p in body.stops:
        if not (isinstance(p.get("name"), str) and p.get("kind") in planner.CHANGE_HOURS
                and isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lon"), (int, float))):
            raise HTTPException(422, "Each stop needs a name, a kind (warehouse, port or airport), lat and lon.")
    return stock.plan(body.warehouse, body.stops, body.lines, body.preferences, body.depart_at, body.places)


@app.post("/api/dispatch")
def api_dispatch(body: DispatchIn):
    """Submit the dispatch order to the warehouse: record it and take the stock out of what is available."""
    try:
        order = stock.submit(body.warehouse, body.lines, body.route, body.stops)
    except ValueError as err:
        raise HTTPException(409, str(err))
    retrieve.forget()  # the stock and the orders changed
    units = sum(l["quantity"] for l in order["lines"])  # a dispatch is a planned shipment too
    unit = order["lines"][0]["unit"] if order["lines"] else "pallet"
    planned = _add_planned({"label": f"{order['warehouse']} → {order['destination']}", "order_id": order["order_id"],
                            "cargo": {"units": units, "unit_type": unit, "weight_kg": None}, "route": body.route}, "dispatch")
    return {**order, "planned": planned}


@app.post("/api/assistant")
def api_assistant(body: AssistantIn):
    """Ask PortShifter: a conversational answer from the tables, or the fixed out-of-scope reply."""
    return assistant.answer(body.message, body.history, body.selected, body.known_in_scope, PLANNED)


@app.post("/api/route")
def api_route(body: RouteIn):
    """How Ask PortShifter read a message: the structured request, and whether the fine-tuned reader or the
    fixed patterns produced it."""
    return router.read(body.message, body.expecting)


@app.post("/api/plan-new")
def api_plan_new(body: PlanNewIn):
    """New shipments described in a sentence, each with suggested routes. Nothing is created."""
    return newplan.plan(body.message, body.preferences, body.places, body.shipments, body.details)


@app.get("/api/planned")
def api_planned():
    return PLANNED


def _add_planned(plan: dict, source: str) -> dict:
    """Record one approved plan as a planned shipment (tentative: nothing is booked)."""
    route = plan.get("route") or {}
    if not route.get("legs"):
        raise HTTPException(422, "Each plan needs a route with legs.")
    row = {"plan_id": f"P-{len(PLANNED) + 1}", "status": "tentative", "label": str(plan.get("label") or "")[:200],
           "route_label": route.get("label"), "cargo": plan.get("cargo"), "legs": route["legs"], "km": route.get("km"),
           "hours": route.get("hours"), "cost": route.get("cost"), "cost_note": route.get("cost_note"),
           "currency": route.get("currency"), "eta": route.get("eta"), "risk": route.get("risk"),
           "depart_at": route.get("depart_at"), "arrive_by": route.get("arrive_by"), "slack_hours": route.get("slack_hours"),
           "when": plan.get("when"), "source": source, "order_id": plan.get("order_id"),
           "approved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    PLANNED.append(row)
    return row


@app.post("/api/planned")
def api_add_planned(body: PlannedIn):
    """Every way of planning ends here: Ask PortShifter approvals (source "assistant", the default) and routes
    kept from Plan a shipment (source "planner"). Warehouse dispatches are added by /api/dispatch itself."""
    return [_add_planned(plan, plan.get("source") if plan.get("source") in ("assistant", "planner") else "assistant")
            for plan in body.plans]


@app.get("/api/check")
def api_check_status():
    """Whether a live check can run here, and which corridors there are."""
    return live.status()


@app.post("/api/check")
def api_check(body: CheckIn):
    """Run the monitor on one corridor now. Returns the run record and the shipments whose level changed."""
    out = live.run_check(body.corridor)
    retrieve.forget()  # new events: Ask PortShifter must retrieve from the tables as they are now
    return out


@app.get("/api/runs")
def api_runs():
    return data.agent_runs()


@app.get("/api/scenarios")
def api_scenarios():
    return data.scenarios()


@app.post("/api/chat")
def api_chat(body: ChatIn):
    # Limits are passed on only when the chat module accepts them (agent.chat does).
    if body.preferences and "preferences" in inspect.signature(chat.answer).parameters:
        return chat.answer(body.message, body.selected_ids, body.preferences)
    return chat.answer(body.message, body.selected_ids)


app.mount("/", StaticFiles(directory=pathlib.Path(__file__).parent / "static", html=True))
