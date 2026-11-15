# CONTRACTS: PortShift

Change this file only through a PR, and post on the board when it changes. Table shapes follow the sample rows in `demo/fixtures/*.json`, which match this file exactly. Build against the fixtures until the real upstream lands.

Timestamps are ISO 8601 UTC strings. Coordinates are WGS84 decimal degrees. Money is in `currency` (EUR for the demo), always an estimate.

## 1. Enums

| Name | Values |
|---|---|
| `mode` | `ship`, `truck`, `plane` |
| `event.type` | `strike`, `closure`, `weather`, `warning`, `congestion`, `other` |
| `event.status` | `suspected`, `confirmed` |
| `scenario.status` | `tentative` (only value for now) |
| `scenario_change.change_type` | `reschedule`, `reroute` |
| risk `level` | 1 Clear, 2 Watch, 3 At risk, 4 Severe, 5 Critical (rules in `AGENTS.md`) |

**Confirmed** means two evidence rows with different `domain` for the same event, or one evidence row with `is_official = true`. Otherwise **suspected**. The monitor sets `status`; nothing else may change it.

## 2. Citation object

Used in `evidence` rows, chat answers and the app's citations panel.

```json
{"claim": "str", "url": "str", "title": "str", "retrieved_at": "ts", "published_at": "ts|null"}
```

No citation, no display. `url` comes from a Linkup result, never invented. Fixture URLs use the reserved `.invalid` TLD and `claim` starts with `SAMPLE:`.

## 3. Tables (Delta; same names and fields in `demo/fixtures`)

**`shipments`**: `shipment_id` (PK), `cargo`, `origin`, `destination`, `mode` (main mode), `eta`, `is_demo_fleet` (always true; the UI says "demo fleet").

**`legs`**: `shipment_id`, `seq` (1-based, PK with shipment_id), `mode`, `from_name`, `from_lat`, `from_lon`, `to_name`, `to_lat`, `to_lon`, `geometry` (array of `[lat, lon]`, at least from and to), `planned_start`, `planned_end`.

**`disruption_events`**: `event_id` (PK), `type`, `status`, `location` (place name), `lat`, `lon`, `radius_km` (area of effect), `window_start`, `window_end`, `summary` (one sentence, no money), `detected_at`, `is_fixture` (true unless produced by a live Linkup call; the UI shows a "sample" badge).

**`evidence`**: `evidence_id` (PK), `event_id` (FK), the citation object fields (`claim`, `url`, `title`, `retrieved_at`, `published_at`), `domain` (host of `url`), `is_official` (port authority, government or operator source).

**`shipment_risk`**: `shipment_id` (PK), `level` (1-5), `reason` (one sentence), `event_ids` (array). Written only by the risk job in `pipelines/`.

**`cost_rates`**: `mode` (PK), `per_delay_day`, `rebooking_fee`, `per_extra_km`, `currency`.

**`rate_cards`** (what a carrier charges; read by `app/costing.py`): `rate_id` (PK), `partner`, `mode`, `origin`, `destination`, `unit`, `base_rate`, `per_km`, `min_charge`, `currency`, `valid_from`, `valid_to`, `source`, `note`. The price of one unit is `base_rate + per_km x km`; `min_charge` is the least a leg costs. `unit` depends on the mode: `container_20`, `container_40`, `reefer` or `tonne` by ship; `km` (full truck) or `pallet` (part load) by truck; `kg` (chargeable weight, the greater of actual and volume x 167 kg) by plane. An empty `origin`, `destination`, `valid_from` or `valid_to` means any. `source` is `default` (illustrative) or `operator` (the operator's own rate, which wins where one applies).

**`surcharges`**: `code`, `mode` (the two together are the key), `label`, `partner`, `basis`, `value`, `applies_to_units`, `source`. `basis` is `percent_of_base`, `per_unit` or `flat`; an empty `applies_to_units` means every unit.

**`delay_charges`**: `mode`, `unit`, `partner` (the three together are the key; empty means any), `label`, `free_days`, `per_unit_per_day`, `rebooking_fee`, `source`. Waiting costs `units x per_unit_per_day x (days - free_days)` plus `rebooking_fee`.

**`shipment_terms`** (the commercial side of a demo shipment): `shipment_id` (PK), `carrier`, `units`, `unit_type`, `weight_kg`, `volume_m3`, `promised_by`, `late_penalty_per_day`. `weight_kg` and `volume_m3` are 0 when not given. A shipment delivered after `promised_by` costs `late_penalty_per_day` for each day or part of a day.

**`warehouse_stock`** (what is on hand at each warehouse; in production the stockpile manager supplies it): `stock_id` (PK), `warehouse`, `sku`, `item`, `quantity`, `unit`, `kg_per_unit`, `reserved`, `updated_at`, `is_sample`. `warehouse` is the name of a warehouse place the planner knows. `reserved` is what earlier dispatch orders have taken; available is `quantity - reserved`. `is_sample` is true for the demo rows and the UI shows a "sample stock" badge.

**`dispatch_orders`** (a shipment of stock, submitted to the warehouse that holds it): `order_id` (PK), `warehouse`, `destination`, `stops`, `route_label`, `status`, `submitted_at`, `depart_at`, `eta`, `cost`, `currency`, `is_sample`. `stops` is the ordered list of place names from the warehouse to the destination. `status` is `submitted`, then `acknowledged`, `picked` and `dispatched` as the warehouse works it. `cost` is the estimate from `app/costing.py`. Written by the app when the operator submits; nothing is sent to a carrier.

**`dispatch_lines`**: `order_id`, `stock_id` (the two together are the key), `sku`, `item`, `quantity`, `unit`. One row per stock line allocated to the order.

**`market_rates`** (reported freight rates, shown next to our own; never used in a cost formula): `rate_id` (PK), `topic` (`ocean-asia-europe`, `ocean-short-sea`, `air`, `road`), `mode`, then the citation fields `claim` (the source's own words), `url`, `title`, `retrieved_at`, `published_at`, plus `domain` and `is_fixture`. Live rows come from one Linkup search per topic (`app/rates.py`) and are not stored yet; the fixture file holds flagged samples. No model extracts or computes a figure from them.

**`agent_runs`** (written by the monitor, one row per corridor run; Delta DDL still to be added to `pipelines/tables.py`): `run_id` (PK), `corridor`, `started_at`, `finished_at`, `queries_run`, `results_seen`, `events_extracted`, `events_dropped`, `dropped_reasons` (array of text), `event_ids` (array), `needs_rescore` (bool), `error` (nullable), `steps_json` (JSON text: per query `{query, results, extracted, dropped[]}`).

**`scenarios`**: `scenario_id` (PK), `label`, `status`, `created_at`, `cost_delta`, `currency`.

**`scenario_changes`**: `scenario_id` (FK), `shipment_id`, `change_type`, `delay_days`, `new_planned_start`, `cost_delta`, `note`. `extra_km` is nullable: it is set for reroute changes and null for reschedules.

## 4. Event extractor (Adaption fine-tune, `EXTRACTOR_ENDPOINT`)

Input: one news snippet plus its metadata. Output: one JSON object, or `null` if the snippet describes no disruption. The model never outputs money, risk levels or `status`.

```json
{
  "type": "strike",
  "location": {"name": "Port of Rotterdam", "lat": 51.95, "lon": 4.14},
  "window": {"start": "2026-11-15T00:00:00Z", "end": "2026-11-18T00:00:00Z"},
  "summary": "Dock workers strike at Rotterdam terminals.",
  "source_url": "str",
  "published_at": "ts|null"
}
```

`window.end` may be `null` when unknown; the monitor then assumes start + 72 h. The monitor maps this to a `disruption_events` row (flattening `location` and `window`, setting `radius_km`, `detected_at`, `status`, `is_fixture = false`) plus an `evidence` row. The extractor must also work through the base model with the same prompt (`EXTRACTOR_USE_BASE=1`).

## 5. Agent interfaces (`agent/`)

```python
# linkup.py
search(query: str) -> list[dict]       # each: {title, url, snippet, published_at, retrieved_at, domain}
fetch(url: str) -> dict                # {url, title, text, retrieved_at}

# monitor.py   (python -m agent.monitor)
run_corridor(corridor: dict) -> list[str]   # corridor = {name, queries[]}; returns event_ids written
run_corridor_record(corridor: dict, ...) -> agent_runs row + "steps"   # what the run did, step by step
# Steps: search (Linkup, retries 429, rewords on empty) -> extract (base model) -> place (gazetteer; unknown
# places are dropped and counted) -> cross-check (same place + type + overlapping window = one event;
# confirmed = two independent domains or one official source) -> write disruption_events + evidence
# (is_fixture = false) + agent_runs. Rescoring is the risk job's work; the record sets needs_rescore.
# Writes to Delta when DATABRICKS_* is set, else fixture-shaped JSON files in .portshift_live/
# (run the app with PORTSHIFT_FIXTURES=.portshift_live).

# chat.py   (the app calls this; three intents only)
answer(message: str, selected_ids: list[str], preferences: dict | None = None) -> {
    "text": str, "citations": [citation], "intent": str, "preferences": preferences,
    "plan": plan_result | None, "llm_used": bool}
# intents: explain a shipment, cost to reschedule the selected shipment(s), suggest a plan
# (plus "set_limits" when the message only changes the limits). A shipment id in the message counts as selected.
# preferences = {"max_risk": 1-5, "max_extra_cost": EUR or null, "max_delay_hours": hours or null}
#   the user's limits on risk and price. Optional; limits can also be written in the sentence
#   ("suggest routes, max risk 2, under EUR 3000"). They persist for the running process.
#   Defaults: max_risk 3, max_extra_cost 5000, max_delay_hours null (no limit).

# cost.py
reschedule_cost(shipment_id: str, delay_days: int) -> {"cost": float, "currency": str, "breakdown": dict}
reroute_cost(shipment_id: str, extra_km: float) -> {"cost": float, "currency": str, "breakdown": dict}

# plan.py
options_for(shipment_id) -> {shipment, risk, reason, event, options[]}   # keep / reschedule / reroute
suggest_plan(shipment_ids: list[str] | None, prefs: Preferences | None) -> plan_result
# plan_result = {"scenario": scenarios row, "changes": [scenario_changes rows], "preferences",
#   "shipments": [{shipment_id, current_risk, event, options[], recommended_id,
#                  status: within_limits | no_action_needed | outside_limits}]}
# Each option: {id, kind, label, extra_cost, delay_hours, resulting_risk, within_limits, violations[]}.
# The recommendation is the cheapest option inside the limits; if none fits, the least-bad one, flagged
# outside_limits. suggest_plan returns the rows; writing them to Delta is the pipelines writer's job.

# llm.py   (wording only; numbers and sources always come from code)
available() -> bool;  complete(system: str, user: str) -> str | None
# Databricks serving endpoint (LLM_ENDPOINT + DATABRICKS_HOST/TOKEN) or ANTHROPIC_API_KEY. No key: template text.
```

Costs are formulas over `cost_rates` (`delay_days * per_delay_day + rebooking_fee`, `extra_km * per_extra_km`). The UI labels every figure "estimate, illustrative rates".

**App pricing.** `agent/cost.py` and the chat text keep the `cost_rates` formula above. The app prices every option and planned route it shows from `rate_cards`, `surcharges`, `delay_charges` and `shipment_terms` (`app/costing.py`), and returns the arithmetic with each figure: `cost_lines: [{label, formula, amount, rate_source: default | operator | shipment, partner, rate_id, note}]`, `cost_basis` and `cost_note` on every option of `POST /api/options`, every leg of `POST /api/routes` and every `wait_out`. Lookup order: the operator's own rate where one applies (their partner, their lane, valid on the day), else the default. The operator's rows are read and replaced through `GET` and `PUT /api/my-rates`; they are kept in a file on the app server for now and are not yet a Delta table. No model produces a figure; `market_rates` never price anything; one currency, no conversion.

## 6. App read path

The app reads through `app/data.py` only. It needs one reader per table returning rows exactly as in section 3 (`shipments`, `legs`, `disruption_events`, `evidence`, `shipment_risk`, `scenarios`, `scenario_changes`). The risk job and the scenario writer are the only writers of `shipment_risk` and `scenarios`/`scenario_changes`; the monitor is the only writer of `disruption_events` and `evidence`.

## 7. Fixtures

`demo/fixtures/*.json`: one file per table, an array of rows. Six demo shipments covering all five risk levels:

| Shipment | Level | Why |
|---|---|---|
| S-1001 | 4 | confirmed Suez closure on a later leg |
| S-1002 | 5 | confirmed Rotterdam strike on current leg |
| S-1003 | 1 | clear |
| S-1004 | 3 | confirmed strike near a stop within 72 h |
| S-1005 | 5 | confirmed Calais strike on next leg |
| S-1006 | 2 | suspected warning (E-4) more than 72 h before the shipment reaches it |

All events and evidence in the fixtures are samples (`is_fixture = true`, `.invalid` URLs). E-1 and E-3 are confirmed (two domains, or one official); E-2 is confirmed by an official source (so S-1001 is level 4: confirmed, later leg); E-4 is suspected (one domain).
