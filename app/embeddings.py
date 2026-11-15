"""Embeddings for retrieval: turn text into vectors, so a question finds a record that means the same thing in
different words ("booze" and "whisky", "held up" and "strike").

Providers, the first one configured wins (keys only in the local .env):
  1. Databricks model serving: EMBED_ENDPOINT (an embedding endpoint name, for example databricks-gte-large-en)
     with DATABRICKS_HOST and DATABRICKS_TOKEN. On a workspace with a low rate limit a batch of texts is refused
     (HTTP 429) even though one text at a time is answered; a provisioned endpoint does not have that limit.
  2. Ollama, local: OLLAMA_EMBED_MODEL (for example nomic-embed-text, after `ollama pull nomic-embed-text`).
If the first provider fails and the second is configured too, the second is used. With neither, or when both fail,
embed() returns None and retrieval uses BM25 alone; a failure is remembered for a minute so a question does not wait
on a provider that is down. Off under pytest unless a test puts a provider in.

Vectors of records are kept in memory by the text they came from, so each record is embedded once; a question is
embedded each time it is asked. Standard library only.
"""
import hashlib
import json
import os
import sys
import time
import urllib.request

_cache: dict[str, list[float]] = {}


_down: dict[str, float] = {}   # provider -> when it last failed


def providers() -> list[str]:
    """The configured providers, in the order they are tried."""
    if "pytest" in sys.modules and not os.environ.get("PORTSHIFT_EMBED_IN_TESTS"):
        return []
    out = []
    if os.environ.get("EMBED_ENDPOINT") and os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"):
        out.append("databricks")
    if os.environ.get("OLLAMA_EMBED_MODEL"):
        out.append("ollama")
    return out


def provider() -> str | None:
    """The provider that will be tried first right now (one that failed in the last minute is skipped)."""
    return next((p for p in providers() if time.time() - _down.get(p, 0) > 60), None)


def _post(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _call(texts: list[str], kind: str, timeout: float, which: str | None = None) -> list[list[float]]:
    which = which or provider()
    if which == "databricks":
        host = os.environ["DATABRICKS_HOST"].rstrip("/")
        host = host if host.startswith("http") else "https://" + host
        data = _post(f"{host}/serving-endpoints/{os.environ['EMBED_ENDPOINT']}/invocations", {"input": texts},
                     {"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}"}, timeout)
        return [row["embedding"] for row in data["data"]]
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    host = host if host.startswith("http") else "http://" + host
    model = os.environ["OLLAMA_EMBED_MODEL"]
    # nomic-embed-text is trained with a prefix that says whether the text is a question or a record
    prefix = ("search_query: " if kind == "query" else "search_document: ") if "nomic" in model else ""
    return _post(f"{host}/api/embed", {"model": model, "input": [prefix + t for t in texts]}, {}, timeout)["embeddings"]


def embed(texts: list[str], kind: str = "document", timeout: float = 20.0) -> list[list[float]] | None:
    """One vector per text, or None when no provider is configured or every one fails (retrieval then uses BM25 alone).
    All the vectors of one call come from one provider: vectors of different models cannot be compared."""
    if not texts:
        return None
    for which in providers():
        if time.time() - _down.get(which, 0) <= 60:
            continue
        model = os.environ.get("EMBED_ENDPOINT") if which == "databricks" else os.environ.get("OLLAMA_EMBED_MODEL")
        keys = [hashlib.sha1(f"{which}|{model}|{kind}|{t}".encode()).hexdigest() for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in _cache]
        try:
            for start in range(0, len(missing), 64):
                batch = missing[start:start + 64]
                for i, vec in zip(batch, _call([texts[i] for i in batch], kind, timeout, which)):
                    _cache[keys[i]] = vec
        except Exception:
            _down[which] = time.time()
            continue
        if kind == "query":  # questions are not worth keeping
            return [_cache.pop(k) for k in keys]
        return [_cache[k] for k in keys]
    return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
