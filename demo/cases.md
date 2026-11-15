# Demo cases

These are the cases we rehearse, in the order we show them. Each one has a deep link, so if a click goes wrong on
stage you can jump straight back in. Links are relative to wherever the app is running (locally that's
`http://localhost:8000`).

Say it early and say it plainly: **the fleet is made up, the disruptions are real.** Events with a "sample" badge
are fixtures; anything without one came from a live Linkup search. Every cost is an "estimate, illustrative rates".

## 1. The morning briefing

Link: `/?briefing`

PortShifter walks through what it checked, step by step, then puts two decisions in front of you with what each
would cost. This is the "agent did the work while you were asleep" moment, so let it play out before talking over
it.

## 2. A shipment in trouble: S-1005

Link: `/?select=S-1005&ptab=plan`

S-1005 is a truck going Felixstowe to Duisburg through Dover and Calais, and it's red because of a confirmed strike
at Calais on its next leg. Before opening the options, point at the route on the map: it follows real roads round
the Thames estuary and goes through the Channel Tunnel. Then show why it's level 5 (the reason line), and that the
strike is "confirmed" because of an official source. Open the sources and show how long ago each was retrieved.

In Options, the reroute goes via Dunkirk on a real ferry route, with the fare priced in, and is checked again by the
risk job. Rescheduling is the other choice, and it costs a couple of days. Both carry the illustrative-rates label.

## 3. Live search, on stage

This is the step that has to be live. Either:

- ask PortShifter "check Calais for new disruptions", or
- run the Databricks Job "PortShift: monitor -> risk" from the Jobs page (it stops after 12 Linkup calls).

New events show up without a "sample" badge, with their real source links, as "suspected" or "confirmed". It's worth
saying how the agent decides: a lot of what Linkup returns for "Calais strike" is not a disruption at all (profiles,
statistics, old news), and the extractor is built to throw those away.

Fallback if the network or credits fail: the live events already loaded on the demo machine (they keep their real
links), or the sample events, with their badge showing.

## 4. What if?

Link: `/?whatif=What if Dover closes tomorrow for 3 days?`

A made-up scenario, drawn in purple so nobody mistakes it for real news. It shows which shipments would be hit and
what that would cost, without writing anything.

## 5. Planning new freight

Link: `/?tab=new`

Plan a shipment with an arrive-by date, pick a route and press "Add to planned shipments". Then open Planned
shipments (`/?tab=pln`) to show it there. For the same thing by chat, ask PortShifter something like "plan a new
shipment from Edinburgh warehouse to Birmingham warehouse, 8 pallets, arrive by Friday", then approve it. It lands in
the same tab, tagged by where it came from.

Fleet (`/?tab=flt`): click a depot on the map to plan with one of your own trucks.

## 6. Why the extractor can be trusted (one slide)

On 50 real search results we labelled before any model saw them, detection F1 was 0.361 for the untuned 2B model,
0.857 for our Adaption fine-tune of it, and 0.870 for Llama 3.3 70B on Databricks, which is what runs live. The
details are in `finetune/RESULTS.md`. Keep the caveat in: Adaption's win rate is a preference score, not accuracy.

## Before going on

- [x] `python evals/check_citations.py`: 0 failures (15 Nov, 10:05 UTC)
- [x] `python evals/check_risk.py`: 14 shipments, 0 failures
- [x] `python evals/check_app.py <app url>`: 14 shipments, 0 failures, on the demo instance
- [ ] Live search tried once on the demo machine within the hour before (credits left?)
- [ ] The UI shows "Demo fleet", the "sample" badges and "estimate, illustrative rates"
- [ ] Backup recording of cases 1 to 5 saved
