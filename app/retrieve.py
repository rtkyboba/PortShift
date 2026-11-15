"""Retrieval for Ask PortShifter: find the records a question is about, so the answer is written from them.

Every table the app holds becomes a set of small records: a shipment, a disruption, a source cited for a disruption
(with its URL), a stock line, a dispatch order, a planned shipment, a rate, a reported market rate. search() ranks
them for a question and returns the best few, then follows the links between them: a shipment brings its
disruptions, a disruption brings its sources and the shipments it hits. The model is given those records and
nothing else from the tables, and the sources among them are what the answer cites.

Ranking is hybrid: two rankings of the same records, fused.
  * BM25 over words, plus a boost when the question names a record's id, place or carrier. Exact and cheap: it finds
    "S-1007", "Felixstowe", "reefer".
  * Embeddings (embeddings.py): the question and every record as vectors, ranked by cosine similarity. It finds a
    record that says the same thing in other words ("booze" for whisky, "held up" for a strike).
  * Reciprocal rank fusion: each record scores 1 / (60 + its rank) in each list, summed, so a record high in either
    list comes up and one high in both comes first. No tuning of weights between two different kinds of score.
With no embedding provider configured the ranking is BM25 alone, and the result says which method was used. The
vectors are kept in memory (the tables are small: no vector store).
"""
import math
import re
import time

import costing
import data
import embeddings

NAMES = {0: "Not scored", 1: "Clear", 2: "Watch", 3: "At risk", 4: "Severe", 5: "Critical"}
_STOP = set("""the a an and or of to in on at by for from with is are was be it this that these those all any some my our your me i we you do does did
can could will would should have has had not no how many much what which when where why who tell show give about there here""".split())


def _words(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9\-]*", str(text).lower()):
        if w in _STOP:
            continue
        out.append(w)
        if len(w) > 4 and w.endswith("s"):
            out.append(w[:-1])  # shipments ~ shipment, strikes ~ strike
    return out


def _when(iso) -> str:
    return str(iso or "")[:16].replace("T", " ") + " UTC" if iso else "not set"


KEEP_SECONDS = 90
_kept: dict = {"at": 0.0, "key": None, "docs": None}


def forget() -> None:
    """Drop the kept records (after something that changes the tables: a dispatch, a live check, new rates)."""
    _kept["docs"] = None


def documents(planned: list[dict] | None = None) -> list[dict]:
    """Every record as {id, kind, title, text, links: [ids], citation?}. Reading every table takes a moment on a real
    warehouse, so the records are kept for a short time and built again when they are older than that."""
    key = (data.source(), tuple(p.get("plan_id") for p in planned or []), data._now().strftime("%Y-%m-%dT%H") if data.source() != "databricks" else "")
    if _kept["docs"] is not None and _kept["key"] == key and time.time() - _kept["at"] < KEEP_SECONDS:
        return _kept["docs"]
    docs = _build(planned)
    _kept.update(at=time.time(), key=key, docs=docs)
    return docs


def _build(planned: list[dict] | None) -> list[dict]:
    docs = []
    ships, events = data.shipments(), data.events()
    for s in ships:
        t = s.get("terms") or {}
        stops = [s["legs"][0]["from_name"], *[l["to_name"] for l in s["legs"]]] if s["legs"] else []
        text = (f"Shipment {s['shipment_id']}: {s['cargo']}, {s['origin']} to {s['destination']} by {s['mode']}"
                + (f", calling at {', '.join(stops[1:-1])}" if len(stops) > 2 else "") + f". Planned arrival {_when(s['eta'])}. "
                f"Risk level {s['risk']['level']} {NAMES[s['risk']['level'] or 0]}: {s['risk']['reason']}."
                + (f" Carrier {t['carrier']}." if t.get("carrier") else "")
                + (f" Promised to the customer by {_when(t['promised_by'])}, late penalty EUR {t['late_penalty_per_day']:,.0f} per day." if t.get("promised_by") else "")
                + (f" Waiting out the disruption ({s['wait_out']['days']} days) would cost about EUR {s['wait_out']['cost']:,.0f} (estimate)." if s.get("wait_out") else ""))
        docs.append({"id": s["shipment_id"], "kind": "shipment", "title": f"{s['shipment_id']} {s['origin']} to {s['destination']}", "text": text,
                     "links": list(s["risk"]["event_ids"]), "keys": [s["shipment_id"], s["origin"], s["destination"], *stops, t.get("carrier") or ""]})
    for e in events:
        hits = [x["shipment_id"] for x in e["shipments"]]
        text = (f"Disruption {e['event_id']}: {e['type']} at {e['location']}, {e['status']}{' (sample event)' if e['is_fixture'] else ''}. {e['summary']} "
                f"Window {_when(e['window_start'])} to {_when(e['window_end'])}. Basis: {e['basis']['text']}. "
                + (f"Hits {', '.join(hits)}." if hits else "Hits no shipment."))
        docs.append({"id": e["event_id"], "kind": "disruption", "title": f"{e['type'].capitalize()} at {e['location']}", "text": text,
                     "links": hits + [v["evidence_id"] for v in e["evidence"]], "keys": [e["event_id"], e["location"], e["type"]]})
        for v in e["evidence"]:
            docs.append({"id": v["evidence_id"], "kind": "source", "title": v["title"],
                         "text": f"Source for {e['type']} at {e['location']} ({v['domain']}{', official' if v.get('is_official') else ''}, retrieved {_when(v['retrieved_at'])}): {v['claim']}",
                         "links": [e["event_id"]], "keys": [e["location"], v["domain"]],
                         "citation": {k: v[k] for k in ("claim", "url", "title", "retrieved_at", "published_at")}})
    try:
        import stock
        view = stock.view()
        for w in view["warehouses"]:
            for r in w["lines"]:
                docs.append({"id": r["stock_id"], "kind": "stock", "title": f"{r['item']} at {w['warehouse']}",
                             "text": f"Stock {r['stock_id']} at {w['warehouse']}: {r['item']} ({r['sku']}), {r['available']} of {r['quantity']} {r['unit']}s available, "
                                     f"{r['reserved']} allocated, {r['kg_per_unit']} kg each{' (sample stock)' if r.get('is_sample') else ''}.",
                             "links": [], "keys": [w["warehouse"], r["item"], r["sku"]]})
        for o in view["orders"]:
            docs.append({"id": o["order_id"], "kind": "dispatch order", "title": f"{o['order_id']} {o['warehouse']} to {o['destination']}",
                         "text": f"Dispatch order {o['order_id']}: {', '.join(str(l['quantity']) + ' ' + l['unit'] + 's ' + l['item'] for l in o['lines'])} from {o['warehouse']} to "
                                 f"{o['destination']}, {o['route_label']}, status {o['status']}, leaves {_when(o['depart_at'])}, arrives {_when(o['eta'])}, about EUR {o['cost']:,.0f}.",
                         "links": [l["stock_id"] for l in o["lines"]], "keys": [o["order_id"], o["warehouse"], o["destination"]]})
    except Exception:
        pass
    for p in planned or []:
        docs.append({"id": p["plan_id"], "kind": "planned shipment", "title": f"{p['plan_id']} {p.get('label', '')}",
                     "text": f"Planned shipment {p['plan_id']} (tentative, not booked): {p.get('label', '')}, {p.get('route_label', '')}, leaves {_when(p.get('depart_at'))}, "
                             f"arrives {_when(p.get('eta'))}" + (f", must arrive by {_when(p['arrive_by'])}" if p.get("arrive_by") else "")
                             + (f", about EUR {p['cost']:,.0f} (estimate)" if p.get("cost") is not None else "") + ".",
                     "links": [], "keys": [p["plan_id"], p.get("label", "")]})
    op = costing.operator()
    for src, rows in (("your own rate", op["rate_cards"]), ("default rate, illustrative", costing.defaults("rate_cards"))):
        for r in rows:
            lane = f"{r.get('origin') or 'any origin'} to {r.get('destination') or 'any destination'}"
            docs.append({"id": r["rate_id"], "kind": "rate", "title": f"{r['partner']} {r['mode']} rate",
                         "text": f"Rate {r['rate_id']} ({src}): {r['partner']}, {r['mode']}, {lane}, EUR {r['base_rate']:g} per {costing.UNITS.get(r['unit'], r['unit'])}"
                                 + (f" plus EUR {r['per_km']:g} per km" if r.get("per_km") else "") + (f", minimum EUR {r['min_charge']:g}" if r.get("min_charge") else "") + ".",
                         "links": [], "keys": [r["partner"], r["mode"]]})
    for r in data.optional_rows("market_rates"):
        docs.append({"id": r["rate_id"], "kind": "market rate", "title": r["title"],
                     "text": f"Reported market rate ({r['domain']}{', sample' if r.get('is_fixture') else ''}; a benchmark, never used to price a shipment): {r['claim']}",
                     "links": [], "keys": [r.get("mode", "")],
                     "citation": {k: r[k] for k in ("claim", "url", "title", "retrieved_at", "published_at")}})
    return docs


RRF_K = 60
EMBED_TOP = 10      # the embedding list contributes its best few only...
EMBED_BAND = 0.10   # ...and only those within this much of its best match: similarity scores sit close together,
MIN_COSINE = 0.5    # so "near the top" says more than any fixed level; below this floor nothing counts


def _bm25(question: str, docs: list[dict]) -> list[float]:
    q = _words(question)
    toks = [_words(d["text"] + " " + d["title"]) for d in docs]
    n, avg = len(docs), sum(len(t) for t in toks) / max(1, len(docs))
    df: dict[str, int] = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    low = question.lower()
    scores = []
    for d, t in zip(docs, toks):
        tf: dict[str, int] = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        score = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(t) / avg)) for w in set(q) if w in tf)
        if d["id"].lower() in low:
            score += 8  # the question names this record
        score += 2.5 * sum(1 for key in d.get("keys", []) if key and len(key) > 3 and key.lower() in low)
        scores.append(score)
    return scores


def search(question: str, docs: list[dict], k: int = 8, limit: int = 14) -> list[dict]:
    """The records for a question: the k best by the fused ranking, then the records they link to. Each comes back
    with its BM25 score, its cosine similarity (None without embeddings), its fused score and the method used."""
    if not question.strip() or not docs:
        return []
    bm25 = _bm25(question, docs)
    n = len(docs)
    first = embeddings.provider()
    vectors = embeddings.embed([d["title"] + ". " + d["text"] for d in docs])
    query = embeddings.embed([question], kind="query") if vectors else None
    if vectors and embeddings.provider() != first:  # the provider changed between the two calls: the vectors do not match
        vectors = embeddings.embed([d["title"] + ". " + d["text"] for d in docs])
        query = embeddings.embed([question], kind="query") if vectors else None
    cos = [embeddings.cosine(query[0], v) for v in vectors] if vectors and query else None
    method = "hybrid" if cos else "bm25"
    by_bm25 = sorted(range(n), key=lambda i: -bm25[i])
    fused = [0.0] * n
    for rank, i in enumerate(by_bm25):
        if bm25[i] > 0:
            fused[i] += 1 / (RRF_K + rank + 1)
    if cos:
        by_cos = sorted(range(n), key=lambda i: -cos[i])
        floor = max(MIN_COSINE, cos[by_cos[0]] - EMBED_BAND)
        for rank, i in enumerate(by_cos[:EMBED_TOP]):
            if cos[i] >= floor:
                fused[i] += 1 / (RRF_K + rank + 1)
    order = sorted(range(n), key=lambda i: (-fused[i], -bm25[i]))
    top = [i for i in order[:k] if fused[i] > 0]
    by_id = {d["id"]: i for i, d in enumerate(docs)}
    chosen = list(top)
    for i in top[:4]:  # follow the links of the best few: a shipment's disruptions, a disruption's sources and shipments
        for link in docs[i]["links"]:
            j = by_id.get(link)
            if j is not None and j not in chosen:
                chosen.append(j)
                for more in docs[j]["links"] if docs[j]["kind"] == "disruption" else []:
                    m = by_id.get(more)
                    if m is not None and m not in chosen and docs[m]["kind"] == "source":
                        chosen.append(m)
    return [{**docs[i], "score": round(bm25[i], 2), "cosine": round(cos[i], 3) if cos else None, "fused": round(fused[i], 4),
             "method": method} for i in chosen[:limit]]
