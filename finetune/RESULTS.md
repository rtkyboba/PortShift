# PortShift extractor fine-tune: results

Task: one news snippet in, one disruption event JSON out (type, place, time window, summary, source), or `null`
when the snippet describes no disruption. Contract: `CONTRACTS.md` section 4.

## The run (track lead's Adaption account, 14 Nov 2026)

- Platform: Adaption AutoScientist (SDK 0.19.0), instruction (SFT) method, LoRA
- Base model: Qwen/Qwen3.5-2B (the smallest in the supported list)
- Dataset: `finetune/adaption_train.jsonl`, 1,161 rows (prompt, completion). Dataset id `3a1f01a0-3c27-4ff1-a84f-dcef7db06e8a`
- Run id: `4c406bd7-b8fa-4350-be47-e08a2b2d5596`, status succeeded, 22:31 to 23:36 UTC (65 minutes)
- Iterations: 1 of max 3 (it stopped after the first because the target was met)
- Adaption `best_win_rate`: 0.942 (target 0.7)
- Hyperparameters chosen by AutoScientist: LoRA r=16, alpha=32, dropout 0, lr 5e-5, 1 epoch, cosine schedule,
  warmup 3%, on q/k/v/o and the MLP projections
- Checkpoint: a 44 MB LoRA adapter, `python finetune/run_adaption.py download` (not committed)

An earlier run of the same data (`5c4c9379-0f2a-421e-96ec-425e8a49eaaf`, win rate 0.9258) was made on a
teammate's Adaption account before the team rule that runs go on the track lead's account. This run replaces it.

## Held-out score: base against fine-tune

101 rows in `finetune/heldout.jsonl` that were never uploaded (91 events, 10 with no disruption). Both models were
served locally on one RTX 4080 with `finetune/serve_local.py`, given the same prompts, greedy decoding, and scored
with `evals/extractor_eval.py`. Every reply from both models parsed as JSON. Predictions are in `finetune/results/`.

| Metric | Base Qwen3.5-2B | Fine-tune | 
|---|---|---|
| Detection F1 (event or none) | 0.948 | **1.000** |
| Detection precision | 0.901 | **1.000** |
| Detection recall | 1.000 | 1.000 |
| Type, exact | 0.593 | **0.934** |
| Location name, exact | 0.824 | **1.000** |
| Window start, exact | 0.341 | **0.989** |
| Window end, exact | 0.165 | **0.945** |

Field scores are over correctly detected events. The fine-tune beats the base model on every field.

## What these numbers do and do not show

- **The held-out rows are synthetic and come from the same templates as the training rows.** The fine-tune has
  learned the template's conventions (how a window is written, how a place is named), so these scores say how well
  it learned our format, not how well it reads real news. There is no score on real Linkup snippets yet.
- **Adaption's win rate is not accuracy.** 0.942 is the share of comparisons in which Adaption's judge preferred
  the fine-tune's output to the base model's on Adaption's own evaluation split.
- **All six type errors of the fine-tune are "congestion"** (read as closure or weather). The training file has
  no congestion rows at all (374 weather, 237 warning, 219 closure, 212 strike, 119 none), while the held-out set
  has some. Adding congestion examples to `make_dataset.py` is the obvious next fix.
- Single run, one iteration, no seeds or variance estimate. The base model's low window scores are partly format
  (it writes "15 November" where the gold answer is an ISO time), which exact match counts as wrong.

## Live path

The live path stays on the base model (`EXTRACTOR_USE_BASE=1`). The fine-tune meets the rule in AGENTS.md section 6
(it beats the base model on the held-out set), but `agent/extract.py` does not call an extractor endpoint yet and
uses a different prompt from the one the fine-tune was trained on, and the evidence so far is synthetic only. To
swap it in: serve the adapter (`finetune/serve_local.py` gives an OpenAI-compatible endpoint; 8 GB of GPU memory in
use), point `EXTRACTOR_ENDPOINT` at it, have `agent/extract.py` send the training prompt, and score it on real
snippets first.

## Reproduce

1. `pip install "adaption==0.19.0"`; put `ADAPTION_API_KEY` in the repo-root `.env`.
2. `python finetune/run_adaption.py upload`, `train`, `wait`, `download`; then
   `mkdir -p finetune/checkpoints/best && tar xf finetune/checkpoints/best-checkpoint.tgz -C finetune/checkpoints/best`.
3. `pip install torch transformers peft accelerate`
4. `python finetune/serve_local.py --port 8090` (base) and
   `python finetune/serve_local.py --adapter finetune/checkpoints/best --port 8091` (fine-tune).
5. `python evals/run_extractor.py --backend http --url http://127.0.0.1:8090/v1/chat/completions --out preds_base.jsonl`,
   the same on port 8091 into `preds_ft.jsonl`, then `python evals/extractor_eval.py preds_base.jsonl preds_ft.jsonl`.

## Things that went wrong on the way (so nobody repeats them)

- Passing `column_mapping` to `autoscientist.create` is rejected (400) for an uploaded dataset; leave it out.
- The planned Qwen3.5-0.8B is not supported; 2B is the smallest.
- **A LoRA adapter can load without being applied.** Adaption trains on the image-and-text build of the model,
  whose text layers are named `model.language_model.layers.N`; the text-only build names them `model.layers.N`.
  Loaded the usual way, no weight matched and the "fine-tune" produced exactly the base model's 101 answers.
  `serve_local.py` maps the names and refuses to start unless all 192 adapter tensors are applied.
- The run took 65 minutes, not the 15 to 45 we expected.

## Extractor v2: hard negatives and real search results (15 Nov 2026)

Why: on live Linkup results the extractor over-extracted (state aid read as a closure, Q3 statistics as strikes,
profile pages as sources). v1's held-out rows came from the same templates as its training rows, so they could not
show this. v2 is scored on **real Linkup results labelled by hand**:

- **dev** set, `finetune/real/labels.jsonl`: 78 results from 8 searches (72 unambiguous: 23 events, 49 not).
  Used to find failure groups, so it is not a clean test for runs designed after it (run C).
- **test** set, `finetune/real/test_labels.jsonl`: 60 results from 6 different searches (50 unambiguous: 11 events,
  39 not), labelled before any model was run on them. Recovery news is heavily represented (Panama Canal).

Training data (`finetune/v2/`): synthetic search results shaped like real Linkup hits, about 54% hard negatives
(statistics and recaps, funding, recovery news, speculation, profiles, link lists, other meanings of "strike", mass
actions with no named place, condition reports), on the live extractor prompt (`agent.extract.training_prompt`).
Every label is exact by construction; nothing is copied from either real set; sources use the `.invalid` TLD.

| Run | Data | Adaption win rate | Run id |
|---|---|---|---|
| A | 1,800 template rows | 0.7654 (3 iterations, target 0.85) | `924b8f3e-e770-4704-9fed-59dfb1d1a57a` (dataset `aeb5e3ce`) |
| B | same rows, 782 reworded by Llama 3.3 70B with fact and label checks | 0.7288 (3 iterations) | `11efbc11-05a4-4cab-aa04-679d03c7a9ea` (dataset `c62956af`) |
| C | B + 400 rows for run A's dev failure groups (271 reworded), 2,200 rows | 0.7399 (3 iterations) | `b0a2fa1a-b2b0-466d-bf55-6a076b7abab1` (dataset `dc5e5783`) |

Detection on real results (an event or not), unambiguous rows only:

| Extractor | dev F1 | dev precision | test F1 | test precision | test recall |
|---|---|---|---|---|---|
| Base Qwen3.5-2B, same prompt | 0.468 | 0.310 | 0.361 | 0.220 | 1.000 |
| Fine-tune run A (template data) | 0.852 | 0.742 | 0.733 | 0.579 | 1.000 |
| **Fine-tune run B (reworded data)** | **0.936** | **0.917** | **0.857** | **0.900** | **0.818** |
| Fine-tune run C (B + targeted rows) | 0.898 | 0.846 | 0.818 | 0.818 | 0.818 |
| Llama 3.3 70B (Databricks), strict prompt (the live extractor) | 0.917 | 0.880 | 0.870 | 0.833 | 0.909 |

- Run B, the same 2B model trained on reworded rows, more than doubles the base model's F1 on the untouched test
  set (0.361 to 0.857) and comes within 0.013 of the 70B model there, with higher precision (0.90 against 0.83) and
  lower recall (it missed 2 of 11 events: a Hormuz traffic report and a multi-port congestion roundup). The base
  model calls almost everything an event (60 of 60 on test).
- Run A (template text only) generalised worse (test 0.733): rewording the same facts in varied styles is what
  moved the score, not more rows.
- Run C added 400 rows aimed at run A's dev mistakes (recovery news, works, passenger items, called strikes,
  security alerts). It fixed the types (every event it found on test had the right type) but raised more false
  alarms and missed two Hormuz reports, so it scores below B on both sets. **Run B is the best extractor fine-tune.**
  More targeted rows did not beat varied wording; with 11 test events, one event is about 0.05 F1, so B and C are
  close and a bigger test set would be needed to separate them with confidence.
- Run A's false alarms were mostly recovery news ("capacity raised", "carrier resumes transits") and
  infrastructure or passenger items; run B has 1 false alarm on test (an FAQ page).
- On the synthetic held-out rows run A is 240/240 on detection: that set no longer separates runs; the real sets do.
- Adaption's win rate is a judged preference on its own split, not these accuracies.
- Adaption `expand` (dataset `f791f7db`) returned general-purpose rows unrelated to the task: 0 of 595 usable, not used.

---

# Request reader for Ask PortShifter (second fine-tune, 15 Nov 2026)

Task: an operator's chat message in, one structured request out: intent, goal, fleet budget, corridor, shipment ids,
and for new shipments the stops, cargo and timing of each, or a details reply. Format and prompt: `app/reader_prompt.py`.
Data, runner and scorer: `finetune/router/`. The model never chooses an option, a route or a figure.

## The runs (track lead's Adaption account)

| | v1 | v2 (the one scored below) |
|---|---|---|
| Request format | no timing | timing per shipment, details replies |
| Training rows | 1,460 | 1,790 |
| Dataset id | `cbabd23c-9d18-4b52-8685-16a8fe48bcab` | `40b1ae9e-5f97-4f7f-a712-ed34b47c59a8` |
| Run id | `2e4100f2-2dde-4bc8-8895-a81c2d4d92e1` | `34e00a06-87a9-4b51-8cfe-f5bb7b63e0da` |
| Adaption `best_win_rate` | 0.847 | 0.886 |

Both: Qwen/Qwen3.5-2B, LoRA, instruction method, one iteration (target 0.7 met). v1 was superseded when cargo and
timing became required for a new shipment; it was not downloaded or scored.

## Held-out score

266 rows in `finetune/router/heldout.jsonl`, **written from phrasings, place names and shipment ids that are not in
the training rows**, so this measures wording the model has not seen. Scored with `finetune/router/eval.py`; every
prediction is in `finetune/router/heldout_predictions.json`. The fine-tune was served locally with
`finetune/serve_local.py` (192 of 192 adapter tensors applied), greedy decoding.

| Metric | Fixed patterns | Fine-tune alone | As the app uses it |
|---|---|---|---|
| Intent right | **0.853** | 0.692 | **0.853** |
| Whole request right | 0.624 | 0.455 | **0.699** |
| New shipments: stops right | 0.405 | **0.798** | 0.750 |
| New shipments: cargo right | 0.881 | 0.810 | **0.929** |
| New shipments: timing right | **0.881** | 0.619 | 0.821 |
| Details reply right | **0.872** | 0.641 | **0.872** |
| Fleet plan: goal right | **0.643** | 0.214 | **0.643** |
| Live check: corridor right | 0.571 | **0.667** | 0.571 |
| Out of scope: precision / recall | 0.600 / 0.818 | **0.929** / 0.591 | 0.600 / 0.818 |

## What it shows, and the decision

- **The fine-tune alone does not beat the fixed patterns** on unseen wording: it gets the intent right less often
  (0.692 against 0.853) and the whole request right less often (0.455 against 0.624). Its Adaption win rate of 0.886
  is a judged preference over the untuned base model, which is poor at this task (intent 0.147 and whole request 0.028
  on the v1 held-out set), not accuracy.
- **It is much better at one thing: splitting a sentence into shipments and their stops** (0.798 against 0.405). That
  is the part fixed patterns are worst at.
- **So the app uses each for its part** (`app/router.py`): the patterns decide what a message is and read cargo, timing,
  goal and budget; when the message is about new shipments and `ROUTER_ENDPOINT` is set, the fine-tune splits it into
  shipments and stops. Its answer is used only if every place, figure and date word in it appears in the message. That
  combination gets the whole request right on 0.699 of the held-out rows against 0.624 for the patterns alone, with
  stops up from 0.405 to 0.750. Timing drops from 0.881 to 0.821, because where the two disagree on how many shipments
  there are, the model's reading of the timing is used.
- Without `ROUTER_ENDPOINT` the app behaves exactly as with the patterns alone.

## Limits

- Synthetic data: both sets are generated from templates, the held-out set from a separate list of them. No real
  operator messages have been scored.
- One run each, one iteration, no variance estimate.
- About 2 seconds per message on one RTX 4080 shared with another model; only new-shipment messages go to the model.
- The model's weak spots on unseen wording are telling a fleet question from a stock question or a live check, and the
  goal of a fleet plan. More varied training rows for those intents is the next step, not a bigger model.

## Reproduce

1. `python finetune/router/make_dataset.py` (rewrites `train.jsonl` and `heldout.jsonl`).
2. `ROUTER_RUN=v2 python finetune/router/run.py upload`, `train`, `status`, `download`; extract the archive into
   `finetune/router/checkpoints/v2/best`.
3. `python finetune/serve_local.py --adapter finetune/router/checkpoints/v2/best --port 8092`
4. `python finetune/router/eval.py --reader patterns`, then `--url http://127.0.0.1:8092/v1/chat/completions`, then the
   same with `--as-used`.
5. To use it in the app: start the app with `ROUTER_ENDPOINT=http://127.0.0.1:8092/v1/chat/completions`.
