"""Generate a SYNTHETIC extractor dataset per CONTRACTS.md section 4. Deterministic (seeded).

Row: {"input": {snippet, published_at, source_url}, "output": event | null, "synthetic": true}
Snippets are template-written, not scraped. source_url uses the reserved .invalid TLD.
Held-out uses different places AND different templates than train.
Usage: python finetune/make_dataset.py
  -> train.jsonl, heldout.jsonl (structured), adaption_train.jsonl, heldout_prompts.jsonl (prompt/completion)
"""
import json, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(7)
OUT = Path(__file__).parent

# (name, lat, lon)
PORTS_T = [("Port of Rotterdam", 51.95, 4.14), ("Port of Hamburg", 53.54, 9.97), ("Port of Antwerp", 51.27, 4.35), ("Port of Felixstowe", 51.96, 1.35),
           ("Port of Los Angeles", 33.73, -118.26), ("Port of Singapore", 1.26, 103.84), ("Yantian Port", 22.57, 114.28),
           ("Port of Valencia", 39.45, -0.32), ("Port of Genoa", 44.41, 8.92), ("Port of Santos", -23.98, -46.30)]
PORTS_H = [("Port of Gdansk", 54.40, 18.67), ("Port of Busan", 35.10, 129.04), ("Port of Piraeus", 37.94, 23.64), ("Port of Durban", -29.87, 31.03)]
ROADS_T = [("A7 near Lyon", 45.76, 4.84), ("M25 near Dartford", 51.45, 0.25), ("A2 near Duisburg", 51.43, 6.76), ("I-5 near Sacramento", 38.58, -121.49), ("A1 near Milan", 45.46, 9.19)]
ROADS_H = [("E4 near Helsingborg", 56.05, 12.69), ("N1 near Pretoria", -25.75, 28.19)]
AIR_T = [("Frankfurt Airport", 50.04, 8.56), ("Heathrow Airport", 51.47, -0.45), ("Schiphol Airport", 52.31, 4.76), ("Changi Airport", 1.36, 103.99)]
AIR_H = [("Incheon Airport", 37.46, 126.44), ("Munich Airport", 48.35, 11.79)]

SRC = ["the port authority said", "according to the operator", "the transport ministry said", "Reuters reported", "local media reported", "union officials said"]
SITES = ["samplenews", "portwire", "freightdesk", "logisticsdaily"]

def iso(d): return d.strftime("%Y-%m-%dT00:00:00Z")

def make(typ, loc, summary, start, end, snippet, pub):
    url = f"https://{random.choice(SITES)}.invalid/{random.randint(1000, 9999)}"
    out = None if typ is None else {"type": typ, "location": {"name": loc[0], "lat": loc[1], "lon": loc[2]},
                                     "window": {"start": iso(start) if start else None, "end": iso(end) if end else None},
                                     "summary": summary, "source_url": url, "published_at": pub.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return {"input": {"snippet": snippet, "published_at": pub.strftime("%Y-%m-%dT%H:%M:%SZ"), "source_url": url}, "output": out, "synthetic": True}

def when():
    pub = datetime(2026, 11, random.randint(1, 20), random.randint(6, 20), tzinfo=timezone.utc)
    return pub, pub.replace(hour=0) + timedelta(days=random.randint(1, 4))

def strike(loc, t):
    pub, start = when(); hrs = random.choice([24, 48, 72]); end = start + timedelta(hours=hrs); s = random.choice(SRC)
    if t == 0:
        sn = f"Dockworkers at the {loc[0]} will begin a {hrs}-hour strike on {start:%A %d %B}, halting cargo handling, {s}."
        return make("strike", loc, f"{hrs}-hour strike halts cargo handling at {loc[0]}.", start, end, sn, pub)
    if t == 1:
        wk = start + timedelta(days=5)
        sn = f"Unions warned they may walk out at the {loc[0]} around {wk:%d %B} if talks fail, {s}."
        return make("warning", loc, f"Possible strike at {loc[0]} if talks fail.", wk, None, sn, pub)
    sn = f"Strike action will shut {loc[0]} terminals from {start:%d %B}; a {hrs}-hour stoppage is planned, {s}."
    return make("strike", loc, f"Planned {hrs}-hour stoppage at {loc[0]} terminals.", start, end, sn, pub)

def road(loc, t):
    pub, start = when(); s = random.choice(SRC); cause = random.choice(["a lorry fire", "a bridge inspection", "flooding", "a multi-vehicle crash"])
    if t == 0:
        sn = f"The {loc[0]} is closed in both directions after {cause}; reopening is expected {start:%A %d %B}, {s}."
        return make("closure", loc, f"{loc[0]} closed after {cause}.", pub.replace(hour=0), start, sn, pub)
    sn = f"Drivers face long delays on the {loc[0]} as {cause} blocks lanes, {s}."
    return make("congestion", loc, f"Delays on {loc[0]} due to {cause}.", pub.replace(hour=0), None, sn, pub)

def airport(loc, t):
    pub, start = when(); s = random.choice(SRC)
    if t == 0:
        sn = f"Air traffic controllers at {loc[0]} are balloting on industrial action with no dates set, {s}."
        return make("warning", loc, f"Controllers at {loc[0]} balloting on industrial action; no dates set.", None, None, sn, pub)
    sn = f"{loc[0]} suspended all cargo flights on {start:%A %d %B} due to a runway fault, {s}."
    return make("closure", loc, f"Cargo flights suspended at {loc[0]} due to runway fault.", start, None, sn, pub)

def weather(loc, t):
    pub, start = when(); s = random.choice(SRC)
    if t == 0:
        sn = f"A storm warning is in force for {loc[0]}; vessel operations suspended from {start:%d %B}, {s}."
        return make("weather", loc, f"Vessel operations at {loc[0]} suspended for storm.", start, None, sn, pub)
    sn = f"Forecasters say a storm could disrupt shipping near {loc[0]} around {start:%d %B}, {s}."
    return make("weather", loc, f"Possible storm disruption near {loc[0]}.", start, None, sn, pub)

NEG = ["Shares of the logistics firm rose {n}% after quarterly results beat expectations.",
       "The company opened a new warehouse near {c} and plans to hire {n}0 staff.",
       "{p} reported record container volumes last quarter, up {n}% year on year.",
       "Analysts expect freight rates to stay flat through the winter.",
       "The mayor of {c} unveiled a cycling plan for the city centre.",
       "{p} signed a long-term green fuel agreement with two shipping lines."]

def negative(pool):
    loc = random.choice(pool); pub, _ = when()
    return make(None, loc, "", None, None, random.choice(NEG).format(n=random.randint(2, 9), c=loc[0].split()[-1], p=loc[0]), pub)

def build(ports, roads, air, tmpl, n_neg, per):
    rows = []
    for fn, pool in ((strike, ports), (road, roads), (airport, air), (weather, ports)):
        for loc in pool:
            for _ in range(per):
                rows.append(fn(loc, random.choice(tmpl[fn.__name__])))
    rows += [negative(ports + roads + air) for _ in range(n_neg)]
    random.shuffle(rows)
    return rows

TRAIN_T = {"strike": [0, 1], "road": [0], "airport": [0], "weather": [0]}
HELD_T = {"strike": [2], "road": [1], "airport": [1], "weather": [1]}

def dump(name, rows):
    seen, out = set(), []
    for r in rows:
        k = r["input"]["snippet"]
        if k not in seen: seen.add(k); out.append(r)
    (OUT / name).write_text("".join(json.dumps(r) + "\n" for r in out)); print(name, len(out)); return out

train = dump("train.jsonl", build(PORTS_T, ROADS_T, AIR_T, TRAIN_T, 300, 45))
trs = {r["input"]["snippet"] for r in train}
held = dump("heldout.jsonl", [r for r in build(PORTS_H, ROADS_H, AIR_H, HELD_T, 20, 8) if r["input"]["snippet"] not in trs])

# Adaption raw-dataset export: one row per example with `prompt` and `completion` text columns
# (upload with column_mapping={"prompt": "prompt", "completion": "completion"}; SFT needs >= 1000 rows).
INSTRUCTION = ("Extract the logistics disruption from the news snippet. Reply with one JSON object with keys "
               "type, location{name,lat,lon}, window{start,end}, summary, source_url, published_at, "
               "or the word null if the snippet describes no disruption. Allowed type values: "
               "strike, closure, weather, warning, congestion, other.")
def prompt_of(inp):
    return f"{INSTRUCTION}\n\nPublished: {inp['published_at']}\nSource: {inp['source_url']}\nSnippet: {inp['snippet']}"
def completion_of(out):
    return "null" if out is None else json.dumps(out, separators=(",", ":"))
(OUT / "adaption_train.jsonl").write_text("".join(
    json.dumps({"prompt": prompt_of(r["input"]), "completion": completion_of(r["output"])}) + "\n" for r in train))
(OUT / "heldout_prompts.jsonl").write_text("".join(
    json.dumps({"prompt": prompt_of(r["input"]), "completion": completion_of(r["output"])}) + "\n" for r in held))
print("adaption_train.jsonl", len(train), "rows")
