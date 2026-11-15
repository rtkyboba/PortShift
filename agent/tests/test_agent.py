"""Tests for cost, plan options, limits, chat and the LLM guard. No network, no keys."""
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent import chat, cost, llm, plan
from agent.plan import Preferences

FIX = pathlib.Path(__file__).resolve().parents[2] / "demo" / "fixtures"


@pytest.fixture()
def db():
    return {t: json.loads((FIX / f"{t}.json").read_text()) for t in
            ("shipments", "legs", "disruption_events", "evidence", "shipment_risk", "cost_rates")}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for key in ("LLM_ENDPOINT", "DATABRICKS_HOST", "DATABRICKS_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
                "LLM_MODEL", "LLM_PROVIDER", "OLLAMA_MODEL", "OLLAMA_HOST"):
        monkeypatch.delenv(key, raising=False)
    chat._session = Preferences()


# ---- cost formulas
def test_cost_formulas_use_cost_rates(db):
    r = cost.reschedule_cost("S-1002", 3, db)  # truck: 420/day + 150 fee
    assert r["cost"] == 3 * 420 + 150 and r["currency"] == "EUR"
    assert cost.reroute_cost("S-1002", 100, db)["cost"] == 100 * 1.8 + 150
    assert cost.reroute_cost("S-1001", 1000, db)["cost"] == 1000 * 3.2 + 600  # ship


# ---- options and limits
def test_options_for_disrupted_truck(db):
    info = plan.options_for("S-1002", db)
    kinds = {o["kind"] for o in info["options"]}
    assert kinds == {"keep", "reschedule", "reroute"}
    assert info["risk"] == 5
    resched = next(o for o in info["options"] if o["kind"] == "reschedule")
    assert resched["extra_cost"] == cost.reschedule_cost("S-1002", resched["delay_days"], db)["cost"]
    assert resched["delay_days"] >= 1 and resched["new_planned_start"]


def test_clear_shipment_only_has_keep(db):
    assert [o["kind"] for o in plan.options_for("S-1003", db)["options"]] == ["keep"]


def test_default_limits_pick_cheapest_inside(db):
    best, status, ev = plan.recommend(plan.options_for("S-1002", db)["options"], Preferences())
    assert status == "within_limits" and best["kind"] == "reroute"  # cheapest option that lowers risk to <= 3
    assert next(o for o in ev if o["kind"] == "keep")["within_limits"] is False


def test_accepting_high_risk_recommends_keeping(db):
    best, status, _ = plan.recommend(plan.options_for("S-1002", db)["options"], Preferences(max_risk=5))
    assert best["kind"] == "keep" and status == "no_action_needed"


def test_impossible_limits_flag_outside(db):
    best, status, ev = plan.recommend(plan.options_for("S-1002", db)["options"],
                                      Preferences(max_risk=1, max_extra_cost=10))
    assert status == "outside_limits" and not best["within_limits"] and best["violations"]


def test_delay_limit_excludes_slow_options(db):
    _, _, ev = plan.recommend(plan.options_for("S-1002", db)["options"], Preferences(max_delay_hours=6))
    assert next(o for o in ev if o["kind"] == "reschedule")["within_limits"] is False
    assert next(o for o in ev if o["kind"] == "reroute")["within_limits"] is True


def test_suggest_plan_rows_match_contract(db):
    result = plan.suggest_plan(["S-1002", "S-1005"], Preferences(), db)
    assert result["scenario"]["status"] == "tentative" and result["scenario"]["scenario_id"].startswith("SC-")
    assert plan.suggest_plan(["S-1002", "S-1005"], Preferences(), db)["scenario"]["scenario_id"] == result["scenario"]["scenario_id"]
    for ch in result["changes"]:
        assert set(ch) == {"scenario_id", "shipment_id", "change_type", "delay_days", "new_planned_start",
                           "extra_km", "cost_delta", "note"}
    assert result["scenario"]["cost_delta"] == round(sum(c["cost_delta"] for c in result["changes"]), 2)


def test_default_plan_covers_every_disrupted_shipment(db):
    ids = {r["shipment_id"] for r in plan.suggest_plan(None, Preferences(), db)["shipments"]}
    assert ids == {r["shipment_id"] for r in db["shipment_risk"] if r["level"] > 1}


# ---- limits from the sentence
@pytest.mark.parametrize("text,expected", [
    ("suggest routes, max risk 1, under EUR 500", (1, 500.0, None)),
    ("risk 2 or lower please", (2, 5000.0, None)),
    ("set max risk to 2", (2, 5000.0, None)),
    ("budget of 3k and no more than 12 hours delay", (3, 3000.0, 12.0)),
    ("delay under 2 days", (3, 5000.0, 48.0)),
    ("no cost limit", (3, None, None)),
    ("suggest routes for S-1005", (3, 5000.0, None)),  # a shipment number is not a limit
])
def test_parse_preferences(text, expected):
    p, _ = chat.parse_preferences(text, Preferences())
    assert (p.max_risk, p.max_extra_cost, p.max_delay_hours) == expected


def test_preferences_clamp_and_describe():
    p = Preferences.from_dict({"max_risk": 99, "max_extra_cost": -5, "max_delay_hours": "none"})
    assert p.max_risk == 5 and p.max_extra_cost == 0.0 and p.max_delay_hours is None
    assert "level 5" in p.describe()


# ---- chat without an LLM
def test_suggest_routes_lists_options_and_cites_evidence(db):
    r = chat.answer("suggest routes", ["S-1002"], db=db)
    assert r["intent"] == "suggest_plan" and r["llm_used"] is False
    assert "Recommended:" in r["text"] and "Reroute" in r["text"] and "Reschedule" in r["text"]
    assert "estimate" in r["text"].lower()
    urls = {e["url"] for e in db["evidence"]}
    assert r["citations"] and all(c["url"] in urls for c in r["citations"])
    assert r["plan"]["scenario"]["status"] == "tentative"


def test_suggest_with_limits_in_the_sentence_changes_the_answer(db):
    loose = chat.answer("suggest routes", ["S-1002"], db=db)["plan"]["shipments"][0]["recommended_id"]
    tight = chat.answer("suggest routes, max risk 1 and under EUR 100", ["S-1002"], db=db)
    assert tight["preferences"]["max_risk"] == 1 and tight["preferences"]["max_extra_cost"] == 100.0
    assert tight["plan"]["shipments"][0]["status"] == "outside_limits"
    assert loose == "reroute"


def test_limits_persist_and_ui_object_overrides(db):
    chat.answer("set max risk to 2", [], db=db)
    assert chat._session.max_risk == 2
    r = chat.answer("suggest a plan", ["S-1006"], preferences={"max_extra_cost": 123}, db=db)
    assert r["preferences"]["max_risk"] == 2 and r["preferences"]["max_extra_cost"] == 123.0


def test_set_limits_only_message_confirms(db):
    r = chat.answer("max risk 4", [], db=db)
    assert r["intent"] == "set_limits" and "Limits updated" in r["text"]


def test_cost_intent_reports_formula_cost(db):
    r = chat.answer("what does it cost to move this to another date?", ["S-1002"], db=db)
    assert r["intent"] == "cost_to_reschedule" and "estimate" in r["text"].lower()
    days = next(o for o in plan.options_for("S-1002", db)["options"] if o["kind"] == "reschedule")
    assert f"{days['extra_cost']:,.0f}" in r["text"]


def test_cost_for_clear_shipment_says_nothing_to_wait_out(db):
    r = chat.answer("how much to move it a day?", ["S-1003"], db=db)
    assert "no disruption" in r["text"].lower()


def test_cost_without_selection_asks_to_select(db):
    assert "Select a shipment" in chat.answer("what does it cost to reschedule", [], db=db)["text"]


def test_explain_names_status_and_basis(db):
    r = chat.answer("why is this risky?", ["S-1001"], db=db)
    assert r["intent"] == "explain" and "confirmed" in r["text"] and "sample" in r["text"]
    assert r["citations"]


def test_shipment_id_in_message_counts_as_selected(db):
    r = chat.answer("suggest routes for S-1005", [], db=db)
    assert [s["shipment_id"] for s in r["plan"]["shipments"]] == ["S-1005"]


def test_fleet_overview_without_selection(db):
    assert "S-1002" in chat.answer("what is going on?", [], db=db)["text"]


def test_unknown_shipment_is_handled(db):
    assert "could not find" in chat.answer("suggest routes", ["S-9999"], db=db)["text"]


# ---- the LLM client and the figure guard
class _Fake(BaseHTTPRequestHandler):
    reply = "Rerouting is the cheapest option inside your limits."
    status = 200
    seen: dict = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen = {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.path.endswith("chat/completions"):
            out = {"choices": [{"message": {"content": type(self).reply}}]}
        else:
            out = {"content": [{"type": "text", "text": type(self).reply}]}
        self.wfile.write(json.dumps(out).encode())

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Fake.reply, _Fake.status, _Fake.seen = "Rerouting is the cheapest option inside your limits.", 200, {}
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_no_key_means_no_llm():
    assert llm.provider() is None and llm.complete("s", "u") is None


def test_anthropic_request_shape_and_wording_used(db, monkeypatch, server):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", server)
    r = chat.answer("suggest routes", ["S-1002"], db=db)
    assert r["llm_used"] is True and r["text"].startswith("Rerouting is the cheapest option")
    assert "Recommended:" in r["text"]  # option list is still printed by code
    seen = _Fake.seen
    assert seen["path"] == "/v1/messages" and seen["headers"]["x-api-key"] == "test-key"
    assert "CONTEXT" in seen["body"]["messages"][0]["content"] and "never" in seen["body"]["system"].lower()


def test_databricks_endpoint_request_shape(monkeypatch, server):
    monkeypatch.setenv("LLM_ENDPOINT", f"{server}/serving-endpoints/chat/completions")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    assert llm.provider() == "databricks"
    assert llm.complete("sys", "user") == "Rerouting is the cheapest option inside your limits."
    assert _Fake.seen["headers"]["authorization"] == "Bearer dapi-test"


def test_invented_figures_are_rejected(db, monkeypatch, server):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", server)
    _Fake.reply = "Rerouting costs only EUR 99999 so it is clearly best."
    r = chat.answer("suggest routes", ["S-1002"], db=db)
    assert r["llm_used"] is False and "99999" not in r["text"] and "Recommended:" in r["text"]


def test_llm_failure_falls_back(db, monkeypatch, server):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", server)
    _Fake.status = 500
    r = chat.answer("suggest routes", ["S-1002"], db=db)
    assert r["llm_used"] is False and "Recommended:" in r["text"]


def test_ollama_request_shape(monkeypatch, server):
    monkeypatch.setenv("OLLAMA_MODEL", "portshift-test")
    monkeypatch.setenv("OLLAMA_HOST", server)
    assert llm.provider() == "ollama"
    assert llm.complete("sys", "user") == "Rerouting is the cheapest option inside your limits."
    seen = _Fake.seen
    assert seen["path"] == "/v1/chat/completions" and seen["body"]["model"] == "portshift-test"
    assert "authorization" not in seen["headers"] and seen["body"]["stream"] is False


def test_ollama_chat_end_to_end(db, monkeypatch, server):
    monkeypatch.setenv("OLLAMA_MODEL", "portshift-test")
    monkeypatch.setenv("OLLAMA_HOST", server)
    r = chat.answer("suggest routes", ["S-1002"], db=db)
    assert r["llm_used"] is True and "Recommended:" in r["text"]


def test_provider_order_and_force(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("OLLAMA_MODEL", "m")
    assert llm.provider() == "ollama"  # local first when no Databricks endpoint is configured
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert llm.provider() == "anthropic"
    monkeypatch.setenv("LLM_PROVIDER", "databricks")  # forced but not configured: no silent switch
    assert llm.provider() is None


def test_ollama_down_falls_back(db, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "m")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")  # nothing listens here
    r = chat.answer("suggest routes", ["S-1002"], db=db)
    assert r["llm_used"] is False and "Recommended:" in r["text"]
