"""Strict extractor: retries failed model calls, keeps 'null' replies, and drops events that already ended (in code)."""
from agent import extract

ITEM = {"url": "https://example.invalid/a", "domain": "example.invalid", "title": "t", "snippet": "s",
        "published_at": "2026-11-10T00:00:00Z"}
EVENT = '{"type": "warning", "location": {"name": "Port of Los Angeles"}, "window": {"start": "2026-11-20", "end": null}, "summary": "Strike deferred to 20 Nov."}'


def _fake(monkeypatch, replies):
    calls = []

    def complete(system, user, **kw):
        calls.append(user)
        return replies.pop(0)

    monkeypatch.setattr(extract.llm, "available", lambda: True)
    monkeypatch.setattr(extract.llm, "complete", complete)
    return calls


def test_failed_call_is_retried_until_a_reply(monkeypatch):
    calls = _fake(monkeypatch, [None, None, EVENT])
    ev = extract.extract_raw(ITEM, "2026-11-15", sleep=lambda s: None)
    assert len(calls) == 3 and ev["type"] == "warning" and ev["window_start"] == "2026-11-20T00:00:00Z"


def test_null_reply_is_not_retried(monkeypatch):
    calls = _fake(monkeypatch, ["null", EVENT])
    assert extract.extract_raw(ITEM, "2026-11-15", sleep=lambda s: None) is None and len(calls) == 1


def test_event_that_already_ended_is_dropped_by_extract_but_kept_by_extract_raw(monkeypatch):
    past = EVENT.replace("2026-11-20", "2026-11-01")
    _fake(monkeypatch, [past, past])
    assert extract.extract_raw(ITEM, "2026-11-15", sleep=lambda s: None) is not None
    assert extract.extract(ITEM, "2026-11-15") is None


def test_model_input_carries_source_domain_and_today():
    user = extract.build_user({**ITEM, "domain": "linkedin.com"}, "2026-11-15")
    assert '"source": "linkedin.com"' in user and '"today": "2026-11-15"' in user
    assert extract.training_prompt(ITEM, "2026-11-15").startswith(extract.SYSTEM)
