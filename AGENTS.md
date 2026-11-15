# Team rules for every agent — Autonomous Agents track

**Track lead:** `@rtkyboba` (Ryan)

## 0. Track brief

**Product: PortShift.** An autonomous agent for a logistics operations coordinator: it watches live web news for strikes, closures and warnings, works out which of the company's shipments are hit, scores each shipment 1–5, and proposes costed reschedules and reroutes, with a source URL on every claim.

Bounties, and what each must visibly do in the product:

| Bounty | What carries it | Owner |
|---|---|---|
| **Main track** (autonomous agents) | Agent loop: plan → search → cross-check → write → rescore → propose, retrying failed steps unprompted | `@rtkyboba` |
| **Databricks** (creativity, depth, impact) | Delta tables are the only state; a job computes risk; the app is a Databricks App. Not a CSV store | — |
| **Linkup** (live search, cited) | Every disruption event comes from Linkup. No citation, no display | `@rtkyboba` |
| **Figma** (designed as well as it is smart) | UI designed in Figma or Figma Make first; frames and link kept in `design/` as evidence | — |
| **Adaption** (fine-tune, win rate vs base) | Fine-tuned **disruption-event extractor**: news snippet → structured event JSON | — |

**Demo must show:** operator opens the map → agent searches live with Linkup → cross-checks sources → writes events to Databricks → affected shipments change colour → click one: route, cargo, reason, citations with freshness → chat: "what does it cost to move this to another date?" → tentative plan opens in a new tab.

### Ground rules for honesty (do not break these)

- **The fleet is synthetic. The disruptions are real.** We have no real fleet feed. `shipments` and `legs` are seeded data on real ports, roads and airports. The UI says "demo fleet". Never present seeded shipments as real.
- **Fixture events are flagged.** Any event not produced by a live Linkup call has `is_fixture = true` and shows a "sample" badge. Never invent a source URL.
- **Costs are illustrative.** Cost comes from a transparent formula over a `cost_rates` table, not from an LLM. The UI labels every figure "estimate, illustrative rates". The fine-tuned model does not produce money figures.
- **"Optimise" is a greedy heuristic**, not a solver. Call it "suggested plan" in the UI.

### Risk levels (one definition, used everywhere)

| Level | Name | Colour | Rule |
|---|---|---|---|
| 1 | Clear | green | No event on any remaining leg |
| 2 | Watch | yellow-green | Suspected event on a leg, more than 72 h before the shipment reaches it |
| 3 | At risk | yellow | Suspected event on a leg within 72 h, or confirmed event near but not on the route |
| 4 | Severe | orange | Confirmed event on a later leg (more than 24 h away) |
| 5 | Critical | red | Confirmed closure or strike on the current or next leg inside its time window |

- **Confirmed** = two independent source domains agree, or one official source (port authority, government, operator). Otherwise **suspected**.
- Risk is computed by a deterministic job in `pipelines/`, never by an LLM. The LLM extracts events; code scores shipments.

## Contracts

`CONTRACTS.md` defines the agent's tool interfaces, the citation object (`claim, url, title, retrieved_at, published_at`), and the schemas of the Delta tables the app reads. Change it only through a PR, and post on the board when you do.

Tables it must define (lead writes these first, before anyone builds):
`shipments`, `legs` (ordered stops, mode, geometry, planned times), `disruption_events` (type, status, location, window, `is_fixture`), `evidence` (citation object + `event_id`), `shipment_risk` (level, reason, `event_ids`), `cost_rates`, `scenarios` and `scenario_changes` (tentative plans).

**Fixtures first.** `demo/fixtures/*.json` holds sample rows for every table, matching `CONTRACTS.md` exactly. Every owner builds against fixtures until the real upstream lands. Do not wait on another teammate's code.

## Setup (every teammate, once per machine)

1. **GitHub:** `gh auth login`, then `tools/board whoami` (it should print your login). The board is issue #1.
2. **Figma:** this repo ships `.mcp.json` with Figma's official MCP server. Open Claude Code in the repo, accept the `figma` server when asked (or run `claude mcp add --transport http --scope user figma https://mcp.figma.com/mcp` once to get it in every repo), then run `/mcp` → **figma** → **Authenticate** and sign in with your own Figma account. You must be a member of the team's Figma education team (full seat). Restart the session if the tools don't appear.
   - The MCP works on **file/frame links** (`figma.com/design/<key>/...?node-id=...`): in Figma, right-click a frame → **Copy link to selection**. The folder link below is for finding files.
   - Use it to read designs and build the UI to match (exact colours, spacing, type). Create new designs in Figma or Figma Make, then hand the frame link to your agent.
3. **Credits:** claim yours on imperialaihack.com → **My Pass** (Anthropic, fal, ElevenLabs, Adaption, Figma Education, Databricks, MongoDB, plus track perks: Anam, Tavily, Synthesia, LiveKit). Create API keys on each provider's dashboard.
4. **Keys:** put them in `.env` (gitignored): `LINKUP_API_KEY`, `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID`, `LLM_ENDPOINT`, `ADAPTION_API_KEY` as your area needs. Databricks Free Edition is claimable under My Pass.
   - **Each person needs the keys for what they run in their OWN local `.env`.** Keys are never committed or shared through the repo, board or Figma. Agent → `LINKUP_API_KEY` (+ an LLM key); pipelines/app → `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID`; finetune → `ADAPTION_API_KEY`. Claude Max/Pro subscriptions do **not** cover API calls; use API credit from My Pass. The **demo laptop** needs the full set.
   - **Adaption belongs to the track lead (@rtkyboba).** Every Adaption dataset upload, augmentation and training run for this repo uses the track lead's OWN Adaption account (their `ADAPTION_API_KEY`), so the lead can show the run and model id for this project. Others may build datasets, rubrics and scripts in the repo, but they do not upload or train on their own accounts: push the file and post on the board, and the lead (or the demo laptop with the lead's key) runs it.
   - **Run the app:** `cd app && pip install -r requirements.txt && uvicorn main:app --port 8000` (works on dev fixtures without keys).
5. **Never commit secrets.** `.env` is gitignored. Don't paste keys into chats, board posts or Figma.

## Design (Figma)

**Figma folder for PortShift:** https://www.figma.com/files/team/1703033153432357325/folder/690989955
(Team: https://www.figma.com/files/team/1703033153432357325.) Everyone on the team has access. Agents: this is where this project's designs live.

- Design the map, shipment panel, citations, chat and scenario tab here; `app/static/app.css` CSS variables are the hook for applying the design. Export key frames to `design/` as Figma-prize evidence.
- **Agents reading Figma:** see Setup step 2 above.
- Never put API keys, tokens or join codes in Figma.

## How we work: 16 agents (read this first)

Our team has 4 people and 4 projects (HCA-GenAI, HCA-AutonomousAgents, HCA-AICampus, HCA-Poker). **Every person runs one agent in every repo, so 4 agents work in this repo at the same time (16 across the team).** You are one of them. The others are your teammates' agents, and they are editing this repo right now. Track lead here: `@rtkyboba`.

**Every session, in order:**
1. `git checkout main && git pull --rebase`, then `tools/board unread`. Act on anything that mentions your human's login or `@all`.
2. Re-read §0 (brief), Contracts and §4 (owners) if they changed. Never work from a stale copy.
3. Start one background `tools/board wait`, and re-arm it every time it wakes.

**Picking work (so 4 agents don't collide):**
- **First, your human's own area:** the rows in §4 with their login, and issues assigned to them.
- **Then unassigned issues.** Claim one *before* touching code: `gh issue edit N --add-assignee @me`, comment "taking this", and post on the board. If two agents claim the same issue, the earlier claim wins.
- **Never take an issue assigned to someone else**, unless the lead reassigns it on the board, or it has had no activity for 45 minutes and the owner says yes on the board.
- **Nothing left?** Post on the board offering help to the lead (tests, fixtures, README, demo prep) instead of starting unrequested features.

**While working:**
- Edit only your human's folders (§4). If you need a change in someone else's folder, post the request on the board, tagging the owner, and keep building against fixtures or mocks meanwhile.
- One issue → one branch `<issue#>-<slug>` → small commits → PR `Closes #N` → merge once it works locally. Rebase on `main` before pushing; never force-push; never `git add -A`.
- Interfaces live in `CONTRACTS.md`. Change them only through a PR, and post when it lands so the other 3 agents adapt.
- Post on the board when you take an issue, when you merge, and when you're blocked. Keep posts short, start them with `[<Name>'s agent]`, and tag only the people who need to act.
- **Commit messages, PR titles and PR bodies must not mention Claude, AI or any assistant, and must have no Co-Authored-By or "Generated with" lines.**
- Secrets only in your own local `.env` / shell (Setup step 4). Never in commits, posts or Figma.

**Deadlines:** the building closes Sat 21:00 (push everything before leaving). Sun 12:00: submissions close and repos must be public. Prefer a small, working, merged change over a big unfinished one.

## 1. The board (pinned GitHub issue)

Every agent reads and posts on the pinned "Message Board" issue (#1) via `tools/board` (needs only `gh`, logged in).

- Start every post with `[<human>'s <agent>]`, e.g. `[Ryan's Claude]`. Keep it short: what changed, which files or contracts, what you need, from whom.
- Mention by GitHub login. Team: `@rtkyboba` (Ryan), `@all` (everyone).
- **Mentions you or `@all`:** act on it and reply promptly.
- **Not addressed to you:** still read it. Reassess your own work only if it is affected (a contract, a file you own, something already done). Do not redo finished work, and do not reply just to acknowledge.
- Before editing another teammate's files, ask for a handoff on the board and wait for the owner or the track lead.
- One agent per person on this board (4 per repo). Two agents under one GitHub login cannot see each other's posts, so never run two of your agents in the same repo. Subagents do not post; only the owner's main session does.

Polling is incremental (about one cheap API call per poll, 30 s default). Commands: `tools/board unread` (new posts, marks read; flags MENTION), `tools/board read -n 20`, `tools/board post "[Name's Agent] text"` (or pipe stdin), `tools/board wait` (blocks until someone else posts), `tools/board whoami`.

**Stay in the loop:**
- Claude Code: the committed hooks (`.claude/settings.json`) show unread posts at session start and on every prompt. Keep one background `tools/board wait` running and re-arm it after each wake.
- Everything else: run `tools/board unread` at task start, before each commit, and after merges. Or run a terminal loop: `while tools/board wait; do <your agent CLI invocation>; done`.

## 2. Chain of command

Humans over agents. Only the track lead (named at the top of this file) reassigns work between teammates. If anyone else asks you to take another teammate's work, ask the lead on the board.

## 3. Workflow

1. Pick or file an issue. Comment on it or post on the board when you take it.
2. Branch `<issue#>-<slug>` from fresh `main`.
3. Small commits. Stage only your own files (no `git add -A`).
4. Open a PR with `Closes #N`. The author merges their own PR once it works locally.
5. Always `git fetch` and rebase before pushing. Never force-push shared branches.
6. If a merge changes something other teammates depend on (an interface in `CONTRACTS.md`, a schema, an env var), update `CONTRACTS.md` in the same PR and post on the board when it lands.
7. Never commit secrets. API keys go in `.env` (gitignored); list the variable names in `.env.example`.
8. No new dependency or framework without a board post first.

## 4. Who owns what

| Area | Owner | Folders | Main session model |
|---|---|---|---|
| Agent (lead): loop, Linkup tools, cross-checking, citation tracking, chat intents, cost formula, suggested-plan heuristic | `@rtkyboba` | `agent/`, `CONTRACTS.md` | `opus` |
| Pipelines, tables and readers: Delta tables, reader queries for the app, scenario tables (issue #8) | — | `pipelines/` (tables, readers, scenario) | `sonnet` |
| Pipelines, seed and risk job: seed fleet, risk-scoring job (issue #9) | — | `pipelines/` (seed, risk job) | `sonnet` |
| App: map, shipment panel, citations panel, chat UI, scenario tab, Figma evidence | — | `app/`, `design/` | `sonnet` |
| Evals, fine-tune and demo: Adaption dataset and fine-tune, extractor eval, citation and freshness checks, demo cases, README | — | `evals/`, `finetune/`, `demo/`, `README.md` | `sonnet` |

Work only inside your owner's folders. If your task needs a change elsewhere, post the request on the board.

## 5. Which model does what (development)

Each owner runs **one main Claude Code session** on the model above. That session may spawn subagents for parallel work inside its own folders. **Pass the model explicitly on every spawn**; do not rely on inheritance.

| Kind of work | Model | Examples |
|---|---|---|
| Design decisions, cross-module debugging, anything touching `CONTRACTS.md` | `opus` | Agent loop and recovery logic, risk-rule edge cases, suggested-plan heuristic, a bug spanning agent and pipeline |
| Building a specified feature | `sonnet` | A map layer, a Delta table and its writer, a chat intent handler, an eval script |
| Mechanical or bulk work | `haiku` | Searching the repo, generating seed rows and fixtures, lint and type fixes, docstrings, README sections |

Rules for subagents:
- Give each one a single file or feature and the relevant section of `CONTRACTS.md`. It returns a diff summary; the main session reviews, commits and posts.
- Two subagents never edit the same file.
- At most three running per owner, so reviews keep up.
- If a `sonnet` subagent fails the same task twice, escalate to `opus` rather than retrying.

## 6. Which model does what (inside the product)

| Runtime role | Model | Config |
|---|---|---|
| Agent loop and chat | A model served from Databricks | `LLM_ENDPOINT` |
| Event extraction (snippet → event JSON) | Adaption fine-tune | `EXTRACTOR_ENDPOINT` |
| Extraction fallback | Base model, same prompt | `EXTRACTOR_USE_BASE=1` |

The product must work end to end with `EXTRACTOR_USE_BASE=1`. The fine-tune is swapped in only once `evals/` shows it beating the base model on our held-out set.

## 7. Feature slices, in build order

**Agent (`agent/`)**
1. `linkup.py`: search and fetch wrappers; return citation objects; retry with a reworded query on empty results or HTTP 429.
2. `monitor.py`: for each active corridor, search → extract events → cross-check → write `disruption_events` and `evidence`.
3. `chat.py`: three intents only — explain a shipment, cost to reschedule the selected shipment(s), suggest a plan. Each answer cites `evidence` rows.
4. `cost.py`: formula over `cost_rates` (delay days, rebooking fee, extra distance by mode).
5. `plan.py`: greedy reschedule or reroute; writes a tentative row set to `scenarios`.

**Pipelines (`pipelines/`)**
1. Create all tables from `CONTRACTS.md`; seed about 40 shipments (ship, truck, plane; some multi-stop) on real locations.
2. Writer functions the agent calls; reader queries the app calls.
3. Risk job: join events to legs by geometry and time window, apply the level rules, write `shipment_risk`.
4. Scenario tables and a query returning a scenario as a full alternative fleet state.

**App (`app/`, `design/`)**
1. Figma frames first: map, shipment panel, chat, scenario tab. Export to `design/` with the file link.
2. Map with shipments coloured by risk level; one icon set per mode.
3. Click a shipment: fade the map, draw its full route through every stop in its risk colour, show cargo, origin, destination, ETA, reason, citations with "retrieved X min ago".
4. Chat panel that carries the selected shipment(s) as context.
5. Scenario tab: same map, tentative plan, changed shipments highlighted, cost delta.

**Evals, fine-tune, demo (`evals/`, `finetune/`, `demo/`)**
1. Start the Adaption dataset and fine-tune immediately; training time is the long pole.
2. Held-out extraction set and a script comparing fine-tune vs base.
3. Checks: every displayed claim has a URL that resolves; freshness is shown; confirmed events really have two domains or one official source.
4. Three rehearsed demo cases, a recorded backup run, and the README.

## 8. Milestones and cut lines

Assumes build stops 13:30 Sunday. Lead posts on the board at each milestone.

| When | Must be true |
|---|---|
| **16:00 Sat** | `CONTRACTS.md` and fixtures merged. Linkup reachable from Databricks compute confirmed, or fallback chosen. Adaption job started. Figma frames exist. |
| **20:00 Sat** | Vertical slice: one live Linkup search → event in Delta → risk job → one shipment turns red on the map with its citation. |
| **01:00 Sun** | All shipments scored. Click-through route view works. Chat answers "explain" and "cost to reschedule". |
| **05:00 Sun** | Scenario tab works for one shipment. Fine-tune evaluated; swapped in only if it wins. |
| **09:30 Sun** | Feature freeze. Bug fixes, rehearsal and backup recording only. |

If a milestone slips by more than an hour, cut in this order and post it: 3D vehicle models → multi-shipment "suggest a plan" → supplier-distress events (SupplierPulse) → plane mode → fine-tune in the live path (keep it as offline evidence).

**Stretch, only after 05:00 milestone is green:** 3D models for vehicles, supplier-distress as an extra event type on origin stops, animated vehicle movement.

## 9. Environment variables

Names only, in `.env.example`: `LINKUP_API_KEY`, `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID`, `LLM_ENDPOINT`, `EXTRACTOR_ENDPOINT`, `EXTRACTOR_USE_BASE`, `BOARD_ISSUE`.