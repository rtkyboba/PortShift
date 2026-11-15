"""Run check now: one monitor run on request, then show what changed.

The run is the agent's own (agent/monitor.py): search with Linkup, extract, place, cross-check, write events
and evidence, and a run record. Nothing here searches or extracts by itself, and nothing is invented: without
a Linkup key or a model the answer is "not run" with the reason.

Without Databricks the monitor writes to the live folder (data.live_dir()); data.py lays those events over the
demo fleet and re-runs the risk job, so a new event changes a shipment's colour on the next read.
"""
import data


def _agent():
    import sys
    root = str(data._here.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from agent import linkup, llm, monitor, sink
    return linkup, llm, monitor, sink


def status() -> dict:
    try:
        linkup, llm, monitor, _ = _agent()
    except Exception as err:
        return {"can_run": False, "reason": f"The agent package could not be loaded ({type(err).__name__}).", "corridors": []}
    reason = None
    if not linkup.available():
        reason = "LINKUP_API_KEY is not set on this server, so there is no live search. Nothing is invented in its place."
    elif not llm.available():
        reason = "No model is configured for extraction (LLM_ENDPOINT, OLLAMA_MODEL or ANTHROPIC_API_KEY)."
    return {"can_run": reason is None, "reason": reason, "corridors": [c["name"] for c in monitor.DEFAULT_CORRIDORS],
            "corridor_queries": {c["name"]: c["queries"] for c in monitor.DEFAULT_CORRIDORS},
            "writes_to": "Databricks Delta tables" if data.use_databricks() else "the live folder on this server"}


def _levels() -> dict:
    return {r["shipment_id"]: r["level"] for r in data._rows("shipment_risk")}


def run_check(corridor: str | None = None) -> dict:
    st = status()
    if not st["can_run"]:
        return {"ran": False, **st}
    _, _, monitor, sink = _agent()
    chosen = next((c for c in monitor.DEFAULT_CORRIDORS if c["name"] == corridor), monitor.DEFAULT_CORRIDORS[0])
    before = _levels()
    target = sink.default_sink() if data.use_databricks() else sink.JsonDirSink(data.live_dir())
    record = monitor.run_corridor_record(chosen, sink=target)
    data.forget_rescore()
    after = _levels()
    changed = [{"shipment_id": i, "from": before.get(i), "to": lvl} for i, lvl in sorted(after.items()) if before.get(i) != lvl]
    return {"ran": True, **st, "run": record, "changed": changed,
            "rescored": not data.use_databricks(),  # in Databricks the scheduled risk job rescores
            "note": "Events come from live search and carry their sources. The fleet is a demo fleet."}
