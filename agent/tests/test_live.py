"""Tests for linkup.py, extract.py, gazetteer.py, sink.py and monitor.py. No network, no keys."""
import json
import pathlib
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent import extract, gazetteer, linkup, monitor
from agent.sink import DatabricksSink, JsonDirSink

NOW = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
FIX = pathlib.Path(__file__).resolve().parents[2] / "demo" / "fixtures"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for key in ("LINKUP_API_KEY", "LINKUP_BASE_URL", "LLM_ENDPOINT", "DATABRICKS_TOKEN", "DATABRICKS_HOST",
                "ANTHROPIC_API_KEY", "OLLAMA_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------- fake Linkup
class _Linkup(BaseHTTPRequestHandler):
    script: list = []  # [(status, body)], consumed in order
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        status, payload = type(self).script.pop(0) if type(self).script else (200, {"results": []})
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *a):
        pass


@pytest.fixture()
def linkup_server(monkeypatch):
    httpd = HTTPServer(("127.0.0.1", 0), _Linkup)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Linkup.script, _Linkup.seen = [], []
    monkeypatch.setenv("LINKUP_API_KEY", "lk-test")
    monkeypatch.setenv("LINKUP_BASE_URL", f"http://127.0.0.1:{httpd.server_port}")
    yield _Linkup
    httpd.shutdown()


RESULT = {"name": "Rotterdam dockers strike", "url": "https://www.reuters.com/x", "content": "Dockers strike.",
          "type": "text", "publishedAt": "2026-11-14"}


def test_no_key_search_is_empty_and_fetch_raises():
    assert linkup.search("anything") == []
    with pytest.raises(linkup.LinkupUnavailable):
        linkup.fetch("https://example.com")


def test_search_shape_and_request(linkup_server):
    linkup_server.script = [(200, {"results": [RESULT, {"type": "image", "name": "i", "url": "https://x/i.png"}]})]
    out = linkup.search("rotterdam strike", sleep=lambda s: None)
    assert len(out) == 1 and out[0]["domain"] == "reuters.com" and out[0]["title"] == "Rotterdam dockers strike"
    assert out[0]["published_at"] == "2026-11-14T00:00:00Z" and out[0]["retrieved_at"].endswith("Z")
    seen = linkup_server.seen[0]
    assert seen["path"] == "/v1/search" and seen["auth"] == "Bearer lk-test"
    assert seen["body"]["outputType"] == "searchResults" and seen["body"]["q"] == "rotterdam strike"


def test_429_is_retried_with_backoff(linkup_server):
    linkup_server.script = [(429, {}), (429, {}), (200, {"results": [RESULT]})]
    waits = []
    assert len(linkup.search("q", sleep=waits.append)) == 1
    assert waits == [1, 2] and len(linkup_server.seen) == 3


def test_empty_results_retry_with_reworded_query(linkup_server):
    linkup_server.script = [(200, {"results": []}), (200, {"results": [RESULT]})]
    assert len(linkup.search("rotterdam strike", sleep=lambda s: None)) == 1
    queries = [s["body"]["q"] for s in linkup_server.seen]
    assert queries[0] == "rotterdam strike" and queries[1] != queries[0] and "rotterdam strike" in queries[1]


def test_persistent_failure_returns_empty_not_error(linkup_server):
    linkup_server.script = [(401, {})]
    assert linkup.search("q", sleep=lambda s: None) == []


def test_fetch_returns_markdown_text(linkup_server):
    linkup_server.script = [(200, {"markdown": "# Strike at port\nDetails here"})]
    page = linkup.fetch("https://x.example/a", sleep=lambda s: None)
    assert page["title"] == "Strike at port" and "Details" in page["text"]
    assert linkup_server.seen[0]["path"] == "/v1/fetch"


# ---------------------------------------------------------------- gazetteer and extractor
def test_gazetteer_resolves_known_and_drops_unknown():
    assert gazetteer.resolve("Port of Rotterdam")[0] == "Port of Rotterdam"
    assert gazetteer.resolve("the Suez Canal")[0] == "Suez Canal"
    assert gazetteer.resolve("Atlantis") is None and gazetteer.resolve("") is None
    assert gazetteer.resolve("Rotterdamn") is None  # whole-word match only


def test_extract_parse_validates_and_defaults():
    ok = extract.parse('```json\n{"type":"strike","location":{"name":"Calais"},"window":{"start":"2026-11-17",'
                       '"end":null},"summary":"Strike."}\n```')
    assert ok["window_end"] == "2026-11-20T00:00:00Z" and ok["type"] == "strike"
    assert extract.parse("null") is None and extract.parse("not json") is None
    assert extract.parse('{"type":"strike","location":{"name":""},"summary":"s"}', "2026-11-14") is None
    assert extract.parse('{"type":"strike","location":{"name":"X"},"window":{"start":"2026-11-20","end":"2026-11-10"},'
                         '"summary":"s"}') is None
    assert extract.parse('{"type":"weird","location":{"name":"X"},"summary":"s"}', "2026-11-14")["type"] == "other"


def test_extract_without_llm_returns_none():
    assert extract.extract({"title": "t", "snippet": "s", "url": "u"}) is None


# ---------------------------------------------------------------- monitor
def _ext(location, kind="strike", start="2026-11-15", end="2026-11-18", summary="Strike announced."):
    def fn(item, today=None):
        return {"type": kind, "location_name": location, "window_start": start + "T00:00:00Z",
                "window_end": end + "T00:00:00Z", "summary": summary, "source_url": item["url"],
                "published_at": item.get("published_at")}
    return fn


def _res(url, title="t"):
    from agent.linkup import domain_of
    return {"title": title, "url": url, "snippet": "x", "published_at": "2026-11-14T00:00:00Z",
            "retrieved_at": "2026-11-14T17:59:00Z", "domain": domain_of(url)}


def _sink(tmp_path):
    return JsonDirSink(tmp_path / "live")


def test_two_independent_domains_confirm(tmp_path):
    sink = _sink(tmp_path)
    corridor = {"name": "North Sea", "queries": ["q"]}
    search = lambda q, **k: [_res("https://reuters.com/a"), _res("https://bbc.co.uk/b")]
    rec = monitor.run_corridor_record(corridor, sink, NOW, search, _ext("Port of Rotterdam"))
    events = json.loads((sink.dir / "disruption_events.json").read_text())
    live = [e for e in events if not e["is_fixture"]]
    assert len(live) == 1 and live[0]["status"] == "confirmed" and live[0]["location"] == "Port of Rotterdam"
    assert (live[0]["lat"], live[0]["lon"]) == (51.95, 4.14)  # from the gazetteer, not the model
    evidence = [e for e in json.loads((sink.dir / "evidence.json").read_text()) if e["event_id"] == live[0]["event_id"]]
    assert {e["domain"] for e in evidence} == {"reuters.com", "bbc.co.uk"}
    assert rec["event_ids"] == [live[0]["event_id"]] and rec["needs_rescore"] is True


def test_single_unofficial_domain_is_suspected_and_official_confirms(tmp_path):
    corridor = {"name": "c", "queries": ["q"]}
    one = monitor.run_corridor_record(corridor, _sink(tmp_path / "a"), NOW,
                                      lambda q, **k: [_res("https://blog.example.com/a")], _ext("Calais"))
    sink = _sink(tmp_path / "b")
    off = monitor.run_corridor_record(corridor, sink, NOW,
                                      lambda q, **k: [_res("https://www.portofrotterdam.com/a")], _ext("Calais"))
    ev_a = json.loads((tmp_path / "a" / "live" / "disruption_events.json").read_text())
    ev_b = json.loads((sink.dir / "disruption_events.json").read_text())
    assert [e["status"] for e in ev_a if not e["is_fixture"]] == ["suspected"]
    assert [e["status"] for e in ev_b if not e["is_fixture"]] == ["confirmed"]
    ev = [e for e in json.loads((sink.dir / "evidence.json").read_text()) if e["domain"] == "portofrotterdam.com"]
    assert ev and ev[0]["is_official"] is True and one["event_ids"] and off["event_ids"]


def test_unplaceable_events_are_dropped_and_counted(tmp_path):
    sink = _sink(tmp_path)
    rec = monitor.run_corridor_record({"name": "c", "queries": ["q"]}, sink, NOW,
                                      lambda q, **k: [_res("https://a.com/x")], _ext("Atlantis harbour"))
    assert rec["event_ids"] == [] and rec["events_dropped"] == 1 and "Atlantis" in rec["dropped_reasons"][0]
    assert not [e for e in json.loads((sink.dir / "disruption_events.json").read_text()) if not e["is_fixture"]]


def test_different_places_and_windows_stay_separate(tmp_path):
    sink = _sink(tmp_path)
    calls = iter([_ext("Calais"), _ext("Hamburg"), _ext("Calais", start="2026-12-20", end="2026-12-22")])
    search = lambda q, **k: [_res(f"https://site{abs(hash(q)) % 999}.com/{q}")]
    extractor = lambda item, today=None: next(calls)(item, today)
    rec = monitor.run_corridor_record({"name": "c", "queries": ["a", "b", "c"]}, sink, NOW, search, extractor)
    assert len(rec["event_ids"]) == 3


def test_run_record_has_steps_and_is_written(tmp_path):
    sink = _sink(tmp_path)
    rec = monitor.run_corridor_record({"name": "Ch", "queries": ["q1", "q2"]}, sink, NOW,
                                      lambda q, **k: [_res("https://a.com/" + q)], _ext("Calais"))
    assert rec["queries_run"] == 2 and len(rec["steps"]) == 2 and rec["results_seen"] == 2
    runs = json.loads((sink.dir / "agent_runs.json").read_text())
    assert runs[0]["run_id"] == rec["run_id"] and json.loads(runs[0]["steps_json"])[0]["query"] == "q1"


def test_corridor_failure_is_contained(tmp_path):
    def boom(q, **k):
        raise RuntimeError("search exploded")
    rec = monitor.run_corridor_record({"name": "c", "queries": ["q"]}, _sink(tmp_path), NOW, boom, _ext("Calais"))
    assert "search exploded" in rec["error"] and rec["event_ids"] == []


def test_rerun_upserts_instead_of_duplicating(tmp_path):
    sink = _sink(tmp_path)
    args = ({"name": "c", "queries": ["q"]}, sink, NOW, lambda q, **k: [_res("https://a.com/x")], _ext("Calais"))
    monitor.run_corridor_record(*args)
    monitor.run_corridor_record(*args)
    live = [e for e in json.loads((sink.dir / "disruption_events.json").read_text()) if not e["is_fixture"]]
    assert len(live) == 1


def test_run_corridor_returns_event_ids(tmp_path):
    ids = monitor.run_corridor({"name": "c", "queries": ["q"]}, sink=_sink(tmp_path), now=NOW,
                               search_fn=lambda q, **k: [_res("https://a.com/x")], extract_fn=_ext("Calais"))
    assert len(ids) == 1 and ids[0].startswith("L-")


def test_official_domain_rules():
    assert monitor.is_official("portofrotterdam.com") and monitor.is_official("transport.gov.uk")
    assert monitor.is_official("bison-fute.gouv.fr") and not monitor.is_official("reuters.com")


# ---------------------------------------------------------------- sinks
def test_json_sink_is_seeded_from_fixtures(tmp_path):
    sink = _sink(tmp_path)
    assert {p.name for p in sink.dir.glob("*.json")} >= {"shipments.json", "legs.json", "disruption_events.json"}
    assert json.loads((sink.dir / "shipments.json").read_text()) == json.loads((FIX / "shipments.json").read_text())


def test_databricks_sink_builds_upsert_sql():
    run = []
    sink = DatabricksSink(execute=run.append)
    row = {"event_id": "L-1", "type": "strike", "status": "confirmed", "location": "Calais", "lat": 50.97, "lon": 1.85,
           "radius_km": 25.0, "window_start": "2026-11-15T00:00:00Z", "window_end": "2026-11-18T00:00:00Z",
           "summary": "It's a strike.", "detected_at": "2026-11-14T18:00:00Z", "is_fixture": False}
    assert sink.write("disruption_events", [row], ["event_id"]) == 1
    assert run[0].startswith("DELETE FROM main.portshift.disruption_events WHERE event_id IN ('L-1')")
    assert run[1].startswith("INSERT INTO main.portshift.disruption_events") and "'It\\'s a strike.'" in run[1]
    assert "FALSE" in run[1]


def test_databricks_sink_unknown_table_raises_so_monitor_skips_it():
    with pytest.raises(KeyError):
        DatabricksSink(execute=lambda s: None).write("agent_runs", [{"run_id": "R"}], ["run_id"])
