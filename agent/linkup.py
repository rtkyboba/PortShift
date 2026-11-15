"""Linkup search and fetch (https://docs.linkup.so). Standard library only.

search(query)  -> [{title, url, snippet, published_at, retrieved_at, domain}]
fetch(url)     -> {url, title, text, retrieved_at}

Behaviour required by AGENTS.md section 7 slice 1:
  * HTTP 429 (rate limit or no credits): wait and retry the same query.
  * Empty result list: retry once or twice with a reworded query.
Without LINKUP_API_KEY, search returns [] and fetch raises LinkupUnavailable, so callers can say
"no live search" instead of inventing anything. `retrieved_at` is the time of the call: a result is
only ever shown with a real URL that Linkup returned.
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

BASE = "https://api.linkup.so"
REWORDS = ("{q} latest news", "{q} today announcement update")


class LinkupUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("LINKUP_API_KEY"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _post(path: str, body: dict, timeout: float = 30.0) -> dict:
    base = os.environ.get("LINKUP_BASE_URL", BASE).rstrip("/")
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {os.environ['LINKUP_API_KEY']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def _post_retrying(path: str, body: dict, retries: int, sleep) -> dict | None:
    """POST; on 429 wait 1s, 2s, ... and retry. None if every attempt fails (never raises on 4xx/5xx/network)."""
    for attempt in range(retries + 1):
        try:
            return _post(path, body)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < retries:
                sleep(2 ** attempt)
                continue
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None
    return None


def _published(value: str | None) -> str | None:
    if not value:
        return None
    return value if "T" in value else value + "T00:00:00Z"


def search(query: str, depth: str = "standard", max_results: int = 8, from_date: str | None = None,
           retries: int = 2, sleep=time.sleep) -> list[dict]:
    if not available():
        return []
    attempts = [query] + [r.format(q=query) for r in REWORDS[:2]]
    for text in attempts:
        body = {"q": text, "depth": depth, "outputType": "searchResults", "maxResults": max_results}
        if from_date:
            body["fromDate"] = from_date
        data = _post_retrying("/v1/search", body, retries, sleep)
        results = [r for r in (data or {}).get("results", []) if r.get("type", "text") == "text" and r.get("url")]
        if results:
            now = _now()
            return [{"title": r.get("name") or r["url"], "url": r["url"], "snippet": r.get("content", ""),
                     "published_at": _published(r.get("publishedAt")), "retrieved_at": now,
                     "domain": domain_of(r["url"])} for r in results]
    return []


def fetch(url: str, retries: int = 2, sleep=time.sleep) -> dict:
    if not available():
        raise LinkupUnavailable("LINKUP_API_KEY is not set")
    data = _post_retrying("/v1/fetch", {"url": url, "mode": "standard", "renderJs": False}, retries, sleep)
    if data is None:
        raise LinkupUnavailable(f"fetch failed for {url}")
    text = data.get("markdown", "")
    first = next((l.lstrip("# ").strip() for l in text.splitlines() if l.strip()), "")
    return {"url": url, "title": first[:200], "text": text, "retrieved_at": _now()}
