"""Minimal chat-completion client. Standard library only (no new dependency).

The LLM only writes wording. Every number, option, source and citation in an answer comes from
code (plan.py, cost.py, the evidence rows); chat.py also rejects any LLM text that contains a
figure it was not given. With no key configured, `available()` is False and chat.py answers
from templates, so the product works without an LLM.

Providers, chosen in this order (keys live only in your local .env, never in the repo).
Set LLM_PROVIDER=databricks|ollama|anthropic to force one.
  1. Databricks model serving: LLM_ENDPOINT + DATABRICKS_HOST + DATABRICKS_TOKEN.
     LLM_ENDPOINT is the serving endpoint name (OpenAI-compatible chat completions under
     <host>/serving-endpoints), or a full https URL to POST to directly.
  2. Ollama, hosted locally: OLLAMA_MODEL (for example a model you pulled, or a fine-tuned one you
     imported). OLLAMA_HOST defaults to http://127.0.0.1:11434. No key is needed.
     For a reasoning model set OLLAMA_REASONING_EFFORT=none, or it may think past the token limit.
  3. Anthropic Messages API: ANTHROPIC_API_KEY (model from LLM_MODEL, default below).
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"


def _databricks_ready() -> bool:
    return bool(os.environ.get("LLM_ENDPOINT") and os.environ.get("DATABRICKS_TOKEN") and (
        os.environ.get("DATABRICKS_HOST") or os.environ["LLM_ENDPOINT"].startswith("http")))


def provider() -> str | None:
    forced = os.environ.get("LLM_PROVIDER", "").lower()
    if forced == "databricks" and _databricks_ready():
        return "databricks"
    if forced == "ollama" and os.environ.get("OLLAMA_MODEL"):
        return "ollama"
    if forced == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if forced:
        return None
    if _databricks_ready():
        return "databricks"
    if os.environ.get("OLLAMA_MODEL"):
        return "ollama"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def available() -> bool:
    return provider() is not None


def _post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def complete(system: str, user: str, max_tokens: int = 350, timeout: float = 20.0) -> str | None:
    """One answer, or None on any failure (the caller falls back to its template)."""
    which = provider()
    try:
        if which == "databricks":
            endpoint = os.environ["LLM_ENDPOINT"]
            if endpoint.startswith("http"):
                url = endpoint
            else:
                host = os.environ["DATABRICKS_HOST"].rstrip("/")
                if not host.startswith("http"):
                    host = "https://" + host
                url = f"{host}/serving-endpoints/chat/completions"
            data = _post(
                url, {"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}"},
                {"model": endpoint if not endpoint.startswith("http") else "default",
                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                 "max_tokens": max_tokens, "temperature": 0.2},
                timeout,
            )
            return (data["choices"][0]["message"]["content"] or "").strip() or None
        if which == "ollama":
            host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
            if not host.startswith("http"):
                host = "http://" + host
            data = _post(
                f"{host}/v1/chat/completions", {},
                {"model": os.environ["OLLAMA_MODEL"],
                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                 "max_tokens": max_tokens, "temperature": 0.2, "stream": False,
                 # A reasoning model can spend the whole token budget thinking and return no answer.
                 # OLLAMA_REASONING_EFFORT=none switches that off; unset, nothing extra is sent.
                 **({"reasoning_effort": os.environ["OLLAMA_REASONING_EFFORT"]} if os.environ.get("OLLAMA_REASONING_EFFORT") else {})},
                max(timeout, 60.0),  # local models can be slow on the first call while they load
            )
            return (data["choices"][0]["message"]["content"] or "").strip() or None
        if which == "anthropic":
            base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
            data = _post(
                f"{base}/v1/messages",
                {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                {"model": os.environ.get("LLM_MODEL", DEFAULT_ANTHROPIC_MODEL), "max_tokens": max_tokens,
                 "system": system, "messages": [{"role": "user", "content": user}], "temperature": 0.2},
                timeout,
            )
            return "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text").strip() or None
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, OSError):
        return None
    return None
