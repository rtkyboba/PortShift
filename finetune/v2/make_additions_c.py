"""Run C additions: targeted rows for the failure groups run A showed on the DEV real set (finetune/real/labels.jsonl).

    python finetune/v2/make_additions_c.py      # -> finetune/v2/additions_c.jsonl (same row format as train_v2.jsonl)

Groups (from run A's dev errors): recovery / resumption news read as a disruption; infrastructure works with no
restriction; passenger-only border items; mass actions with no named place; strikes that are called although some
unions hold back (still "strike"); security alerts that stop traffic ("closure", not "warning"). Labels are exact by
construction, as in make_dataset_v2.py. Nothing is copied from either real set.
"""
import json
import pathlib
import random
import sys
from datetime import date, timedelta

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE))
import make_dataset_v2 as gen  # noqa: E402
from agent.extract import training_prompt  # noqa: E402

R = random.Random(20261116)
gen.R = R  # the generator's helpers (pick, noisy, item, human) draw from this RNG too
human, item, event, d = gen.human, gen.item, gen.event, gen.d
CARRIERS = gen.CARRIERS


def recovery(pub, ho):
    p = R.choice(gen.WATERWAYS + gen.PORTS)
    lang = R.choice(["en"] * 5 + ["es", "pt", "fr", "de"])
    n_old, n_new = R.randint(24, 33), None
    n_new = n_old + R.randint(1, 4)
    c = R.choice(CARRIERS)
    if lang == "es":
        text = f"{c} volvió a {p[0]} tras casi {R.randint(2, 3)} años de ausencia; su buque cruzó el {human(pub - timedelta(days=2), 'es')}."
    elif lang == "pt":
        text = f"A {c} voltou a operar em {p[0]} depois de quase três anos; o navio fez a travessia em {pub.day} de novembro."
    elif lang == "fr":
        text = f"Les autorités de {p[0]} relèvent la capacité quotidienne à {n_new} passages et lèvent les restrictions de tirant d'eau à partir du {human(pub, 'fr')}."
    elif lang == "de":
        text = f"{c} kehrt nach fast drei Jahren zu {p[0]} zurück; das erste Schiff passierte am {human(pub - timedelta(days=1), 'de')}."
    else:
        text = R.choice([
            f"{p[0]} authorities raised daily transit capacity from {n_old} to {n_new} vessels on {human(pub)} and restored the maximum draft as water levels recovered.",
            f"Recent rainfall allowed {p[0]} to increase traffic limits after earlier restrictions; more vessels may now pass each day.",
            f"{c} resumed services through {p[0]} after a suspension of almost three years, with its first vessel crossing on {human(pub - timedelta(days=2))}.",
            f"Restrictions at {p[0]} were lifted on {human(pub)}; the backlog of waiting ships has cleared, the operator said.",
            f"The terminal at {p[0]} reopened on {human(pub)} after last week's closure ended, and operations are back to normal.",
            f"Traffic through {p[0]} has returned to around two-thirds of its former level as carriers gradually restore routes.",
            f"Mega-ship traffic resumes at {p[0]}: a 20,000 TEU vessel transited in convoy on {human(pub - timedelta(days=1))}, marking a new phase of recovery.",
        ])
    return text, f"{p[2]}: {R.choice(['capacity raised', 'services resume', 'restrictions eased', 'traffic returns'])}", R.choice(gen.NEWS_SITES + gen.OFFICIAL_SITES), None


def works(pub, ho):
    p = R.choice(gen.PORTS)
    text = R.choice([
        f"A backhoe dredger has started work on a new 2 km access channel at {p[0]}, which will give barges direct access to the container terminals when it opens in 2028.",
        f"Construction of a new breakwater at {p[0]} reached a milestone this week; the project will extend berth capacity.",
        f"{p[0]} installed four new ship-to-shore cranes, the operator said on {human(pub)}.",
        f"All warehouse space at a new logistics park near {p[0]} has now been leased to two operators.",
        f"A new AI crane-safety system developed at {p[0]} is being offered to other ports.",
    ])
    return text, f"{p[2]}: {R.choice(['dredging starts', 'breakwater milestone', 'new cranes', 'logistics park leased'])}", R.choice(gen.NEWS_SITES), None


def passenger(pub, ho):
    p = R.choice([("Port of Dover", "Dover"), ("Channel Tunnel", "Eurotunnel"), ("Heathrow Airport", "Heathrow"), ("Lille-Europe station", "Lille")])
    text = R.choice([
        f"The operator of {p[0]} wants drive-through biometric kiosks for holiday travellers under the new entry-exit system; the trial still awaits approval.",
        f"A £40 million passenger processing hall at {p[0]} sits unused because of software problems, a travel blog reports.",
        f"Travellers using {p[0]} this summer should allow extra time for new passport checks, a consumer guide advises.",
    ])
    return text, f"{p[1]}: passenger checks", R.choice(gen.NEWS_SITES + gen.JUNK_SITES), None


def mass_action(pub, ho):
    n = R.randint(60, 130); c = R.randint(10, 30)
    text = R.choice([
        f"From the Mediterranean to the Indian Ocean, dockworkers at about {n} ports in {c} countries joined an international day of action on {human(pub - timedelta(days=R.randint(7, 14)))}.",
        f"Seafarers and dockers across five continents mobilised in solidarity, union federations said, with stoppages reported at dozens of ports.",
    ])
    return text, f"Dockworkers in {n} ports join day of action", R.choice(gen.NEWS_SITES), None


def called_strike(pub, ho):
    p = R.choice([x for x in gen.PORTS if x[1]] + gen.AIRPORTS)
    s = pub + timedelta(days=R.randint(2, 8))
    text = R.choice([
        f"The ports and docks federation has called a 24-hour stoppage at {p[0]} on {human(s)}, its third strike call in a month; two other unions have withheld backing while talks continue.",
        f"Dockers at {p[0]} are called out on strike on {human(s)}. Not all unions support the action, but the main federation has confirmed it.",
    ])
    return text, f"Strike called at {p[2]} for {human(s, style='dmy')}", R.choice(gen.NEWS_SITES), event("strike", p[0], s, s, f"24-hour strike called at {p[0]} on {human(s, style='dmy')}.")


def security_alert(pub, ho):
    p = R.choice(gen.RAIL + gen.AIRPORTS + [x for x in gen.PORTS])
    s = pub - timedelta(days=R.randint(0, 1))
    what = R.choice(["A bomb alert", "A suspicious package", "A security alert", "An unexploded device found nearby"])
    text = R.choice([
        f"{what} stopped all traffic at {p[0]} on {human(s)}; trains and freight were held while police searched the area.",
        f"{what} is under way at {p[0]}; no services can pass, the authorities said on {human(s)}.",
    ])
    return text, f"{what} halts traffic at {p[2]}", R.choice(gen.NEWS_SITES), event("closure", p[0], s, None, f"{what} stopped traffic at {p[0]} on {human(s, style='dmy')}.")


GROUPS = [(recovery, 160), (works, 60), (passenger, 40), (mass_action, 40), (called_strike, 50), (security_alert, 50)]


def main():
    rows = []
    for fn, n in GROUPS:
        for _ in range(n):
            pub = date(2026, R.randint(9, 11), R.randint(1, 28))
            text, title, site, label = fn(pub, False)
            it = item(text, title, site, pub)
            today = d(pub + timedelta(days=R.randint(0, 3)))
            rows.append({"prompt": training_prompt(it, today), "completion": "null" if label is None else json.dumps(label, ensure_ascii=False),
                         "meta": {"kind": "c_" + fn.__name__, "heldout": False, "synthetic": True, "item": it, "today": today,
                                  "clean": text, "label": label}})
    R.shuffle(rows)
    (HERE / "additions_c.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(len(rows), "rows;", sum(r["completion"] == "null" for r in rows), "null")


if __name__ == "__main__":
    main()
