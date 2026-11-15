"""Chat fallback tests (no LLM). Run: cd app && python -m pytest -q"""
import os
import sys

for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402

import chat  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


def _ask(msg, ids):
    return chat.fallback_answer(msg, ids)


def test_explain_cites_evidence():
    r = _ask("Why is this at risk?", ["S-1005"])
    assert "level 5" in r["text"] and "Calais" in r["text"] and "confirmed" in r["text"]
    assert {"claim", "url", "title", "retrieved_at", "published_at"} == set(r["citations"][0])
    assert any("sample-news-d" in c["url"] for c in r["citations"])


def test_cost_matches_scenario_and_formula():
    r = _ask("how much to reschedule?", ["S-1002"])
    assert "EUR 1,410" in r["text"] and "illustrative" in r["text"] and r["citations"]  # 3 x 420 + 150


def test_cost_explicit_days_and_reroute():
    assert "EUR 4,200" in _ask("cost to reschedule by 2 days", ["S-1001"])["text"]  # 2 x 1800 + 600
    assert "EUR 320" in _ask("cost to reroute 100 km", ["S-1001"])["text"]  # 100 x 3.2


def test_plan_is_greedy_and_skips_low_risk():
    r = _ask("suggest a plan", ["S-1003", "S-1002", "S-1005"])
    t = r["text"]
    assert t.index("S-1002") < t.index("S-1003") and "S-1003: level 1, no change" in t
    assert "Total" in t and r["citations"]
    assert len({c["url"] for c in r["citations"]}) == len(r["citations"])


def test_help_when_unclear_or_nothing_selected():
    for msg, ids in [("hello", ["S-1001"]), ("explain", []), ("cost?", [])]:
        r = _ask(msg, ids)
        assert r["citations"] == [] and "explain" in r["text"] and "suggested plan" in r["text"]


def test_uses_agent_then_falls_back(monkeypatch):
    monkeypatch.setattr(chat, "agent_answer", lambda m, s: {"text": "from agent", "citations": []})
    assert chat.answer("explain", ["S-1001"])["text"] == "from agent"

    def boom(m, s):
        raise RuntimeError("down")
    monkeypatch.setattr(chat, "agent_answer", boom)
    assert "level 4" in chat.answer("explain", ["S-1001"])["text"]
    monkeypatch.setattr(chat, "agent_answer", None)
    body = {"message": "why", "selected_ids": ["S-1001"]}
    assert "level 4" in client.post("/api/chat", json=body).json()["text"]
