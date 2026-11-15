# Real-snippet extractor eval

78 real Linkup search results (8 searches, 15 Nov 2026, queries in `collect.py`), labelled by hand in
`labels.jsonl` (keyed by URL): 23 events, 49 non-events, 6 ambiguous (left out of the headline score).
The raw text is third-party news, so `raw_snippets.jsonl` is gitignored; rerun `collect.py` (8 Linkup calls)
to rebuild it. Results drift as the web changes, so the labels apply to the snapshot taken on 15 Nov.

Labelling rules (the same rules are in the extractor prompt, `agent/extract.py` SYSTEM):
- An event is a specific disruption to freight at a named place (port, terminal, canal, strait or sea lane,
  airport, border, named road, bridge, rail line or station), happening, announced or recent.
- Not events: statistics and recaps, funding and deals, recovery news, speculation, profiles and link lists,
  other meanings of "strike", mass actions with no named place, condition reports with no restriction.
- A deferred or threatened strike is a `warning`; a called strike with dates is a `strike`.
- The location is the place the text names (a bridge, not the nearest port).
- Past events are still events here; `agent.extract.extract()` drops events that already ended, in code.

Score: `python finetune/real/predict.py preds/x.jsonl --workers 2` then `python finetune/real/score.py preds/x.jsonl`.

## Results (72 unambiguous snippets)

| Extractor | Detection F1 | Precision | Recall | Type | Location | Window start |
|---|---|---|---|---|---|---|
| Llama 3.3 70B (Databricks), old prompt | 0.638 | 0.478 | 0.957 | 0.500 | 1.000 | 0.667 |
| Llama 3.3 70B (Databricks), strict prompt | **0.917** | **0.880** | 0.957 | **0.909** | 1.000 | **0.909** |

Both runs retry a failed model call (rate limit or timeout); without that, throttled calls looked like
"no event" and the first measurement of the old prompt was 0.278 F1. Remaining strict-prompt errors: a LinkedIn
profile reposting an old strike, an unrelated bridge headline fragment, one cruise ship's arrest read as a port
closure, a weekly congestion update typed as a warning, and a strike recap with no date.
