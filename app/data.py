"""Single data-access layer. The ONLY module that knows where data lives.

Row shapes are exactly CONTRACTS.md section 3. Two sources:
  * dev (default): demo/fixtures/*.json at the repo root (override with PORTSHIFT_FIXTURES)
  * Databricks: when DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_WAREHOUSE_ID are all set,
    SELECTs against DATABRICKS_CATALOG.DATABRICKS_SCHEMA (default main.portshift) through
    databricks-sql-connector. The SELECTs mirror pipelines/queries.py.
"""
import contextlib
import contextvars
import copy
import json
import math
import os
import pathlib
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
FIXTURES = pathlib.Path(os.environ.get("PORTSHIFT_FIXTURES") or _here.parent / "demo" / "fixtures")

ORDER = {
    "shipments": "shipment_id", "legs": "shipment_id, seq", "disruption_events": "event_id",
    "evidence": "event_id, evidence_id", "shipment_risk": "shipment_id", "cost_rates": "mode",
    "scenarios": "created_at DESC, scenario_id", "scenario_changes": "scenario_id, shipment_id",
    "rate_cards": "rate_id", "surcharges": "mode, code", "delay_charges": "mode, unit, partner", "shipment_terms": "shipment_id",
    "warehouse_stock": "warehouse, stock_id", "dispatch_orders": "submitted_at DESC, order_id", "dispatch_lines": "order_id, stock_id",
}


def use_databricks() -> bool:
    return all(os.environ.get(k) for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"))


def source() -> str:
    return "databricks" if use_databricks() else "fixtures"


# ---- Databricks SQL: one reused connection and a short per-table cache -------------------------
# Opening a connection costs seconds, and one screen or chat answer reads many tables, so every read
# used to take tens of seconds. Reads now share one connection (the connector's connection is not
# thread-safe, hence the lock) and a table read is reused for PORTSHIFT_SQL_CACHE_S seconds (default 30).
# forget_rows() clears the cache; main.py calls it after every successful write request, and the TTL
# covers writes from other processes (the Databricks Job).
_SQL_LOCK = threading.Lock()
_SQL_CONN = None
_SQL_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _sql_ttl() -> float:
    try:
        return float(os.environ.get("PORTSHIFT_SQL_CACHE_S", "30"))
    except ValueError:
        return 30.0


def forget_rows(table: str | None = None) -> None:
    """Drop cached table reads (all tables, or one), so the next read goes to Delta."""
    with _SQL_LOCK:
        if table is None:
            _SQL_CACHE.clear()
        else:
            _SQL_CACHE.pop(table, None)


def _sql_query(query: str) -> list[dict]:
    """Run one SELECT on the shared connection; reconnect once if the connection has gone stale."""
    global _SQL_CONN
    from databricks import sql
    for attempt in (1, 2):
        try:
            if _SQL_CONN is None:
                _SQL_CONN = sql.connect(
                    server_hostname=os.environ["DATABRICKS_HOST"].replace("https://", "").rstrip("/"),
                    http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
                    access_token=os.environ["DATABRICKS_TOKEN"])
            with _SQL_CONN.cursor() as cur:
                cur.execute(query)
                return _cursor_rows(cur)
        except Exception:
            try:
                _SQL_CONN.close()
            except Exception:
                pass
            _SQL_CONN = None
            if attempt == 2:
                raise


def _sql_rows(table: str) -> list[dict]:
    cat = os.environ.get("DATABRICKS_CATALOG", "main")
    sch = os.environ.get("DATABRICKS_SCHEMA", "portshift")
    with _SQL_LOCK:
        hit = _SQL_CACHE.get(table)
        if hit and time.monotonic() - hit[0] < _sql_ttl():
            return copy.deepcopy(hit[1])  # callers may change rows; the cache must not change with them
        rows = _sql_query(f"SELECT * FROM {cat}.{sch}.{table} ORDER BY {ORDER[table]}")
        _SQL_CACHE[table] = (time.monotonic(), rows)
        return copy.deepcopy(rows)


COMPLEX = ("array", "map", "struct")


def _plain(v, type_code=None):
    """Connector arrays may be tuples/numpy-like; JSON needs lists. Without pyarrow the connector returns
    ARRAY/MAP/STRUCT columns as JSON text, so those are decoded by their column type."""
    if type_code in COMPLEX and isinstance(v, str):
        return json.loads(v)
    if hasattr(v, "tolist"):
        v = v.tolist()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _cursor_rows(cur) -> list[dict]:
    cols = [(d[0], d[1] if len(d) > 1 else None) for d in cur.description]
    return [{k: _plain(v, t) for (k, t), v in zip(cols, row)} for row in cur.fetchall()]


# ---- demo clock -------------------------------------------------------------------------------
# The fixtures are written for one moment (clock.json "as_of"). When the app serves them, every
# timestamp is shifted so that moment is always now, to the hour: a shipment that is about to reach a
# strike stays about to reach it, whenever the demo is opened. Off under pytest, and with
# PORTSHIFT_DEMO_CLOCK=0. Never applied to Databricks rows or to a folder without clock.json.
_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def demo_clock_shift() -> timedelta | None:
    if os.environ.get("PORTSHIFT_DEMO_CLOCK", "0" if "pytest" in sys.modules else "1") != "1":
        return None
    try:
        as_of = _ts(json.loads((FIXTURES / "clock.json").read_text())["as_of"])
    except (OSError, KeyError, ValueError):
        return None
    return _now().replace(minute=0, second=0, microsecond=0) - as_of


def _shifted(v, by: timedelta):
    if isinstance(v, str) and _STAMP.match(v):
        return _iso(_ts(v) + by)
    if isinstance(v, list):
        return [_shifted(x, by) for x in v]
    if isinstance(v, dict):
        return {k: _shifted(x, by) for k, x in v.items()}
    return v


# ---- what if: a hypothetical event, for one request only -------------------------------------------
# While a what-if is being worked out, the hypothetical event is added to what `_rows` returns for
# disruption_events and the fleet is scored again with it. Nothing is written anywhere, and the context
# variable keeps it to the request that asked: every other reader still sees only the real tables.
_hypothetical: contextvars.ContextVar = contextvars.ContextVar("portshift_hypothetical", default=None)


@contextlib.contextmanager
def supposing(events: list[dict]):
    token = _hypothetical.set({"events": list(events), "risk": None})
    try:
        yield
    finally:
        _hypothetical.reset(token)


def _rows(table: str) -> list[dict]:
    hyp = _hypothetical.get()
    if not hyp or table not in ("disruption_events", "shipment_risk"):
        return _shown_rows(table)
    if table == "disruption_events":
        return _shown_rows(table) + hyp["events"]
    if hyp["risk"] is None:
        hyp["risk"] = risk_job().score_fleet(_stored_rows("shipments"), _stored_rows("legs"), _rows("disruption_events"), _now())
    return hyp["risk"]


# ---- sample events step aside once there are live ones ---------------------------------------------
# Sample events exist so the app has something to show before any live search has run. With the setting on,
# once the monitor has found real events the samples are left out (with their evidence) and the fleet is scored on the real ones
# only, so the map is not a mix of the two. This is opt-in, PORTSHIFT_SAMPLE_EVENTS=hide, because today's real
# events may touch few demo shipments and the map then goes quiet; the default shows both, samples marked.
_live_only: dict = {"key": None, "rows": None}
_hidden_seen: dict = {"at": -1e9, "value": False}


def samples_hidden() -> bool:
    if os.environ.get("PORTSHIFT_SAMPLE_EVENTS", "keep") != "hide":
        return False
    if not use_databricks():
        return _has_cited_live()
    now = time.monotonic()  # the queries answer this for 20 seconds, so each read does not cost more
    if now - _hidden_seen["at"] > 20:
        _hidden_seen.update(at=now, value=_has_cited_live())
    return _hidden_seen["value"]


def _has_cited_live() -> bool:
    """Is there a live event that can be shown, that is, one with a source? (No citation, no display.)"""
    cited = {v.get("event_id") for v in _stored_rows("evidence")}
    return any(not e.get("is_fixture") and e["event_id"] in cited for e in _stored_rows("disruption_events"))


def _shown_rows(table: str) -> list[dict]:
    rows = _stored_rows(table)
    if table not in ("disruption_events", "evidence", "shipment_risk") or not samples_hidden():
        return rows
    live = [e for e in (rows if table == "disruption_events" else _stored_rows("disruption_events")) if not e.get("is_fixture")]
    if table == "disruption_events":
        return live
    ids = {e["event_id"] for e in live}
    if table == "evidence":
        return [v for v in rows if v.get("event_id") in ids]
    now = _now()
    key = (tuple(sorted(ids)), now.strftime("%Y-%m-%dT%H:%M"))
    if _live_only["key"] != key:
        try:
            scored = risk_job().score_fleet(_stored_rows("shipments"), _stored_rows("legs"), live, now)
        except Exception:  # the job is missing or failed: keep the stored levels rather than guess
            scored = rows
        _live_only.update(key=key, rows=scored)
    return _live_only["rows"]


def _stored_rows(table: str) -> list[dict]:
    if use_databricks():
        return _sql_rows(table)
    rows = json.loads((FIXTURES / f"{table}.json").read_text())
    by = demo_clock_shift()
    rows = _shifted(rows, by) if by else rows
    return _with_live(table, rows) if table in ("disruption_events", "evidence", "shipment_risk") else rows


# ---- live events over the demo fleet ------------------------------------------------------------
# Without Databricks the monitor writes what it finds to a local folder. Those events (real, never shifted
# by the demo clock) are laid over the sample rows, and the risk job is run again on the fleet, so a new
# event changes a shipment's level the next time the app reads. In Databricks the tables already hold both.
_rescore: dict = {"key": None, "rows": None}


def live_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PORTSHIFT_LIVE_DIR") or _here.parent / ".portshift_live")


def _live_rows(table: str) -> list[dict]:
    try:
        rows = json.loads((live_dir() / f"{table}.json").read_text())
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)]


def live_events() -> list[dict]:
    if live_dir().resolve() == FIXTURES.resolve():
        return []
    return [e for e in _live_rows("disruption_events") if not e.get("is_fixture")]


def risk_job():
    """pipelines/risk_job.py, loaded once: the same deterministic scorer the fleet uses."""
    global _risk_mod
    if _risk_mod is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("portshift_risk_job", _here.parent / "pipelines" / "risk_job.py")
        _risk_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_risk_mod)
    return _risk_mod


_risk_mod = None


def forget_rescore() -> None:
    _rescore["key"] = None


def _with_live(table: str, rows: list[dict]) -> list[dict]:
    live = live_events()
    if not live:
        return rows
    if table == "disruption_events":
        have = {r["event_id"] for r in rows}
        return rows + [e for e in live if e["event_id"] not in have]
    if table == "evidence":
        ids, have = {e["event_id"] for e in live}, {r["evidence_id"] for r in rows}
        return rows + [v for v in _live_rows("evidence") if v.get("event_id") in ids and v.get("evidence_id") not in have]
    now = _now()
    key = (tuple(sorted(e["event_id"] for e in live)), now.strftime("%Y-%m-%dT%H:%M"))
    if _rescore["key"] != key:
        try:
            scored = risk_job().score_fleet(_rows("shipments"), _rows("legs"), _rows("disruption_events"), now)
        except Exception:  # the job is missing or failed: keep the stored levels rather than guess
            scored = rows
        _rescore.update(key=key, rows=scored)
    return _rescore["rows"]


_bundled_only: set[str] = set()


def optional_rows(table: str) -> list[dict]:
    """Rows of a table that may not exist in Delta yet (the rate tables and shipment_terms): read from Delta
    when it is there, else from the bundled fixture file."""
    if use_databricks() and table not in _bundled_only:
        try:
            return _sql_rows(table)
        except Exception:
            _bundled_only.add(table)
    try:
        rows = json.loads((FIXTURES / f"{table}.json").read_text())
    except OSError:
        return []
    by = demo_clock_shift()
    return _shifted(rows, by) if by else rows


def event_basis(event: dict, evidence: list[dict]) -> dict:
    """Why an event is confirmed or suspected, from its evidence rows. No numeric confidence."""
    domains = sorted({e["domain"] for e in evidence})
    official = [e["domain"] for e in evidence if e.get("is_official")]
    if official:
        text = f"official source ({official[0]})"
    elif len(domains) >= 2:
        text = f"{len(domains)} independent domains ({', '.join(domains)})"
    else:
        text = f"single source ({domains[0]})" if domains else "no evidence rows"
    return {"status": event["status"], "text": text, "domains": domains, "has_official": bool(official),
            "meets_confirmed_rule": bool(official) or len(domains) >= 2}


def _check(risk: dict, events: list[dict], legs: list[dict] | None = None) -> str | None:
    """Display-side guard for the AGENTS.md rules: Severe/Critical need a confirmed event, and a disruption
    the shipment has already passed is not a disruption."""
    lvl = risk.get("level")
    if lvl in (4, 5) and not any(e["status"] == "confirmed" for e in events):
        return (f"Level {lvl} needs a confirmed event under the risk rules, but the linked event(s) are only "
                "suspected. The risk job should rescore this shipment.")
    if events and legs:
        ahead = [{"geometry": g} for g in (remaining_geometry(leg, _now()) for leg in legs) if len(g) > 1]
        # 100 km margin: the risk rules also count a confirmed event near the route (pipelines/risk_job.py NEAR_KM)
        if not any(leg_in_area(a, e, margin_km=100.0) for a in ahead for e in events):
            places = ", ".join(sorted({e["location"] for e in events}))
            return (f"The linked disruption ({places}) is behind this shipment: the rest of its route does not pass "
                    "through it. The risk job should rescore this shipment.")
    return None


def remaining_geometry(leg: dict, now: datetime) -> list:
    """The part of a leg's line still ahead of the vehicle at `now` (by planned times and distance)."""
    g, a, b = leg["geometry"], _ts(leg["planned_start"]), _ts(leg["planned_end"])
    if now >= b:
        return []
    if now <= a:
        return g
    seg = [_km(p, q) for p, q in zip(g, g[1:])]
    rem = (now - a) / (b - a) * sum(seg)
    for i, d in enumerate(seg):
        if rem <= d or i == len(seg) - 1:
            k = min(1.0, rem / d) if d else 0.0
            here = [g[i][0] + (g[i + 1][0] - g[i][0]) * k, g[i][1] + (g[i + 1][1] - g[i][1]) * k]
            return [here, *g[i + 1:]]
        rem -= d
    return []


def shipments() -> list[dict]:
    risk = {r["shipment_id"]: r for r in _rows("shipment_risk")}
    legs: dict[str, list] = {}
    for leg in sorted(_rows("legs"), key=lambda l: (l["shipment_id"], l["seq"])):
        legs.setdefault(leg["shipment_id"], []).append(leg)
    evs = {e["event_id"]: e for e in _rows("disruption_events")}
    starts = {i: e["window_start"] for i, e in evs.items()}
    import costing
    op, terms = costing.operator(), {t["shipment_id"]: t for t in optional_rows("shipment_terms")}
    out = []
    for s in _rows("shipments"):
        # A shipment with no risk row is "not scored", never shown as Clear.
        r = risk.get(s["shipment_id"], {"shipment_id": s["shipment_id"], "level": None,
                                        "reason": "Not scored yet", "event_ids": []})
        # impact_at: when the earliest linked event window opens. Used only to order the triage list.
        linked = [starts[i] for i in r["event_ids"] if i in starts]
        # wait_out: cost to sit out the linked event windows, from the rate tables (costing.py). An estimate.
        days = wait_out_days([evs[i] for i in r["event_ids"] if i in evs])
        wait = {"days": days, **costing.reschedule(s, days, op)} if days else None
        out.append({**s, "risk": r, "legs": legs.get(s["shipment_id"], []), "terms": terms.get(s["shipment_id"]),
                    "impact_at": min(linked, key=_ts) if linked else None, "wait_out": wait})
    return out


def shipment_detail(shipment_id: str) -> dict | None:
    s = next((x for x in shipments() if x["shipment_id"] == shipment_id), None)
    if not s:
        return None
    ids = set(s["risk"]["event_ids"])
    events = [e for e in _rows("disruption_events") if e["event_id"] in ids]
    evidence = [e for e in _rows("evidence") if e["event_id"] in ids]
    for e in events:
        e["basis"] = event_basis(e, [v for v in evidence if v["event_id"] == e["event_id"]])
    # Display aid only: which legs pass through a linked event's area. The level comes from the risk job.
    legs = [{**leg, "event_ids": [e["event_id"] for e in events if leg_in_area(leg, e)]} for leg in s["legs"]]
    return {**s, "legs": legs, "events": events, "evidence": evidence, "risk_check": _check(s["risk"], events, legs)}


def scenarios() -> list[dict]:
    """Tentative plans. Each change also carries before/after times: the shipment's planned start and ETA
    now, and the ETA shifted by delay_days. Nothing here is booked."""
    ships = {s["shipment_id"]: s for s in shipments()}
    all_changes, out = _rows("scenario_changes"), []
    for sc in _rows("scenarios"):
        changes = []
        for c in all_changes:
            if c["scenario_id"] != sc["scenario_id"]:
                continue
            s = ships.get(c["shipment_id"])
            before = after = None
            if s:
                start = s["legs"][0]["planned_start"] if s["legs"] else None
                before = {"planned_start": start, "eta": s["eta"], "risk_level": s["risk"]["level"]}
                after = {"planned_start": c.get("new_planned_start") or start,
                         "eta": _iso(_ts(s["eta"]) + timedelta(days=c.get("delay_days") or 0))}
            changes.append({**c, "before": before, "after": after})
        out.append({**sc, "changes": changes})
    return out


def agent_runs() -> list[dict]:
    """Monitor run records (CONTRACTS.md section 3), newest first. The table is optional: it is absent
    until the monitor has run, so a missing file or table means an empty list, not an error."""
    try:
        if use_databricks():
            cat, sch = os.environ.get("DATABRICKS_CATALOG", "main"), os.environ.get("DATABRICKS_SCHEMA", "portshift")
            with _SQL_LOCK:
                return _sql_query(f"SELECT * FROM {cat}.{sch}.agent_runs ORDER BY started_at DESC LIMIT 20")
        try:
            rows = json.loads((FIXTURES / "agent_runs.json").read_text())
        except OSError:
            rows = []
        rows = rows + [r for r in _live_rows("agent_runs") if live_dir().resolve() != FIXTURES.resolve()]
    except Exception:
        return []
    return sorted(rows, key=lambda r: r.get("started_at") or "", reverse=True)[:20]


def cost_rates() -> list[dict]:
    return _rows("cost_rates")


# ---- operator triage helpers (read-only over the contract tables) ----

def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _km(a, b) -> float:
    """Great-circle distance between two [lat, lon] points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def leg_in_area(leg: dict, event: dict, steps: int = 24, margin_km: float = 0.0) -> bool:
    """True if the leg's drawn line comes within the event's radius_km (plus margin_km), sampled along each segment."""
    centre, g = (event["lat"], event["lon"]), leg["geometry"]
    for p, q in zip(g, g[1:]):
        for i in range(steps + 1):
            k = i / steps
            if _km((p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k), centre) <= event["radius_km"] + margin_km:
                return True
    return False


def wait_out_days(events: list[dict]) -> int | None:
    """Days to wait out the linked event windows (same rule as the chat's reschedule estimate)."""
    if not events:
        return None
    span = max(_ts(e["window_end"]) for e in events) - min(_ts(e["window_start"]) for e in events)
    return max(1, math.ceil(span.total_seconds() / 86400))


def events() -> list[dict]:
    """Every disruption event with its evidence, basis and the shipments whose risk row links to it.
    Events with no evidence rows are dropped: no citation, no display."""
    evidence = _rows("evidence")
    hit: dict[str, list] = {}
    for s in shipments():
        for i in s["risk"]["event_ids"]:
            hit.setdefault(i, []).append({"shipment_id": s["shipment_id"], "level": s["risk"]["level"],
                                          "wait_out": s["wait_out"]})
    out = []
    for e in _rows("disruption_events"):
        ev = [v for v in evidence if v["event_id"] == e["event_id"]]
        if not ev:
            continue
        ships = sorted(hit.get(e["event_id"], []), key=lambda x: (-(x["level"] or 0), x["shipment_id"]))
        # exposure: summed wait-out estimate over the shipments it hits (illustrative rates)
        exposure = sum(x["wait_out"]["cost"] for x in ships if x["wait_out"])
        out.append({**e, "evidence": ev, "basis": event_basis(e, ev), "shipments": ships, "exposure": exposure})
    out.sort(key=lambda e: (e["status"] != "confirmed", -len(e["shipments"]), e["window_start"]))
    return out


def summary() -> dict:
    """Fleet statistics for the header strip. Counts only, plus one money figure: the cost to wait out the
    event window for every Severe or Critical shipment, from the rate tables (costing.py). Always an estimate."""
    ships, evs = shipments(), events()
    levels = {str(i): 0 for i in range(6)}  # "0" = not scored
    modes: dict[str, int] = {}
    exposure, priced, currency, own = 0.0, 0, "EUR", False
    for s in ships:
        lvl = s["risk"]["level"] or 0
        levels[str(lvl)] += 1
        modes[s["mode"]] = modes.get(s["mode"], 0) + 1
        if lvl >= 4 and s["wait_out"]:
            exposure += s["wait_out"]["cost"]
            priced, currency, own = priced + 1, s["wait_out"]["currency"], own or s["wait_out"]["cost_basis"] != "default"
    retrieved = sorted(v["retrieved_at"] for e in evs for v in e["evidence"])
    return {
        "source": source(),
        "shipments": len(ships), "levels": levels, "modes": modes,
        "affected": sum(1 for s in ships if (s["risk"]["level"] or 0) >= 2),
        "events": {"total": len(evs), "confirmed": sum(e["status"] == "confirmed" for e in evs),
                   "suspected": sum(e["status"] == "suspected" for e in evs),
                   "sample": sum(bool(e["is_fixture"]) for e in evs),
                   "live": sum(not e["is_fixture"] for e in evs), "samples_hidden": samples_hidden()},
        "exposure": {"amount": exposure, "currency": currency, "shipments": priced,
                     "basis": "cost to wait out the event window for every Severe or Critical shipment",
                     "note": "estimate, your rates where you have them" if own else "estimate, illustrative rates"},
        "evidence": {"newest_retrieved_at": retrieved[-1] if retrieved else None,
                     "oldest_retrieved_at": retrieved[0] if retrieved else None},
    }


# ---- reschedule options for one shipment, checked against the operator's limits ----

def _limits(preferences: dict | None) -> dict:
    p = {"max_risk": 3, "max_extra_cost": 5000.0, "max_delay_hours": None, **(preferences or {})}
    p["max_risk"] = min(5, max(1, int(p["max_risk"])))
    return p


def _evaluate(options: list[dict], p: dict) -> tuple[list[dict], str, str]:
    """Mark each option inside or outside the limits, and pick the cheapest inside them (the planner's rule)."""
    for o in options:
        v = []
        if o["resulting_risk"] > p["max_risk"]:
            v.append(f"risk level {o['resulting_risk']} is above your limit of {p['max_risk']}")
        if p["max_extra_cost"] is not None and o["extra_cost"] > p["max_extra_cost"]:
            v.append(f"extra cost EUR {o['extra_cost']:,.0f} is above your limit of EUR {p['max_extra_cost']:,.0f}")
        if p["max_delay_hours"] is not None and o["delay_hours"] > p["max_delay_hours"]:
            v.append(f"extra delay {o['delay_hours']:g} h is above your limit of {p['max_delay_hours']:g} h")
        o["violations"], o["within_limits"] = v, not v
    inside = [o for o in options if o["within_limits"]]
    if inside:
        best = min(inside, key=lambda o: (o["extra_cost"], o["resulting_risk"], o["delay_hours"]))
        return options, best["id"], "no_action_needed" if best["kind"] == "keep" else "within_limits"
    best = min(options, key=lambda o: (len(o["violations"]), o["resulting_risk"], o["extra_cost"]))
    return options, best["id"], "outside_limits"


def _fallback_options(shipment_id: str) -> dict | None:
    """Without the agent package: keep, or wait out the event window."""
    d = shipment_detail(shipment_id)
    if not d:
        return None
    level = d["risk"]["level"] or 1
    options = [{"id": "keep", "kind": "keep", "label": "Keep the current plan", "extra_cost": 0.0, "delay_hours": 0.0,
                "resulting_risk": level, "delay_days": 0, "extra_km": None, "new_planned_start": None,
                "detail": d["risk"]["reason"]}]
    if d["events"] and d["wait_out"]:
        days = d["wait_out"]["days"]
        start = _ts(d["legs"][0]["planned_start"]) if d["legs"] else None
        options.append({
            "id": f"reschedule-{days}d", "kind": "reschedule", "label": f"Reschedule by {days} day{'s' if days != 1 else ''}",
            "extra_cost": 0.0, "delay_hours": days * 24.0, "resulting_risk": 1, "delay_days": days,
            "extra_km": None, "new_planned_start": _iso(start + timedelta(days=days)) if start else None,
            "detail": "Waits out the event window. Assumes the window is not extended."})
    return {"shipment_id": shipment_id, "current_risk": level, "reason": d["risk"]["reason"], "options": options,
            "source": "fallback"}


def options(shipment_id: str, preferences: dict | None = None) -> dict | None:
    """Options for one shipment (keep / reschedule / reroute) with cost, how the cost was worked out, delay, risk
    after and whether each is inside the limits. Which options exist comes from agent.plan when the agent package
    is present (else keep or wait). Every option is priced here from the rate tables (costing.py), so the app
    shows one price for one option, with its lines. Nothing is written."""
    import costing
    p = _limits(preferences)
    ship = next((s for s in _rows("shipments") if s["shipment_id"] == shipment_id), None)
    if not ship:
        return None
    try:
        root = str(_here.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from agent import plan as agent_plan
        result = agent_plan.suggest_plan([shipment_id], agent_plan.Preferences.from_dict(p))
        out = {**result["shipments"][0], "source": "agent"}
    except Exception:
        out = _fallback_options(shipment_id)
    # Reroutes are searched for here (reroute.py: other crossings, other gateways, round the area), each checked by
    # the risk job, instead of taken from the planner's fixed table. There may be none.
    import reroute
    found = reroute.alternatives(shipment_id)
    out = {**out, "options": [o for o in out["options"] if o.get("kind") != "reroute"] + found["options"],
           "no_reroute": found["why_none"]}
    op = costing.operator()
    priced, best, status = _evaluate([reroute.price_ferries(ship, costing.price_option(ship, o, op), op) for o in out["options"]], p)
    terms = costing.terms_of(ship)
    return {**out, "options": priced, "recommended_id": best, "status": status, "currency": costing.CURRENCY,
            "terms": {k: terms.get(k) for k in ("carrier", "units", "unit_type", "promised_by", "late_penalty_per_day")}}
