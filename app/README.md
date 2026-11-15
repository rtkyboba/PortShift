# PortShift app

FastAPI + vanilla JS + Leaflet. Runs as a Databricks App (`app.yaml`) and locally.

    cd app && pip install -r requirements.txt && uvicorn main:app --port 8000

Data: `data.py` only. Field names and shapes are CONTRACTS.md section 3. Without keys it reads
`../demo/fixtures/*.json`; when `DATABRICKS_HOST`, `DATABRICKS_TOKEN` and `DATABRICKS_WAREHOUSE_ID`
are set it reads the Delta tables (`DATABRICKS_CATALOG`.`DATABRICKS_SCHEMA`, default `main.portshift`;
create and load them with `pipelines/load_fixtures.py`). `GET /api/source` says which is active.
The app displays risk levels from `shipment_risk`; it never computes them, and it flags a Severe/Critical
level whose linked events are all suspected. Events show their evidence basis (status, domains, official
source), never a made-up confidence number.
Costs: `costing.py` looks rates up in `rate_cards`, `surcharges`, `delay_charges` and `shipment_terms` and returns
the arithmetic with every figure (`cost_lines`). The operator's own rates (`GET`/`PUT /api/my-rates`, the My rates
view) win where one applies; defaults are illustrative. They are kept in `.portshift_live/my_rates.json` on the
server (`PORTSHIFT_STATE` to move it), not yet in Delta.
Plan the fleet: `fleet.py`, `POST /api/plan-all`. The operator says "optimise everything for the least cost" (the
agent card on the map, or any Ask agent chat); the agent works through every affected shipment and returns one
proposal with what it did. Nothing is recorded until the operator approves the changes they ticked.
Ask PortShifter: a floating chat window (drag it by its header, hide and show it with the button; `static/app.js`),
in every view. Jobs that end in an approval panel are matched in the browser: plan the whole fleet (`fleet.py`),
plan new shipments from a sentence (`newplan.py`, `POST /api/plan-new`, `POST /api/planned`), run a live check
(`live.py`). Everything else goes to `POST /api/assistant` (`assistant.py`): a fixed scope check first (off-topic
questions get one fixed reply and never reach a model), then answers straight from the tables, then a model when
one is configured (`agent/llm.py`), given a snapshot of the tables and told to answer only from it; a reply with a
figure that is not in the snapshot is dropped. Local model: `ollama pull qwen3.5:9b`, then
`OLLAMA_MODEL=qwen3.5:9b OLLAMA_REASONING_EFFORT=none` (a larger context helps: an Ollama Modelfile with
`PARAMETER num_ctx 8192`). Deep link: `?bot=<message>` (add `&confirm=1` to say yes). Prompt-injection tests: issue #63.
Warehouse stock: `stock.py`, used from Plan a shipment ("What's going: Warehouse stock"): the warehouse is stop 1, the chosen
pallets and their weight are the cargo for `POST /api/routes`, and the picked route is submitted to the warehouse. `GET /api/stock` (what each warehouse holds and what
is still available), `POST /api/dispatch/plan` (checks an allocation, returns routes for the real cargo; kept for the API, the UI uses `/api/routes`),
`POST /api/dispatch` (records the order and its lines for the warehouse; 409 when the stock is no longer there).
Tables `warehouse_stock`, `dispatch_orders`, `dispatch_lines`; orders go to Delta when Databricks is configured,
else they are held in the process. The stock rows are samples standing in for a stockpile manager's feed.
Deep link: `?tab=stk&from=Glasgow warehouse&send=ST-001:20&to=London warehouse (Hayes)` (opens Plan a shipment with stock; `to` takes `A>B` for several stops).
Plan a shipment timing: *How urgent?* is Fastest (earliest arrival within the risk limit), By a date (late routes are
marked and cannot be picked; send as soon as possible or just in time, which plans backwards) or No deadline.
`POST /api/routes` takes `arrive_by` and `plan_from` (`depart` | `arrive`); each route returns `depart_at`, `eta` and,
with a date, `slack_hours` (negative = late).
Reroutes: `reroute.py`. `data.options` keeps keep and reschedule from `agent.plan` and replaces its table-driven
reroute with a search: for the stretch the disruption touches it tries other ferry crossings (every safe pair of ports),
another port or airport in place of the disrupted one, the stops joined directly, the road round either side, and the
Cape for a Suez closure. Each is timed with the same model as the stretch it replaces (so the change can be negative),
scored by `pipelines/risk_job.py`, and dropped unless it is safer than the plan. `no_reroute` says why when none is
offered. A truck crossing is only offered on a route in `reroute.FERRY_ROUTES` (Dover to Dunkirk, Harwich to Hook of Holland,
Tilbury to Zeebrugge and so on; from general knowledge, to be checked against timetables). The road part is priced by
its change in distance; each new ferry is a fare from the sea rate table and the planned crossing it replaces is a credit.
Options on the map: `detour.py`, `POST /api/options/routes`. For each option of a shipment, what to draw and the arrival
it leads to. A reroute in `agent.plan` is a label and two numbers, so its line is **indicative**: the legs the disruption
touches are replaced by a path through the place the option names, or round the edge of the area. With the Options tab
open the map shows only that shipment, its disruption and the options; hover a line for cost and arrival, click to pick.
Map key: every entry has a tick box that hides that kind of mark (kept per browser in `portshift.mapshow`).
What if: `whatif.py`, `POST /api/whatif {message}`. A sentence ("What if Dover closes tomorrow for 3 days?") becomes a
hypothetical event (place, kind, window read by rules; a model is asked only when the rules cannot place it, and its
place must be a known one). `data.supposing()` adds it for that request only, through a context variable: the same risk
job, costing and fleet planner run with it, and nothing is written. The app shows the fleet as it would be, with a
purple *hypothetical* frame, and a panel of what changes and what the planner would do. Ask PortShifter "what if …",
or `?whatif=<question>`.
Briefing: `briefing.py`, `POST /api/briefing`. What the agent found and proposes, step by step (search, cross-check,
score, plan, fleet), counted from the tables; ends on *Review and approve the plan*. Top bar *Briefing*, "Brief me",
or `?briefing`.
Fleet: `assets.py` and the Fleet view. Vehicles (trucks, or a ship or plane the operator runs) and booked capacity
(sea allocations, air allotments on a lane). Status is worked out from the bookings: Available, Allocated, In transit,
Off road (set by hand). `GET/POST /api/fleet`, `PUT/DELETE /api/fleet/{id}`, `POST /api/fleet/candidates` (for each leg
of a route: which records fit and are free, nearest depot first, and why the others cannot), `POST /api/fleet/reserve`
(409 when one is no longer free), `DELETE /api/fleet/bookings/{ref}`. In Plan a shipment the picked route gets a
*Your fleet for this route* section: choose per leg or Auto-assign (greedy), see the cost with your own vehicles, reserve.
Sample fleet (10 trucks, 5 booked lanes) marked *demo fleet*; records and bookings are kept in files in `PORTSHIFT_STATE`.
Customer sites: `customers.py`. `GET /api/customers` (sample sites plus the operator's own), `POST /api/customers`
(name, lat, lon, optional customer), `DELETE /api/customers/{name}` (own sites only). Kept in `customer_sites.json` in
`PORTSHIFT_STATE`, like My rates. Places of kind `customer`, reached by truck. Shown on the live map (click one to plan a
delivery there) and added by dragging *Customer site* onto the map in Plan a shipment. The map key (top right) lists
every mark on the map; it collapses and remembers that per browser.
Request reader: `router.py`, `POST /api/route`. Every chat message is read once into a structured request
(`reader_prompt.py` holds the format): by the fine-tuned reader in `finetune/router/` when `ROUTER_ENDPOINT` points at
it (for example `python finetune/serve_local.py --adapter finetune/router/checkpoints/v2/best --port 8092`, then
`ROUTER_ENDPOINT=http://127.0.0.1:8092/v1/chat/completions`). The fixed patterns always decide what a message is; the
fine-tune is used for the part it is better at on held-out wording, splitting a new-shipments message into shipments
and stops (`finetune/RESULTS.md`), and its reply is used only if every place, figure and date word in it appears in the
message. New shipments need stops, cargo and timing
(`when.py` reads "arrive by Friday 17:00", "leave tomorrow 08:00", "as soon as possible", "no deadline"); the chat asks
for whatever is missing, and asks again, before `newplan.py` plans anything. Deep link: `?bot=<message>&then=<reply>`.
Retrieval (RAG): `retrieve.py`. Every table becomes small records (shipments, disruptions, the sources cited for
them, stock lines, dispatch orders, planned shipments, rates, reported market rates). For a question that the fixed
rules do not answer exactly, `search()` ranks the records two ways and fuses the two lists (reciprocal rank
fusion): BM25 over words, with a boost for a named id, place or carrier, and embeddings (`embeddings.py`, cosine
similarity), so "booze" finds whisky. It then follows links (a shipment's disruptions, a disruption's sources), and the
model is given the fleet summary plus those numbered records only; the sources among them are returned as the answer's
citations and the chat lists the records used and the method. Embeddings come from `EMBED_ENDPOINT` (a Databricks
embedding endpoint, with `DATABRICKS_HOST` and `DATABRICKS_TOKEN`) or `OLLAMA_EMBED_MODEL` (local:
`ollama pull nomic-embed-text`); with neither, retrieval is BM25 alone. Vectors are kept in memory; there is no vector
store. With no chat model configured the closest records are the answer.
`understand.py` puts typing slips, shorthand and loose shipment numbers right before anything reads a message.
Live check: `live.py`, `POST /api/check` runs the agent's monitor on one corridor (needs `LINKUP_API_KEY` and a
model; says so when they are missing). Without Databricks the events land in `.portshift_live/`
(`PORTSHIFT_LIVE_DIR`), are laid over the demo fleet, and the risk job is re-run so levels change.
Sample events: by default live events are shown with the sample ones (each sample marked). `PORTSHIFT_SAMPLE_EVENTS=hide`
leaves the samples out once a live event with a source exists, and scores the fleet on the live ones only; the top bar
then reads *Live sources*. Today's real events may touch few demo shipments, so check the map before a demo.
Keys: `main.py` reads the repo-root `.env` at start.
Chat: `chat.py` `answer()`. Styling: CSS variables at the top of `static/app.css`.
Tests: `cd app && python -m pytest -q`.
