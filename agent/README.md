# agent/ (issue #17)

- `cost.py`: reschedule and reroute cost from `cost_rates` (formula, never an LLM).
- `plan.py`: per-shipment options (keep, reschedule, reroute) and `suggest_plan`, with the user's limits
  (`Preferences`: max risk level, max extra cost, max extra delay). Recommendation = cheapest option
  inside the limits; if none fits, the least-bad one, flagged. Detour distances are an illustrative table.
- `llm.py`: wording only. Databricks serving endpoint (`LLM_ENDPOINT` + `DATABRICKS_HOST` + `DATABRICKS_TOKEN`),
  a local Ollama model (`OLLAMA_MODEL`, optional `OLLAMA_HOST`), or `ANTHROPIC_API_KEY` (+ optional `LLM_MODEL`).
  `LLM_PROVIDER` forces one. No model configured: template text, so chat always works.
- `chat.py`: `answer(message, selected_ids, preferences=None)`; intents explain / cost / suggest a plan.
  Numbers and the option list are printed by code; LLM text containing a figure it was not given is rejected.
- `store.py`: rows from the same source as the app (fixtures or Databricks).

Try it: `python -c "from agent import chat; print(chat.answer('suggest routes, max risk 2', ['S-1002'])['text'])"`
Tests: `python -m pytest agent` (no network, no keys; the LLM client is tested against a local fake server).

## Live path (issue #17, second part)
- `linkup.py`: Linkup search and fetch (verified against docs.linkup.so; not yet run with a real key). Retries 429, rewords on empty results.
- `gazetteer.py`: known ports/airports/chokepoints; the monitor places events by name here and drops what it cannot place.
- `extract.py`: snippet -> event JSON with the base model (no coordinates, status, costs or risk from the model).
- `monitor.py`: `python -m agent.monitor` (needs `LINKUP_API_KEY` and an LLM). Cross-checks sources, writes events and evidence plus an `agent_runs` record.
- `sink.py`: Delta tables when `DATABRICKS_*` is set, else JSON files in `.portshift_live/`.
