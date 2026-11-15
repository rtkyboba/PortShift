"""job_entry: secrets fill only what .env/the environment left empty; NAME=value args set env; bad script rejected."""
import job_entry


def test_missing_keys_are_filled_from_the_secret_scope():
    env, calls = {"DATABRICKS_HOST": "https://h"}, []

    def get(scope, key):
        calls.append((scope, key))
        return f"secret-{key}"

    filled = job_entry.load_secrets(get, "portshift", env)
    assert filled == ["DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"]
    assert env == {"DATABRICKS_HOST": "https://h", "DATABRICKS_TOKEN": "secret-databricks_token",
                   "DATABRICKS_WAREHOUSE_ID": "secret-databricks_warehouse_id"}
    assert calls == [("portshift", "databricks_token"), ("portshift", "databricks_warehouse_id")]


def test_unknown_script_is_rejected():
    assert job_entry.main(["rm_everything"]) == 2


def test_env_args_are_applied_before_running(monkeypatch):
    for k in job_entry.KEYS:
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("DATABRICKS_CATALOG", "before")  # recorded, so the value main() sets is undone after the test
    monkeypatch.delenv("DATABRICKS_CATALOG")
    seen = {}

    class Fake:
        @staticmethod
        def main(rest):
            import os
            seen["catalog"], seen["rest"] = os.environ.get("DATABRICKS_CATALOG"), rest
            return 0

    monkeypatch.setattr(job_entry.importlib, "import_module", lambda name: Fake)
    assert job_entry.main(["DATABRICKS_CATALOG=workspace", "run_risk", "--now", "2026-11-14T16:00:00Z"]) == 0
    assert seen == {"catalog": "workspace", "rest": ["--now", "2026-11-14T16:00:00Z"]}


class FakeLinkup:
    def __init__(self):
        self.sent = []

    def _post(self, path, body, timeout=30.0):
        self.sent.append(body["q"])
        return {"results": []}

    @staticmethod
    def available():
        return True


def test_cap_calls_stops_requests_after_the_budget():
    lk = FakeLinkup()
    calls = job_entry.cap_calls(lk, 2)
    lk._post("/v1/search", {"q": "a"})
    lk._post("/v1/search", {"q": "b"})
    try:
        lk._post("/v1/search", {"q": "c"})
        raise AssertionError("third call should have been refused")
    except RuntimeError as e:
        assert "budget of 2" in str(e)
    assert calls == ["a", "b"] and lk.sent == ["a", "b"]


def test_monitor_runs_only_the_named_corridor_within_budget():
    lk, ran = FakeLinkup(), []

    class Mon:
        DEFAULT_CORRIDORS = [{"name": "A", "queries": ["qa"]}, {"name": "B", "queries": ["qb"]}]

        @staticmethod
        def run(corridors):
            ran.extend(c["name"] for c in corridors)
            for c in corridors:
                for q in c["queries"]:
                    lk._post("/v1/search", {"q": q})
            return [{"corridor": c["name"], "queries_run": 1, "results_seen": 0, "events_extracted": 0,
                     "event_ids": [], "error": None} for c in corridors]

    assert job_entry.run_monitor(["--corridor", "B", "--max-calls", "1"], linkup=lk, monitor=Mon) == 0
    assert ran == ["B"] and lk.sent == ["qb"]


def test_optional_secret_missing_from_scope_is_skipped():
    def get(scope, key):
        raise KeyError(key)

    env = {}
    assert job_entry.load_optional(get, "portshift", env) == [] and env == {}
