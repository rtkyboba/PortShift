"""Entry point for Databricks Jobs: load the SQL warehouse credentials, then run a pipelines script.

    job_entry.py DATABRICKS_CATALOG=workspace run_risk     # Databricks Job task (Python script)
    job_entry.py load_fixtures --tables shipments legs
    job_entry.py LLM_ENDPOINT=databricks-meta-llama-3-3-70b-instruct monitor --max-calls 12
    job_entry.py monitor --corridor "North Sea ports" --max-calls 3

monitor runs agent.monitor (Linkup search -> extract -> cross-check -> write events/evidence) with a hard
cap on Linkup calls per run (--max-calls, default 12), to protect search credits: once the cap is reached
every further call fails and the corridor records the error. --corridor (repeatable) limits the corridors.

Leading NAME=value arguments set environment variables (serverless job tasks cannot set them otherwise).

Inside Databricks there is no .env. DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_WAREHOUSE_ID come
from the secret scope named by PORTSHIFT_SECRET_SCOPE (default "portshift"; keys are the lower-case names);
LINKUP_API_KEY too when the scope has it.
Variables already set in the environment win, so the same command also works locally with .env loaded.
"""
import importlib
import os
import sys
from pathlib import Path

# Serverless job tasks exec() the script, so __file__ is not defined there; sys.argv[0] is the script path.
HERE = Path(globals().get("__file__") or sys.argv[0]).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))  # repo root, for the agent package

KEYS = ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID")
OPTIONAL_KEYS = ("LINKUP_API_KEY",)
SCRIPTS = ("run_risk", "load_fixtures", "monitor")
DEFAULT_MAX_CALLS = 12


def load_secrets(get_secret, scope: str, environ=os.environ) -> list[str]:
    """Fill missing KEYS from `get_secret(scope, key)`; returns the names it set."""
    filled = []
    for k in KEYS:
        if not environ.get(k):
            environ[k] = get_secret(scope, k.lower())
            filled.append(k)
    return filled


def load_optional(get_secret, scope: str, environ=os.environ) -> list[str]:
    """Like load_secrets for OPTIONAL_KEYS, but a key missing from the scope is skipped."""
    filled = []
    for k in OPTIONAL_KEYS:
        if not environ.get(k):
            try:
                environ[k] = get_secret(scope, k.lower())
                filled.append(k)
            except Exception:
                pass
    return filled


def cap_calls(module, max_calls: int) -> list:
    """Wrap module._post so at most max_calls requests go out; returns the list of calls made (grows)."""
    calls, real = [], module._post

    def capped(path, body, *args, **kwargs):
        if len(calls) >= max_calls:
            raise RuntimeError(f"Linkup budget of {max_calls} calls per run reached")
        calls.append(body.get("q") or body.get("url"))
        return real(path, body, *args, **kwargs)

    module._post = capped
    return calls


def run_monitor(argv, linkup=None, monitor=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="job_entry.py monitor")
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    ap.add_argument("--corridor", action="append", help="corridor name; repeat for several (default: all)")
    a = ap.parse_args(argv)
    if linkup is None or monitor is None:
        from agent import linkup, monitor  # noqa: F811
    if not linkup.available():
        print("LINKUP_API_KEY is not set: no live search.")
        return 2
    corridors = [c for c in monitor.DEFAULT_CORRIDORS if not a.corridor or c["name"] in a.corridor]
    if not corridors:
        print(f"no corridor named {a.corridor}")
        return 2
    calls = cap_calls(linkup, a.max_calls)
    records = monitor.run(corridors)
    for r in records:
        print(f"{r['corridor']}: {r['queries_run']} queries, {r['results_seen']} results, {r['events_extracted']} placed, "
              f"events {r['event_ids']}" + (f", ERROR {r['error']}" if r["error"] else ""))
    print(f"linkup calls: {len(calls)} of {a.max_calls}")
    return 0


def _dbutils_get(scope, key):
    from databricks.sdk.runtime import dbutils  # present on Databricks compute only
    return dbutils.secrets.get(scope=scope, key=key)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    while argv and "=" in argv[0] and argv[0].split("=", 1)[0].isupper():
        k, v = argv.pop(0).split("=", 1)
        os.environ[k] = v
    if not argv or argv[0] not in SCRIPTS:
        print(f"usage: job_entry.py {{{'|'.join(SCRIPTS)}}} [args...]")
        return 2
    script, rest = argv[0], argv[1:]
    if not all(os.environ.get(k) for k in KEYS):
        scope = os.environ.get("PORTSHIFT_SECRET_SCOPE", "portshift")
        load_secrets(_dbutils_get, scope)
        load_optional(_dbutils_get, scope)
    if script == "monitor":
        return run_monitor(rest)
    return importlib.import_module(script).main(rest)


if __name__ == "__main__":
    # Exit only on failure: the serverless runner reports even sys.exit(0) as a failed task.
    rc = main()
    if rc:
        sys.exit(rc)
