"""Extractor v2 training data: synthetic web search results shaped like real Linkup output, with exact labels.

    python finetune/v2/make_dataset_v2.py            # writes finetune/v2/train_v2.jsonl and heldout_v2.jsonl

Why: on real Linkup results most hits are NOT disruptions (statistics, state aid, recovery news, profiles, link
lists, other meanings of "strike"), and the v1 data had almost none of these. Every row here is generated from a
fact sheet, so its label is exact; nothing is copied from the real eval set (finetune/real), and every source is
on the reserved .invalid TLD or a generic site name, so no row can pass as a real article.

Rows use the live extractor's own prompt (agent.extract.training_prompt) and its strict output schema, so a
fine-tune can be dropped into agent/extract.py unchanged. Completion: the JSON object, or the word null.
Held-out rows use places and template variants never used in training.
"""
import json
import pathlib
import random
import sys
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.extract import training_prompt  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent
R = random.Random(20261115)

# ---- places ------------------------------------------------------------------------------------------------
# (English name, local-language name or None, short name, kind)
PORTS = [
    ("Port of Felixstowe", None, "Felixstowe", "port"), ("Port of Southampton", None, "Southampton", "port"),
    ("Port of Le Havre", "port du Havre", "Le Havre", "port"), ("Port of Marseille-Fos", "port de Marseille-Fos", "Marseille", "port"),
    ("Port of Genoa", "porto di Genova", "Genoa", "port"), ("Port of Valencia", "puerto de Valencia", "Valencia", "port"),
    ("Port of Algeciras", "puerto de Algeciras", "Algeciras", "port"), ("Port of Piraeus", None, "Piraeus", "port"),
    ("Port of Gdansk", "port Gdańsk", "Gdansk", "port"), ("Port of Bremerhaven", "Hafen Bremerhaven", "Bremerhaven", "port"),
    ("Port of Zeebrugge", "haven van Zeebrugge", "Zeebrugge", "port"), ("Port of Dover", None, "Dover", "port"),
    ("Port of Busan", None, "Busan", "port"), ("Port of Ningbo-Zhoushan", None, "Ningbo", "port"),
    ("Port of Shanghai", None, "Shanghai", "port"), ("Yantian port", None, "Yantian", "port"),
    ("Port of Hong Kong", None, "Hong Kong", "port"), ("Port Klang", None, "Port Klang", "port"),
    ("Port of Colombo", None, "Colombo", "port"), ("Jebel Ali", None, "Jebel Ali", "port"),
    ("Port of Santos", "porto de Santos", "Santos", "port"), ("Port of Savannah", None, "Savannah", "port"),
    ("Port of New York and New Jersey", None, "New York", "port"), ("Port of Houston", None, "Houston", "port"),
    ("Port of Vancouver", None, "Vancouver", "port"), ("Port of Montreal", "port de Montréal", "Montreal", "port"),
    ("Port of Rotterdam", "haven van Rotterdam", "Rotterdam", "port"), ("Port of Hamburg", "Hamburger Hafen", "Hamburg", "port"),
    ("Port of Antwerp-Bruges", "haven van Antwerpen", "Antwerp", "port"), ("Port of Singapore", None, "Singapore", "port"),
]
WATERWAYS = [("Suez Canal", None, "Suez", "canal"), ("Panama Canal", "Canal de Panamá", "Panama", "canal"),
             ("Kiel Canal", "Nord-Ostsee-Kanal", "Kiel", "canal"), ("Strait of Hormuz", None, "Hormuz", "strait"),
             ("Bosphorus", None, "Bosphorus", "strait"), ("Red Sea", None, "Red Sea", "sea lane"),
             ("Strait of Malacca", None, "Malacca", "strait"), ("Rhine at Kaub", "Rhein bei Kaub", "Kaub", "river")]
AIRPORTS = [("Amsterdam Schiphol Airport", "luchthaven Schiphol", "Schiphol", "airport"),
            ("Frankfurt Airport", "Flughafen Frankfurt", "Frankfurt", "airport"), ("Liege Airport", "aéroport de Liège", "Liège", "airport"),
            ("Leipzig/Halle Airport", "Flughafen Leipzig/Halle", "Leipzig", "airport"), ("Heathrow Airport", None, "Heathrow", "airport"),
            ("Hong Kong International Airport", None, "Hong Kong airport", "airport"), ("Memphis International Airport", None, "Memphis", "airport")]
ROADS = [("Brenner Pass", "Brennerpass", "Brenner", "road"), ("Mont Blanc Tunnel", "tunnel du Mont-Blanc", "Mont Blanc", "tunnel"),
         ("Fréjus Road Tunnel", "tunnel du Fréjus", "Fréjus", "tunnel"), ("Øresund Bridge", "Øresundsbron", "Øresund", "bridge"),
         ("M20 in Kent", None, "M20", "road"), ("Ambassador Bridge", None, "Ambassador Bridge", "bridge"),
         ("Van Brienenoord Bridge", "Van Brienenoordbrug", "Brienenoord", "bridge"), ("A1 motorway near Lyon", "autoroute A1 près de Lyon", "A1", "road"),
         ("Severn Bridge", None, "Severn", "bridge"), ("Rader Hochbrücke", None, "Rader Hochbrücke", "bridge")]
RAIL = [("Gotthard Base Tunnel", "Gotthard-Basistunnel", "Gotthard", "rail"), ("Betuweroute", None, "Betuwe line", "rail"),
        ("Channel Tunnel", "tunnel sous la Manche", "Eurotunnel", "rail"), ("Rhine-Alpine rail corridor", None, "Rhine-Alpine corridor", "rail"),
        ("Duisburg intermodal terminal", None, "Duisburg", "rail"), ("Lille-Europe station", "gare de Lille-Europe", "Lille", "rail")]
BORDERS = [("Koroszczyn border crossing", None, "Koroszczyn", "border"), ("Otay Mesa crossing", None, "Otay Mesa", "border"),
           ("Laredo World Trade Bridge", None, "Laredo", "border"), ("Kapikule border crossing", None, "Kapikule", "border")]
NEAR_PORT_ROADS = [  # a road or bridge named near a port: the event is at the road, never the port
    ("Van Brienenoord Bridge", "Rotterdam"), ("A12 near Felixstowe", "Felixstowe"), ("Rader Hochbrücke", "Kiel"),
    ("A7 Elbe Tunnel", "Hamburg"), ("Kennedy Tunnel", "Antwerp"), ("I-710 freeway", "Long Beach"),
    ("Pont de Normandie", "Le Havre"), ("A14 near Ipswich", "Felixstowe")]
HELDOUT_PLACES = {"Port of Montreal", "Kiel Canal", "Memphis International Airport", "Severn Bridge",
                  "Lille-Europe station", "Kapikule border crossing", "Port of Santos", "I-710 freeway"}

UNIONS = ["dockworkers' union", "port workers' union", "lashers' union", "pilots' association", "crane operators",
          "customs officers", "air cargo handlers", "rail freight drivers", "lock keepers", "tugboat crews", "truck drivers"]
CARRIERS = ["Nordline", "Asterion Shipping", "Pacific Crest Lines", "Meridian Container", "Bluewake Logistics",
            "Harbourstone", "TransOcean Global", "Eastgate Freight"]
NEWS_SITES = ["portwire.invalid", "freightdesk.invalid", "logisticsdaily.invalid", "maritimebrief.invalid",
              "supplychainnow.invalid", "cargonews.invalid", "harbourtimes.invalid", "shippingweekly.invalid",
              "localnews-nord.invalid", "regionalpost.invalid", "tradewatch.invalid", "carrier-advisory.invalid"]
OFFICIAL_SITES = ["port-authority.invalid", "transport-ministry.invalid", "canal-authority.invalid", "coastguard.invalid"]
PROFILE_SITES = ["profiles.invalid", "careers.invalid", "linkedin-style.invalid"]
JUNK_SITES = ["aggregator.invalid", "newslist.invalid", "content-farm.invalid", "travelblog.invalid", "forum.invalid"]

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
MONTHS_NL = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

NAV = ["Home | News | Ports | Shipping | Subscribe | Sign in", "Share on X · Facebook · LinkedIn · Email · Print",
       "Cookie settings Accept all Reject", "Advertisement", "Related articles", "Read more »", "Menu Search Login Register",
       "Newsletter: get the daily brief, free, unsubscribe anytime", "Navigation anzeigen bzw. verbergen Suche Anmelden",
       "Lees ook: | Meer nieuws | Video", "Suivre sur Google News · Lire dans l'app", "Most read · Latest · Trending"]


def d(day: date) -> str:
    return day.isoformat()


def human(day: date, lang="en", style=None) -> str:
    style = style or R.choice(["dmy", "md", "wd"])
    if lang == "de":
        return f"{day.day}. {MONTHS_DE[day.month - 1]}"
    if lang == "fr":
        return f"{day.day} {MONTHS_FR[day.month - 1]}"
    if lang == "nl":
        return f"{day.day} {MONTHS_NL[day.month - 1]}"
    if lang == "es":
        return f"{day.day} de {MONTHS_ES[day.month - 1]}"
    if style == "md":
        return f"{MONTHS[day.month - 1]} {day.day}"
    if style == "wd":
        return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"
    return f"{day.day} {MONTHS[day.month - 1]}"


def pick(pool, heldout: bool):
    choices = [p for p in pool if (p[0] in HELDOUT_PLACES) == heldout] or pool
    return R.choice(choices)


def noisy(text: str, junk=0.35) -> str:
    """Wrap text in the page clutter real search results carry."""
    parts = [text]
    if R.random() < junk:
        parts.insert(0, R.choice(NAV))
    if R.random() < junk:
        parts.append(R.choice(NAV))
    if R.random() < 0.2:  # truncated duplicate, as search snippets often repeat the lead
        parts.append("... " + text[: R.randint(60, 160)])
    return " ".join(parts)


def item(text, title, site, published: date):
    return {"url": f"https://{site}/{R.randint(1000, 99999)}", "domain": site, "title": title,
            "snippet": noisy(text), "published_at": d(published) + "T00:00:00Z"}


def event(kind, name, start: date | None, end: date | None, summary):
    return {"type": kind, "location": {"name": name}, "window": {"start": d(start) if start else None,
                                                                  "end": d(end) if end else None}, "summary": summary}


# ---- events (positives) ------------------------------------------------------------------------------------
def pos_strike(pub, ho):
    p = pick(PORTS + AIRPORTS + RAIL, ho)
    s = pub + timedelta(days=R.randint(-2, 10)); n = R.randint(1, 4); e = s + timedelta(days=n - 1)
    u = R.choice(UNIONS)
    lang = R.choice(["en"] * 6 + ["de", "fr", "nl", "es"])
    if lang == "de" and p[1]:
        text = f"Die Beschäftigten im {p[1]} legen vom {human(s, 'de')} bis {human(e, 'de')} die Arbeit nieder, teilte die Gewerkschaft mit. Der Containerumschlag wird stillstehen."
    elif lang == "fr" and p[1]:
        text = f"Grève au {p[1]} : les {u} ont appelé à un arrêt de travail du {human(s, 'fr')} au {human(e, 'fr')}, les opérations de manutention seront fortement perturbées."
    elif lang == "nl" and p[1]:
        text = f"Medewerkers in de {p[1]} staken van {human(s, 'nl')} tot en met {human(e, 'nl')}, meldt de vakbond. Containerterminals liggen stil."
    elif lang == "es" and p[1]:
        text = f"Los estibadores del {p[1]} irán a la huelga del {human(s, 'es')} al {human(e, 'es')}, paralizando la carga y descarga de contenedores."
    else:
        text = R.choice([
            f"{u.capitalize()} at {p[0]} will strike from {human(s)} to {human(e)}, halting cargo handling, the union said.",
            f"A {n * 24}-hour walkout by {u} at {p[0]} begins on {human(s)}. Operators warned customers to expect delays.",
            f"Industrial action at {p[0]}: {u} have confirmed stoppages on {human(s)}" + (f" and {human(e)}." if n > 1 else "."),
            f"Cargo operations at {p[0]} stopped on {human(s)} as {u} walked out over pay; the strike is due to last {n} day{'s' if n > 1 else ''}.",
        ])
    summ = f"{u.capitalize()} strike at {p[0]} from {human(s, style='dmy')} to {human(e, style='dmy')}." if n > 1 else f"{u.capitalize()} strike at {p[0]} on {human(s, style='dmy')}."
    return text, f"Strike at {p[2]} {R.choice(['set to halt operations', 'confirmed', 'begins', 'hits cargo'])}", R.choice(NEWS_SITES), event("strike", p[0], s, e, summ)


def pos_warning(pub, ho):
    p = pick(PORTS + AIRPORTS + RAIL + BORDERS, ho)
    u = R.choice(UNIONS); dl = pub + timedelta(days=R.randint(3, 15))
    variant = R.random()
    if variant < 0.45:
        text = R.choice([
            f"Employers and {u} at {p[0]} extended their contract through {human(dl)}, deferring a strike for the {R.choice(['second', 'third'])} time as talks continue.",
            f"A threatened walkout at {p[0]} has been postponed until {human(dl)}, giving negotiators more time; operations continue normally for now.",
            f"The strike deadline at {p[0]} was pushed back to {human(dl)} after mediators intervened. A stoppage remains possible if talks fail.",
        ])
        summ = f"Threatened strike at {p[0]} deferred to {human(dl, style='dmy')}."
        ev = event("warning", p[0], dl, None, summ)
    elif variant < 0.75:
        text = R.choice([
            f"{u.capitalize()} at {p[0]} are balloting members on industrial action; no dates have been set, officials said.",
            f"Unions at {p[0]} have threatened strikes over automation plans but have not named any dates.",
        ])
        summ = f"{u.capitalize()} at {p[0]} balloting on industrial action; no dates set."
        ev = event("warning", p[0], pub, None, summ)
    else:
        text = f"The authority issued an alert that operations at {p[0]} may be restricted from {human(dl)} because of {R.choice(['expected high winds', 'planned security exercises', 'a possible system outage', 'forecast fog'])}."
        summ = f"Official alert of possible restrictions at {p[0]} from {human(dl, style='dmy')}."
        ev = event("warning", p[0], dl, None, summ)
    return text, f"{p[2]}: {R.choice(['strike threat deferred', 'unions ballot', 'operations alert', 'talks extended'])}", R.choice(NEWS_SITES + OFFICIAL_SITES), ev


CLOSURE_REASONS = {
    "port": ["a cyberattack on the terminal operating system", "a fire at a warehouse", "a security incident",
             "a power failure", "a police operation", "a crane collapse"],
    "canal": ["a collision that damaged a lock gate", "emergency repairs to a lock", "a grounded vessel"],
    "strait": ["a naval exercise", "a security incident", "a grounded tanker"],
    "sea lane": ["a naval exercise", "a security incident"],
    "river": ["emergency repairs to a lock", "a collision that damaged a lock gate"],
    "airport": ["a drone sighting", "a bomb alert", "a fire in the cargo terminal", "a power failure"],
    "road": ["a landslide", "a serious crash", "emergency repairs", "a police operation"],
    "tunnel": ["a truck fire", "emergency repairs", "a safety inspection that found cracks"],
    "bridge": ["a ship strike on a pier", "emergency repairs", "a serious crash"],
    "rail": ["a bomb alert", "a derailment", "a signalling failure", "emergency repairs"],
    "border": ["a system outage at customs", "a protest blocking the crossing", "a police operation"],
}
CLOSURE_VERBS = {"port": "vessels and trucks", "canal": "ships", "strait": "ships", "sea lane": "ships", "river": "barges",
                 "airport": "cargo flights", "road": "trucks", "tunnel": "trucks", "bridge": "trucks", "rail": "trains",
                 "border": "trucks"}


def pos_closure(pub, ho):
    p = pick(PORTS + WATERWAYS + AIRPORTS + ROADS + RAIL + BORDERS, ho)
    s = pub + timedelta(days=R.randint(-1, 6))
    reason = R.choice(CLOSURE_REASONS[p[3]]); who = CLOSURE_VERBS[p[3]]
    open_end = R.random() < 0.5
    e = None if open_end else s + timedelta(days=R.randint(0, 5))
    text = R.choice([
        f"{p[0]} was closed on {human(s)} after {reason}" + (", and authorities said it would stay shut until further notice." if open_end else f"; reopening is planned for {human(e)}."),
        f"Traffic through {p[0]} is suspended from {human(s)}" + (f" to {human(e)}" if e else "") + f" following {reason}, operators said.",
        f"No {who} could pass {p[0]} on {human(s)} because of {reason}; freight is being diverted.",
    ])
    summ = f"{p[0]} closed from {human(s, style='dmy')} after {reason}."
    return text, f"{p[2]} {R.choice(['closed', 'shut', 'traffic halted', 'suspended'])} after {reason.split(' ', 1)[1][:30]}", R.choice(NEWS_SITES + OFFICIAL_SITES), event("closure", p[0], s, e, summ)


def pos_road_near_port(pub, ho):
    road, city = R.choice([r for r in NEAR_PORT_ROADS if (r[0] in HELDOUT_PLACES) == ho] or NEAR_PORT_ROADS)
    s = pub + timedelta(days=R.randint(-1, 3))
    text = R.choice([
        f"The {road} near {city} has lost a lane for emergency repairs from {human(s)}, causing long peak-hour queues for trucks heading to the port.",
        f"Roadworks will close the {road} near {city} overnight from {human(s)}; hauliers serving the port should plan detours.",
    ])
    return text, f"{road} restrictions near {city}", R.choice(NEWS_SITES), event("closure", road, s, None, f"Lane closure on the {road} near {city} from {human(s, style='dmy')}.")


def pos_weather(pub, ho):
    p = pick(PORTS + WATERWAYS + AIRPORTS + ROADS, ho)
    s = pub + timedelta(days=R.randint(0, 4)); e = s + timedelta(days=R.randint(0, 3))
    kind = p[3]
    if kind in ("port", "canal", "strait", "sea lane"):
        w = R.choice(["storm", "dense fog", "typhoon", "high winds", "a cyclone"])
        texts = [(f"{w.capitalize()} forced {p[0]} to suspend vessel movements on {human(s)}; operations are expected to resume by {human(e)}.", True),
                 (f"Forecasters expect {w} at {p[0]} from {human(s)} to {human(e)}; pilots have stopped boarding and berthing is halted.", True),
                 (f"Pilotage at {p[0]} is suspended because of {w}, the harbour master said on {human(s)}.", False)]
    elif kind == "river":
        w = "low water levels"
        texts = [(f"Because of {w}, barges on the {p[0]} can only load a fraction of capacity from {human(s)}.", False)]
    elif kind == "airport":
        w = R.choice(["heavy snow", "dense fog", "a storm", "freezing rain"])
        texts = [(f"{w.capitalize()} grounded cargo flights at {p[0]} on {human(s)}; the backlog should clear by {human(e)}.", True),
                 (f"Freight flights at {p[0]} are cancelled from {human(s)} to {human(e)} as {w} sweeps the region.", True)]
    else:
        w = R.choice(["heavy snow", "flooding", "ice", "high winds", "a landslide after heavy rain"])
        texts = [(f"The {p[0]} is closed to trucks from {human(s)} because of {w}; officials expect it to reopen by {human(e)}.", True),
                 (f"{w.capitalize()} has closed the {p[0]} to heavy goods vehicles since {human(s)}.", False)]
    text, has_end = R.choice(texts)
    return text, f"{w.capitalize()} disrupts {p[2]}", R.choice(NEWS_SITES + OFFICIAL_SITES), event("weather", p[0], s, e if has_end else None, f"{w.capitalize()} disrupts {p[0]} from {human(s, style='dmy')}.")


def pos_congestion(pub, ho):
    p = pick(PORTS + BORDERS + RAIL, ho)
    wait = round(R.uniform(1.5, 9), 1); occ = R.randint(85, 99)
    text = R.choice([
        f"Weekly update: average vessel waiting time at {p[0]} is {wait} days; yard occupancy at the main terminal stands at {occ}% with barge delays of up to {R.choice([24, 36, 48, 72])} hours.",
        f"Import containers at {p[0]} are waiting {R.randint(5, 12)} days or longer for rail pickup as dwell times climb, carriers said on {human(pub)}.",
        f"Trucks queued for up to {R.randint(10, 40)} hours at {p[0]} this week as checks slowed processing.",
        f"Congestion builds at {p[0]}: {R.randint(10, 40)} ships are at anchor waiting for a berth, with waits of around {wait} days.",
    ])
    return text, f"{p[2]} congestion {R.choice(['worsens', 'update', 'persists'])}", R.choice(NEWS_SITES + ["carrier-advisory.invalid"]), event("congestion", p[0], pub, None, f"Congestion at {p[0]}: waits around {wait} days." if "wait" in text else f"Congestion and delays at {p[0]}.")


def pos_other(pub, ho):
    s = pub - timedelta(days=R.randint(0, 2))
    if R.random() < 0.5:
        w = R.choice([w for w in WATERWAYS if w[3] in ("sea lane", "strait")])
        text = R.choice([
            f"On {human(s)} maritime security trackers reported renewed missile and drone attacks on merchant ships in the {w[0]}, keeping traffic diverted and war-risk premiums high.",
            f"Attacks on commercial shipping continued in the {w[0]} as of {human(s)}, with carriers routing around the Cape of Good Hope.",
        ])
        return text, f"Attacks continue in the {w[0]}", R.choice(NEWS_SITES + ["security-desk.invalid"]), event("other", w[0], s, None, f"Renewed attacks on shipping in the {w[0]} as of {human(s, style='dmy')}.")
    p = pick(PORTS + WATERWAYS, ho)
    what = R.choice(["a container ship ran aground", "a crane collapsed onto a vessel", "an oil spill", "a vessel lost power and blocked the channel"])
    text = f"Shipping at {p[0]} was disrupted on {human(s)} after {what}; salvage teams are working to clear the area."
    return text, f"Incident disrupts {p[2]}", R.choice(NEWS_SITES), event("other", p[0], s, None, f"Shipping at {p[0]} disrupted on {human(s, style='dmy')} after {what}.")


def pos_bulletin(pub, ho):
    """Carrier bulletin covering several places: the first disruption listed is the event."""
    a, b = R.sample(PORTS, 2)
    wait = round(R.uniform(1.5, 6), 1)
    s = pub - timedelta(days=6)
    text = (f"Port operational updates ({human(s)} - {human(pub)}): {a[0]}: berth waiting time around {wait} days, yard "
            f"utilisation {R.randint(88, 97)}%. {b[0]}: operations normal, minor delays. "
            f"{R.choice(['Demonstrations affect roads in Chile.', 'Rail services in the US Midwest recover after flooding.', 'No other changes.'])}")
    return text, f"Port operational updates ({human(s)} - {human(pub)})", "carrier-advisory.invalid", event("congestion", a[0], s, pub, f"Waiting times around {wait} days and high yard use at {a[0]}.")


def pos_recap_dated(pub, ho):
    """A recently happened, dated disruption reported after the fact: still an event (code drops it if over)."""
    p = pick(PORTS, ho); s = pub - timedelta(days=R.randint(1, 5))
    text = f"The general strike on {human(s)} halted container loading at {p[0]}, with unions putting participation at around {R.randint(70, 98)}%."
    return text, f"General strike halts cargo at {p[2]}", R.choice(NEWS_SITES), event("strike", p[0], s, s, f"General strike halted cargo handling at {p[0]} on {human(s, style='dmy')}.")


POSITIVES = [(pos_strike, 14), (pos_warning, 13), (pos_closure, 13), (pos_road_near_port, 6), (pos_weather, 9),
             (pos_congestion, 12), (pos_other, 9), (pos_bulletin, 4), (pos_recap_dated, 4)]


# ---- non-events (hard negatives) ---------------------------------------------------------------------------
def neg_stats(pub, ho):
    p = pick(PORTS, ho)
    q = R.choice(["first half", "third quarter", "first nine months", "October"])
    if R.random() < 0.3 and p[1]:
        text = f"Der {p[1]} hat in den ersten neun Monaten weniger umgeschlagen: {R.uniform(40, 120):.1f} Millionen Tonnen, ein Minus von {R.uniform(0.5, 6):.1f} Prozent. Als Gründe nennt die Hafenverwaltung Kälte, Streiks und Modernisierung."
    else:
        text = R.choice([
            f"{p[0]} handled {R.uniform(2, 15):.1f} million TEU in the {q}, down {R.uniform(0.5, 6):.1f}% year on year. Weather losses, strikes and terminal works weighed on results.",
            f"Throughput at {p[0]} rose {R.uniform(0.2, 4):.1f}% in the {q} to {R.uniform(50, 230):.1f} million tonnes despite earlier strikes and congestion.",
            f"{p[0]} set a cargo record in {q} even as last year's labour disruption and rail delays remain in the memory of shippers.",
        ])
    return text, f"{p[2]} cargo volumes {R.choice(['fall', 'rise', 'stabilise'])} in {q}", R.choice(NEWS_SITES), None


def neg_funding(pub, ho):
    p = pick(PORTS + WATERWAYS + AIRPORTS, ho)
    text = R.choice([
        f"The European Commission approved €{R.randint(50, 900)} million in state aid to repair quay walls at {p[0]} and prevent structural failure.",
        f"{p[0]} awarded a €{R.randint(20, 400)} million contract to expand its container terminal by 2030.",
        f"The authority has put {R.randint(5, 40)} hectares of waterfront land at {p[0]} on the market for logistics users.",
        f"{p[0]} and a partner port signed a green and digital shipping corridor agreement on {human(pub)}.",
        f"Investors are backing a new {R.choice(['hydrogen terminal', 'cold store', 'rail hub'])} at {p[0]}, the operator said.",
    ])
    return text, f"{p[2]}: {R.choice(['state aid approved', 'new contract', 'land for sale', 'partnership signed', 'investment'])}", R.choice(NEWS_SITES + OFFICIAL_SITES), None


def neg_recovery(pub, ho):
    p = pick(PORTS + WATERWAYS, ho)
    c = R.choice(CARRIERS)
    text = R.choice([
        f"{c} has resumed transits through the {p[0]} after a three-year absence, as its vessel crossed on {human(pub - timedelta(days=2))}.",
        f"Traffic at {p[0]} is back to near-normal levels, with waiting times falling to under a day, carriers said.",
        f"Operations at {p[0]} returned to normal on {human(pub)} after last week's disruption ended.",
        f"Major carriers are gradually restoring services through the {p[0]}; volumes have recovered to two-thirds of earlier levels.",
    ])
    return text, f"{p[2]}: {R.choice(['services resume', 'back to normal', 'carriers return'])}", R.choice(NEWS_SITES), None


def neg_speculation(pub, ho):
    p = pick(PORTS + WATERWAYS, ho)
    text = R.choice([
        f"Analysts warn that {p[0]} could become a target if regional tensions escalate, which would have severe implications for trade.",
        f"Insurers say a prolonged disruption at {p[0]} would ripple inland through road and rail; contingency planning should start now.",
        f"What would a closure of the {p[0]} mean for shippers? An explainer on risks, costs and alternatives.",
        f"Shipping companies are seeking informal assurances before sending vessels near {p[0]}, highlighting persistent risk.",
    ])
    return text, f"{R.choice(['Analysis', 'Explainer', 'Opinion'])}: the risk to {p[2]}", R.choice(NEWS_SITES + JUNK_SITES), None


def neg_profile(pub, ho):
    p = pick(PORTS, ho)
    name = R.choice(["J. de Vries", "M. Schulz", "A. Rossi", "L. Martin", "K. Tan", "S. Okafor", "P. Novak"])
    role = R.choice(["Operations Manager", "Asset Manager", "Spokesperson", "Port Agent", "Research Engineer", "Terminal Planner"])
    extra = ""
    if R.random() < 0.5:  # reposted news inside a profile is the hardest case
        old = pub - timedelta(days=R.randint(40, 120))
        extra = f" Reposted: Latest port news: a strike may affect cargo handling at {p[2]} on {human(old)}. #shipping #ports"
    text = f"### {role} at {p[0]} ({R.randint(2008, 2023)} – Present) Experience: managing maintenance of locks, bridges and quay walls. Skills: logistics, planning.{extra}"
    return text, name, R.choice(PROFILE_SITES), None


def neg_linklist(pub, ho):
    p = pick(PORTS, ho)
    heads = R.sample([
        f"Customs seize drugs in container at {p[2]}", "Local team wins championship", f"New museum opens near {p[2]}",
        "Lottery results", f"Cargo ship strikes bridge in another country", "Weather: sunny weekend ahead",
        f"{p[2]} mayor announces festival", "Celebrity spotted at harbour restaurant", "Stock markets close higher"], 4)
    text = " · ".join(heads) + ". " + R.choice(NAV)
    return text, f"{p[2]} news (page {R.randint(2, 9)})", R.choice(JUNK_SITES), None


def neg_other_meaning(pub, ho):
    p = pick(PORTS + AIRPORTS, ho)
    text = R.choice([
        f"A helicopter made an emergency landing after a bird strike near {p[2]}; nobody was hurt.",
        f"Lightning strike damages church roof in {p[2]}.",
        f"The two companies struck a deal on {human(pub)} to supply cranes to {p[0]}.",
        f"A cruise ship was arrested at {p[0]} under a court order in a dispute with its lender; other traffic is unaffected.",
        f"Police at {p[0]} seized {R.randint(200, 2000)} kg of cocaine hidden in a banana container.",
        f"A data company tried to fly drones over storage tanks at {p[0]}, prosecutors said.",
        f"Bowling: {p[2]} player scores a perfect strike streak in the final.",
    ])
    return text, R.choice([f"Bird strike near {p[2]}", "Deal struck", f"Ship arrested at {p[2]}", f"Drugs seized at {p[2]}", f"Drones over {p[2]} tanks"]), R.choice(NEWS_SITES + JUNK_SITES), None


def neg_mass_action(pub, ho):
    n = R.randint(40, 130); c = R.randint(10, 30)
    text = R.choice([
        f"Dockworkers at about {n} ports in {c} countries held a coordinated day of action on {human(pub - timedelta(days=R.randint(5, 15)))} against military cargo.",
        f"Port workers across {c} countries plan solidarity actions this year, union federations said, without naming ports or dates.",
    ])
    return text, f"Dockworkers in {c} countries {R.choice(['mobilise', 'join day of action'])}", R.choice(NEWS_SITES), None


def neg_condition(pub, ho):
    p = pick(ROADS + PORTS + RAIL, ho)
    text = R.choice([
        f"The latest inspection gave the {p[0]} a poor condition grade of {R.uniform(3.0, 3.9):.1f}; engineers say replacement is needed within the decade.",
        f"The maintenance backlog for roads and bridges has doubled to €{R.uniform(1, 4):.1f} billion, the agency said, warning of more closures in coming years.",
        f"Plans to modernise the {p[0]} by 2032 were presented to the council on {human(pub)}.",
        f"Logistics groups urged faster investment in the {p[0]}, citing vulnerabilities seen in past years.",
    ])
    return text, f"{p[2]}: {R.choice(['condition report', 'backlog grows', 'plans presented', 'industry demands'])}", R.choice(NEWS_SITES), None


def neg_event_tourism(pub, ho):
    p = pick(PORTS, ho)
    text = R.choice([
        f"{p[2]} will welcome around {R.randint(200, 900)} founders and investors on {human(pub + timedelta(days=3))} for a climate tech summit organised with the port.",
        f"Should you spend one, two or three days in {p[2]}? The historic port city offers museums, food and shopping.",
        f"A gravel cycling race through the docks of {p[2]} ended with a solo win after a late attack.",
        f"Port open day at {p[0]}: tours of the terminals for the public this weekend.",
    ])
    return text, R.choice([f"{p[2]} hosts summit", f"Days in {p[2]}", f"Race in the {p[2]} docks", f"Open day at {p[2]}"]), R.choice(NEWS_SITES + JUNK_SITES), None


def neg_history(pub, ho):
    p = pick(WATERWAYS + PORTS, ho)
    text = R.choice([
        f"Five years ago a giant container ship blocked the {p[0]} for six days; here is what the industry learned.",
        f"On this day in history: the great dock strike at {p[0]} began.",
    ])
    return text, f"Looking back: {p[2]}", R.choice(NEWS_SITES + JUNK_SITES), None


def neg_rates(pub, ho):
    a, b = R.sample(PORTS, 2)
    text = f"The container index dipped to ${R.randint(1200, 4000)} per 40ft as easing congestion lowered rates; {a[2]}–{b[2]} rates rose {R.randint(2, 12)}% on firm demand."
    return text, "Container index update", R.choice(NEWS_SITES), None


def neg_software(pub, ho):
    p = pick(PORTS, ho)
    text = f"Issue #12: build port-status monitoring for {p[2]} with tests for resolved strike, stale event, false match and closure cases."
    return text, f"Port monitor MVP issue · repo", "code-host.invalid", None


NEGATIVES = [(neg_stats, 12), (neg_funding, 11), (neg_recovery, 12), (neg_speculation, 9), (neg_profile, 9),
             (neg_linklist, 7), (neg_other_meaning, 11), (neg_mass_action, 6), (neg_condition, 8),
             (neg_event_tourism, 7), (neg_history, 3), (neg_rates, 4), (neg_software, 2)]


def make(n: int, heldout: bool, neg_share=0.55):
    rows = []
    pos_fns = [f for f, w in POSITIVES for _ in range(w)]
    neg_fns = [f for f, w in NEGATIVES for _ in range(w)]
    for i in range(n):
        pub = date(2026, R.randint(9, 11), R.randint(1, 28))
        fn = R.choice(neg_fns if R.random() < neg_share else pos_fns)
        text, title, site, label = fn(pub, heldout)
        it = item(text, title, site, pub)
        today = d(pub + timedelta(days=R.randint(0, 3)))
        rows.append({"prompt": training_prompt(it, today),
                     "completion": "null" if label is None else json.dumps(label, ensure_ascii=False),
                     "meta": {"kind": fn.__name__, "heldout": heldout, "synthetic": True, "item": it, "today": today, "clean": text,
                              "label": label}})
    return rows


def main():
    train, held = make(1800, False), make(240, True)
    for name, rows in (("train_v2.jsonl", train), ("heldout_v2.jsonl", held)):
        (OUT / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    # Adaption upload: two string columns only
    (OUT / "adaption_train_v2.jsonl").write_text(
        "".join(json.dumps({"prompt": r["prompt"], "completion": r["completion"]}, ensure_ascii=False) + "\n" for r in train))
    from collections import Counter
    for name, rows in (("train", train), ("heldout", held)):
        k = Counter(r["meta"]["kind"] for r in rows)
        nulls = sum(r["completion"] == "null" for r in rows)
        print(f"{name}: {len(rows)} rows, {nulls} null ({nulls / len(rows):.0%}); {dict(sorted(k.items()))}")


if __name__ == "__main__":
    main()
