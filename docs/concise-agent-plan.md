# Concise agent plan

Status: in progress. Iterations 1, 2 and 2.1 are on the `concise` profile (2026-11-17).

## Goal

- The agent gives short answers by default and gives more only when the user asks.
- Each model call uses fewer input tokens and each turn uses fewer model calls.
- Each instruction has one home. No rule is written in two places.
- GOLD shows no capability regression at each step.

The reference is the DSS agent prompt
(`dss-agentic-ai-services/packages/dss-agent/src/dss_agent/prompts`): six
numbered markdown sections, 9.7k characters in total, ranked rules, and one
explicit length rule ("about 60 words", with three named exceptions).

## What the agent sends today

Measured on this branch with `get_prompt()` and the bound tool schemas.

| Part | Size (chars) | Sent |
|---|---|---|
| System prompt, `default` profile | 14,500 | each orchestrator model call |
| Tool schemas, 20 tools | 19,000 | each orchestrator model call |
| `pick_dataset` tool message (tree cover loss) | about 5,000 | each later call in the thread |
| `generate_insights` tool message | cautions again, 1,800 average | each later call in the thread |
| Skill body (`analyze`) | 2,800 | after `read_skill`, each later call |
| Dataset catalog, 12 files | 133,000 | by field, see below |

An analysis turn makes about six orchestrator model calls (`read_skill`,
`pick_aoi`, `pick_dataset`, `pull_data`, `generate_insights`, final reply).
Each call carries the fixed 33,500 characters (about 8,000 to 9,000 tokens).

## Findings

### 1. No length rule exists

The prompt has no instruction about answer length. Four instructions push the
other way: "markdown with blank lines between sections", "surface the relevant
dataset cautions / methodology notes", "surface follow-up suggestions", and
"provide short progress messages between tool calls" (`analyze` skill).

### 2. Each tool is described two times

Each tool has a docstring (sent as the schema description) and a
`prompt_fragment` in its `ToolSpec` (sent in the system prompt). The two texts
say the same thing in different words. The fragments are about 7,500
characters.

### 3. The same rule appears in three or four places

| Rule | Places |
|---|---|
| `search_insights` is terminal | tool fragment, docstring, routing row |
| Do not restate a tool's nudge | `send_nudge` fragment, docstring, three bullets in "Nudges" |
| Call tools one at a time | system prompt, `analyze`, `pull-data` |
| Stop when `pick_dataset` returns no dataset | `pick_dataset` fragment, `analyze`, `pull-data` |
| `search_blogs` routing and citation markers | fragment (three paragraphs), skills list, `wri-insights`, `explore` |
| When to use `analyze` or `pull-data` | each skill's `when_to_use`, each skill body, routing section |

### 4. The catalog YAML mixes three kinds of content

- Structured metadata: ids, tile URLs, dates, parameters, endpoints. YAML is
  correct for this. GOLD reads these fields (`sync_zeno_catalog.py`).
- Display text for users: `description`, `methodology`, `cautions`,
  `citation`, `providers`. 61,000 characters.
- Instructions for models: `prompt_instructions`, `code_instructions`,
  `presentation_instructions`, `selection_hints`, and the context layer
  descriptions. 53,000 characters, as long one-line strings.

Problems:

- One rule is written in many fields. In `tree_cover_loss.yml` the
  "tree cover loss, not deforestation" rule is in five fields. The
  "intact forest" wording rule is in three, each time with examples.
- `prompt_instructions` (15,500 characters) is not used by the analyst when
  `code_instructions` exists. The zap planner still reads it.
- `cautions` is display text, but the full text goes to the analyst prompt,
  the `pick_dataset` tool message and the `generate_insights` tool message.
- The `pick_dataset` tool message puts description, usage notes, cautions and
  presentation instructions into the orchestrator history, where they stay
  for the remainder of the thread.

### 5. A skill read costs one model call

Most requests are analysis requests. Each one pays one extra orchestrator
round trip to read the 2,800-character `analyze` skill.

## Target structure

### Orchestrator prompt: numbered markdown sections

Same pattern as DSS, in `src/agent/prompts/`:

```
01-role.md        who the agent is, what is in scope
02-rules.md       ranked rules: data only from tools, short answers, language
03-work.md        the default analysis workflow and the stop conditions
04-surfaces.md    UI selections, nudges
```

- `get_prompt()` joins the sections and adds only the parts that depend on the
  profile (skills list, surface block).
- The tool list in the system prompt is removed. The docstring is the single
  description of a tool. The system prompt keeps only rules that cross tools
  (order, stop conditions).
- The `analyze` workflow moves into `03-work.md`. Skills stay for the less
  frequent workflows (dashboard, imagery, explore, research).
- `ToolSpec.prompt_fragment` and `ROUTING_ROWS` are deleted or reduced to a
  one-line gate.

### Dataset catalog: metadata in YAML, guidance in markdown

Keep `catalog/<dataset>.yml` for structured metadata and display text. Move
the model instructions to `catalog/<dataset>.md`, with one section for each
consumer:

```
## Select     read by pick_dataset
## Chart      read by the analyst code executor
## Write      read by the text generator and the orchestrator
## Caveats    two or three lines, the short form of `cautions`
```

Each rule is written one time, in the section of the consumer that enforces
it. The full `cautions` and `methodology` stay as display text and no longer
go into prompts. `prompt_instructions` is removed after the zap planner reads
the new sections.

### Reply style

One ranked rule in `02-rules.md`, modelled on DSS rule 3:

- Give the answer and its key figures in about 100 words. The chart carries
  the detail. The limit is a start value: change it if the vibe test shows
  that answers are too short or too long.
- Longer answers are permitted for a list of options, for steps, and when
  the user asks for detail.
- Show a caution only when it is important for this request. The trigger is
  in the user's words or in the result. Example: the user says
  "deforestation" and the dataset measures tree cover loss, so the answer
  states the difference in one line. A caution with no trigger is not shown;
  the dataset card has the full text.
- No progress messages between tool calls. No headings in a short answer.

Each dataset's `## Caveats` section therefore lists each caution with its
trigger ("when the user says X", "when the period crosses 2010"), not as
text to repeat in each answer.

### Rollout: a temporary `concise` profile

The short style is for all profiles. During the work it lives in one
temporary profile, `concise`, that extends `default`:

- `AgentConfig` gets one field that selects the prompt section directory
  (and later the short tool messages). The cost is small because profiles
  and feature flags exist already.
- It can be deployed and vibe tested apart from the default behaviour.
- GOLD can run `--ff concise` and the default profile on the same build and
  the same environment. This removes environment drift from the comparison.
  It is the one permitted comparison across `ff` values, and it is used only
  for the efficiency report, not for the regression trend.
- When the result is accepted, `concise` becomes the default and the profile
  and the old prompt code are deleted in the same PR. Two prompt variants
  must not stay in the code.

Changes that have no behaviour variant (the catalog split, the instrumentation)
go directly to all profiles.

## How to measure

### Metrics

| Metric | Source | Type |
|---|---|---|
| Regression count on gating checks | `tools/diff_runs.py` | guardrail, must be zero |
| Input and output tokens for each case | thread state `usage_metadata` or the Langfuse trace | target |
| Orchestrator model calls for each case | thread state messages | target |
| Latency for each case | `latency_s`, already in the ledger | target |
| Final answer length in words | `final_answer` in the run artifacts | target |
| Static prompt size for each profile and dataset | new script, no API calls | target, deterministic |

The efficiency metrics are info-only. They never change a row verdict. This
follows the GOLD rule that new measures start info-only.

### Step 0: instrumentation and baseline

1. Add `tools/prompt_size.py` (name open): it prints the token count of the
   system prompt, the tool schemas and each dataset's guidance for each
   profile. Add a snapshot test so that prompt growth is visible in review.
2. Record tokens, model calls, tool calls and answer words for each ledger
   entry, next to `latency_s`. First find out if the thread state payload
   carries `usage_metadata`. If it does not, read the Langfuse trace.
3. Add a report (`tools/efficiency_report.py`) that compares two runs:
   median and p90 for each metric, for each case group.
4. Run the baseline two times on the same build (A/A). The difference between
   the two runs is the noise floor. A later delta that is smaller than the
   noise floor is not a result.

### Baseline and noise floor (2026-11-16)

Two runs of the same build (`feat/curated-views` at `1bf4a084`), local API,
orchestrator `gemini-3-flash-preview`, default profile, 30 cases, 3 trials.
The runs are not committed.

| Metric (median for each case) | Run A | Run B | A/A difference |
|---|---|---|---|
| Answer words | 198 | 210 | 6% |
| Orchestrator input tokens | 44,428 | 43,319 | 2% |
| Orchestrator output tokens | 558 | 545 | 2% |
| Model calls | 5 | 5 | 0 |
| Latency (s) | 26.7 | 27.2 | 2% |

- The answer length today is about 200 words, with a p90 of about 265.
- The two runs differ by 2 gating checks (`charts_answer` on 1-033 and
  1-087) and 2 info-only checks, with no change to the agent. The rule
  "zero regressions" is therefore applied as follows: run each case that
  flips one more time with 3 trials. It is a regression only if it fails
  again.
- A change in a median is a result only if it is larger than about 10% for
  answer words and 5% for tokens and latency.
- Run a new baseline on the same day as each candidate. Do not compare
  with these numbers after the model or the data changes.

The subset is the file `evals/gold/cases/subsets/inner-loop.txt` (30 cases;
use `gold run --ids-file`).

### Where to run

- Inner loop: local API, a fixed subset of about 30 cases across the 16 case
  groups, 3 trials. Compare only local runs with local runs. Do not commit
  them (GOLD rule).
- For each candidate PR: the full set, 3 trials, on the ephemeral environment
  (`gold-ephemeral.yaml`), against an ephemeral run of `main` at the branch
  point.

### Decision rule for each iteration

- One class of change for each iteration.
- Keep the change if the regression count is zero and the target metric
  improves by more than the noise floor.
- If a case fails because the new behaviour is correct (for example, a case
  expects the long caution text), change the case in the same PR and say so.

## Iterations

| # | Change | Main metric | Main risk |
|---|---|---|---|
| 1 | `concise` profile with the reply style rule; remove progress messages; cautions by trigger | answer words, output tokens | `agent_answer`, `expected_text_match` cases that expect cautions |
| 2 | Orchestrator prompt as markdown sections; one description for each tool; each rule one time | input tokens for each call | routing checks (scope, nudge, recall) |
| 3 | `analyze` workflow in the base prompt | model calls, latency | pull-only and dataset-only scope cases |
| 4 | Short tool messages from `pick_dataset` and `generate_insights` | input tokens for each turn, multi-turn cases | wording rules that the orchestrator no longer sees |
| 5 | Catalog split: guidance by consumer, short caveats | static size, subagent tokens | chart and wording checks for each dataset |
| 6 | Subagent prompts (analyst workflow and JSON schemas, `pick_aoi`) | subagent tokens, latency | chart validity |

Iteration 1 is first because it is the smallest diff and gives the visible
change. Iterations 2 to 4 give the token and latency gain. Iteration 5 is the
largest edit and needs review by the data owners.

## Decisions (2026-11-16)

1. Default length: about 100 words. Adjust after the vibe test.
2. Cautions: only where important, with a trigger. Not in each answer.
3. GOLD source: `evals/gold` in this repository only. The external
   `wri/gnw-gold-evals` repository is not used.
4. Scope: all profiles. A temporary `concise` profile is used for separate
   deployment and comparison, then merged into the default and deleted.

## Iteration 1 result (2026-11-16)

Default profile against `--ff concise`, same API process, inner-loop subset,
3 trials. Runs are not committed.

| Metric (median for each case) | Default | Concise | Change |
|---|---|---|---|
| Answer words | 211 | 66.5 | -68% |
| Answer words, p90 | 290 | 99 | -66% |
| Orchestrator output tokens | 554 | 298 | -46% |
| Orchestrator input tokens | 49,375 | 45,614 | -8% |
| Model calls | 5 | 5 | 0 |
| Latency (s) | 30.9 | 36.9 | +19% |

- Gating checks: 1 regression (`expected_text_match` on 1-080), 2 recoveries.
- 1-080 ("Show me deforestation in Brazil", primary forest layer) fails in
  3 of 3 trials, and again in 3 of 3 after the trigger text was made wider.
  The default profile passes 2 of 3. The case expects a caution about loss
  against deforestation. The catalog tells the model that "primary forest
  loss" is the correct term with this layer. This is an open product
  question, not noise.
- The caution rule is not followed well. Cautions with no trigger are still
  in some answers (1-033, 1-076), and the caution with a trigger is absent
  (1-080). A rule in the orchestrator prompt is not sufficient. The trigger
  must come with the caution in the dataset guidance (iteration 5).
- `answer_traceability` (info-only) evaluates on 18 fewer cases. Find the
  cause before the short style becomes the default.
- The latency increase is not explained. The two runs were not at the same
  time. Measure again with the runs in the opposite sequence.

## Iteration 2 result (2026-11-16)

### What changed

All changes are behind the `concise-replies` flag. The default profile and
the other profiles send the same prompt and the same tool schemas as before
(checked byte for byte on the map, dashboard and no-page prompts).

1. **Prompt as numbered markdown sections.** `src/agent/prompts/sections/`
   holds `01-role.md`, `02-rules.md` (ranked rules), `03-work.md` (order,
   routing rows, stop conditions) and `04-surfaces.md` (app selections).
   `build_prompt` joins them and adds the skills list and the current
   surface. A block between `<!-- tool: NAME -->` (or `<!-- skill: NAME -->`)
   and `<!-- end -->` is kept only when the profile can serve that tool or
   skill. Each rule is written one time. The date is not in the prompt
   (the session block has it), so the prompt does not change from day to
   day.
2. **One description for each tool.** The concise prompt has no tool list.
   The schema description is the one description of a tool. The concise
   profile binds copies of 16 tools with short descriptions
   (`src/agent/prompts/tool_descriptions.py`). The docstrings did not
   change, so the default profile did not change.
3. **Dashboard schemas only when needed: built, then removed.** A
   middleware left the nine dashboard edit tools out of a model call until
   the thread had read skill `dashboard`, or while the user was on a
   dashboard page. It gave 35% of the static saving (6,255 of 17,929
   characters). The user rejected it: tools that appear and disappear by
   page and by thread history are fragile (the agent can start on the
   dashboard page, and a request can need a dashboard tool with no skill
   read). The commit is reverted. All tools are sent on each model call.

### Static size (`scripts/prompt_size.py`)

| Part (characters) | Default | Concise | Change |
|---|---|---|---|
| System prompt | 14,536 | 7,629 | -48% |
| Tool schemas, all bound tools | 18,828 | 14,061 | -25% |
| Fixed cost of a model call | 33,364 | 21,690 | -35% |

With the ratio of the default (33,364 characters are about 7,570 tokens),
the concise fixed cost is about 4,900 tokens for each model call. With the
dashboard middleware it was 15,435 characters (-54%).

### GOLD (inner-loop subset and dashboard cases, 3 trials)

Measured again on 2026-11-17, after the removal of the dashboard
middleware and with the iteration 2.1 changes (see below): all tool
schemas on each call, no `state` argument, one line for each skill.

Default profile against `--ff concise`. One API process from this branch
(`df4395b9`), freshly started. The two runs were started at the same time.
35 cases: the inner-loop subset and the dashboard cases 1-096 to 1-102.
The runs are not committed.

| Metric (median for each case) | Default | Concise | Change |
|---|---|---|---|
| Orchestrator input tokens | 45,983 | 26,583 | -42% |
| Orchestrator input tokens, p90 | 56,736 | 31,634 | -44% |
| Orchestrator output tokens | 526 | 284 | -46% |
| Answer words | 208 | 74 | -64% |
| Answer words, p90 | 257 | 99 | -62% |
| Model calls | 5 | 5 | 0 |
| Latency (s) | 27.5 | 24.7 | -10% |

- The input saving (19,400 tokens for each case, about 3,900 for each
  model call) is the same as with the dashboard middleware (-40%). The
  `state` fix and the shorter skills list make up for the dashboard
  schemas that are sent again. The cached part of the input is about
  2,000 to 4,000 tokens for each call (see "Step 5" below).
- The laptop slept during the runs. Each profile has one trial with an
  error (HTTP 500 from `GET /api/threads/{id}/state`: 1-101 on default,
  1-100 on concise). Latency figures include no sleep time (`latency_s`
  is for each trial), but treat them with care.

Gating checks, before the re-run: 4 regressions (`chart_produced` on
1-078, `dashboard_widgets_match` on 1-100, `charts_answer` on 1-033,
`expected_text_match` on 1-080), 0 recoveries. Each flip, and the error
cases, were run again with 3 trials on both profiles at the same time:

| Case | Default re-run | Concise re-run | Verdict |
|---|---|---|---|
| 1-078 `chart_produced` | 3 of 3 | 3 of 3 | noise |
| 1-100 `dashboard_widgets_match` | 3 of 3 | 3 of 3 | noise |
| 1-101 (error on default) | 3 of 3 | 3 of 3 | noise |
| 1-033 `charts_answer` | fails 3 of 3 | fails 3 of 3 | not caused by this change, see open item 1 |
| 1-080 `expected_text_match` | passes 2 of 3 | passes 1 of 3 | the caution question of iteration 1, not new |

- All seven dashboard cases pass on both profiles. Not measured: a thread
  where the dashboard request comes in a later turn.
- `charts_answer_judge` (info-only) fails on 1-004 and 1-009 on concise:
  the short answer leaves out an explanation that the judge wants.
- `answer_traceability` (info-only) is lost on 20 cases, for the reason
  given before (the check reads only bold figures).

### Open items

1. **1-033 gives the wrong figure on both profiles.** Both profiles answer
   1,435.95 ha for Corona Forestal in 2023; the case expects 79.25 ha, and
   `agent_answer` fails on both. The default passes `charts_answer` only
   because its 2001-2025 chart has a different value near 79 (78.98). The
   concise analyst draws only 2023. The case notes say that 1,436.02 ha was
   a wrong value from an earlier run. Triage the AOI (which WDPA polygon
   the agent selects) apart from this plan.
2. **A parallel tool call.** In one trial of mt-001 the model called
   `pick_aoi` and `pick_dataset` in the same step. Both set `nudge`, and
   LangGraph stopped the run (`INVALID_CONCURRENT_GRAPH_UPDATE`). The rule
   "one at a time" is in both prompts. It did not happen again in 3 trials.
   A code guard is more reliable than a prompt rule: for example
   `parallel_tool_calls=False` where the model supports it, or a reducer on
   `nudge`.
3. **Done (`da337d50`). Injected `state` argument in the schemas.** Eleven tools declare
   `state: Annotated[Dict, InjectedState] | None`. The tools get the state
   at run time (the dashboard cases pass), but with `| None` outside the
   `Annotated` the schema filter does not remove the argument. The model
   therefore sees a `state` parameter (about 70 characters for each tool,
   and the model can fill it). Fix for all profiles:
   `Annotated[Optional[Dict], InjectedState] = None`. Check that the tools
   still get the state.
4. **Done (`df4395b9`). Skills list.** The skills list is now the largest generated part
   (about 2,300 characters). Each skill has a `description` and a
   `when_to_use` that say the same thing in part. They are shared with the
   default profile, so they did not change.
5. **When concise becomes the default:** move each text of
   `tool_descriptions.py` into the docstring of its tool and delete the
   module; delete `ToolSpec.prompt_fragment`, `ROUTING_ROWS`,
   `tool_descriptions()` and the old `get_prompt` body. The
   `curated-charts-first` flag puts its `chart` argument guidance in the
   `prompt_fragment` of `generate_insights`. That guidance must move into
   the docstring of the curated variant before the tool list goes.
6. **Done (`efd2c657`). Review of the rewrite (2026-11-16).** The default prompt and the
   argument schemas are identical to before. No invented facts were found
   in the short tool descriptions. Differences that the review found:
   - Rule 7 no longer says that a caution with no trigger is left out.
     Iteration 1 showed that cautions with no trigger still appear, so the
     sentence must come back.
   - `inspect_view_context` no longer names "the report" as a trigger, and
     no longer says to call it only when the details are necessary.
   - `show_planet_imagery` no longer says that the tool falls back to
     Sentinel-2 by itself outside its footprint.
   - The routing rows no longer say "unless asked for more".
   - All seven dashboard cases and the imagery case pass on both profiles
     (3 trials), measured with the middleware. Not measured: a thread
     where the dashboard request comes in a later turn.

## Rule audit of the concise prompt (2026-11-16)

Each rule of the default prompt (`get_prompt` for the `default` profile),
of `ROUTING_ROWS`, of each `ToolSpec.prompt_fragment` and of each tool
docstring, and where the concise profile has it now. "Description" is the
short tool description in `tool_descriptions.py`. `pull_data`,
`generate_insights` and `read_skill` keep their docstrings on both
profiles. The skills list and the skill bodies are the same on both
profiles.

The four review findings and three rules that this audit found are put
back (marked "restored").

### System prompt

| Default rule | Concise |
|---|---|
| Role: answer with tools and subagents, never invent data | 01-role |
| `Today: <date>` | Dropped. The session block gives the date on each call, and a date in the prompt changes the prompt each day. |
| Trust the session block; do not resolve the AOI or the dataset again unless the user changes it | 01-role (also names the fields of the block) |
| Call tools one at a time | 03-work |
| Tool list (`# Tools`, `# Subagents`) | Dropped as a list. Each line is in the tool description, or in 03-work when it crosses tools (rows below). |
| Skills: call `read_skill` only when "use when" matches; usually one skill | 5. Skills |
| Routing intro: one skill or one row; do not make a dataset, AOI or pull request into a full analysis | 03-work |
| Row: dataset only, then stop; no AOI, pull or insights unless asked | 03-work (restored: "unless the user asks for more") |
| Row: AOI only, then stop unless asked for more | 03-work (restored: "unless the user asks for more") |
| Row: recall with `search_insights`, then stop; never followed by `pick_aoi`, `pick_dataset`, `pull_data`, `generate_insights`; one-line reply | 03-work: "Never follow it with another tool". The sentence "show/recall/pull up is a recall request, never new analysis" is merged into the row's examples. |
| Global and continent scale; "Global World" for a worldwide question | 01-role. The example question is dropped. |
| Concessions: relay and stop; never give figures for concessions that `pick_aoi` did not select | Rule 3 |
| Reply in the session block's language | Rule 4. The note on how the language is computed is dropped: the session block computes it. |
| Markdown with blank lines between sections | Replaced by rule 5 (no headings in a short answer). Decision of iteration 1. |
| No raw JSON or code blocks | Rule 8 |
| Surface the follow-up suggestions | Reversed by rule 6 (the insight card shows them). Decision of iteration 1. |
| After `generate_insights`: summary of the chart and the relevant cautions | Replaced by rules 6 and 7. Decision of iteration 1. |
| Chart data is full rows or column statistics; with statistics, give only aggregates | Rule 1 |
| Say that a chart was made only when a tool returned it this turn; on a decline, state only the decline | Rule 2 |
| UI selections: acknowledge, check AOI, dataset and date range, new request overrides | 04-surfaces |
| Nudges: a tool's own options are the pending nudge; do not call `send_nudge` after it; summarize and stop | 03-work, stop list, and the `send_nudge` block |
| Nudges: `send_nudge` only for a new set of choices | 03-work, `send_nudge` block |
| Nudges: a plain decline from `pull_data` or `generate_insights`: relay and stop, do not retry with the area selected before | 03-work, stop list |
| Nudges: a pending nudge is not a selection; give the answer back to the tool; check "AOI: none" / "Dataset: none" | 03-work, last paragraph |

Rules that the concise prompt adds: rule 5 (about 100 words), rule 7
(cautions by trigger), "no progress messages" (rule 8), and the stop when
`pull_data` fails or has no data (03-work; the `analyze` skill has it too).

### Tool fragments and docstrings

| Tool | Default text | Concise |
|---|---|---|
| `pull_data` | Run `pick_aoi` and `pick_dataset` first | 03-work, analysis order |
| `read_skill` | Call it one time, after you commit to the skill | 5. Skills ("one time and follow it") |
| `generate_insights` | Needs `pull_data` first | 03-work, analysis order |
| `pick_aoi` | Pass the place verbatim; it extracts, translates, finds subregions and global areas itself; set the type of area when obvious; updates the AOI or returns a question | Description. The example "protected areas in Peru" is dropped. |
| `pick_dataset` | No dataset or alternatives: relay, do not pull | 03-work, stop list |
| `pick_dataset` | Dataset only: no AOI needed, do not ask for a place, no `pick_aoi`, `pull_data` or `generate_insights` unless asked | Description and 03-work row |
| `pick_dataset` | Dataset only: confirm the selection briefly | 03-work row (restored) |
| `pick_dataset` | Call again when the dataset, context layer or a parameter changes; dates clamp to the closest valid range | Description |
| `inspect_view_context` | Page, viewport, layers, AOIs, insights, dashboard; triggers "this", "here", current view, the report, the dashboard, an insight on screen; only when the details are necessary | Description (restored: "the report", "when you need those details to answer") |
| `show_imagery` | Global, any date; date rules; defaults and limits of `window_days` and `max_cloud_cover`; raise only when nothing is found and the user agrees; `pick_aoi` first; regional only | Description |
| `show_planet_imagery` | Amazon alerts; 500 m buffer; from September 2020; published about the 15th; null date gives the latest month, tell the user; other places use `show_imagery`; falls back to Sentinel-2 by itself; regional only | Description (restored: the fallback). "There is never a current-month mosaic" is merged into "published about the 15th of the next month". |
| `search_blogs` | Routing to `explore` and `wri-insights` | Skills list (`when_to_use` of the two skills) |
| `search_blogs` | After `pull_data`, before `generate_insights` | `wri-insights` skill body |
| `search_blogs` | Keep the markers, number by first appearance, never invent URLs, no Sources list | Description and rule 9 |
| `update_insight_display` | Restyle only; no new data; most recent insight by default; `insight_choice` nudge when not clear | Description. "Or running code" is dropped: "no new data or charts" covers it. |
| `search_insights` | Find and show again, all conversations and public ones, no compute | Description. "Terminal" is in 03-work. |
| `send_nudge` | 2 to 4 options; free label; exact button texts; short and clear by itself; not to restate a tool's options | Description (restored: "short") and 03-work |
| `create_dashboard` | AOI in state, `pick_aoi` first; starts empty; name default | Description. "Persistent" is dropped (no decision depends on it). "Use when" is in the `dashboard` skill. |
| `add_to_dashboard` | Defaults of `insight_id` and `dashboard_id`; `section`; own dashboards only; the insight must be one the user can see | Description (restored: the insight rule) |
| `add_map_widget` | `layer` values and their sources; defaults; `title`; `section`; own dashboards only | Description. "Renders focused on the dashboard's area" is dropped: the model makes no choice on it. |
| `add_text_widget` | Write the markdown yourself; no raw data; heading in the markdown; `section`, `position` | Description. "Summary of findings from this conversation" is merged into "summary". |
| `edit_text_widget` | Full replacement; default widget; error lists ids | Description |
| `add_dashboard_section` | Short topical title within the character cap; description optional; position; starts empty; use for several topics | Description; the cap is `maxLength` in the schema; "several topics" is in the `dashboard` skill. "Compose it yourself" for `description` is dropped. |
| `edit_dashboard_section` | Title or description, at least one, full replacement; default section; error lists them | Description ("or both" states "at least one") |
| `move_dashboard_widget` | `section` or `ungroup`, exactly one; position; reorder in place; ids from `inspect_view_context`; own dashboards only | Description |
| All "Use when the user asks to ..." lines of the dashboard tools | `dashboard` skill `when_to_use` and body |

## Iteration 2.1: fixed cost without hidden tools (2026-11-16)

No tool is hidden, deferred or gated. Each step was measured with
`scripts/prompt_size.py` (characters; system prompt + all tool schemas).

| Step | Commit | Concise fixed cost | Default fixed cost |
|---|---|---|---|
| Start (after the revert of the dashboard middleware) | `d4e5ef94` | 21,690 | 33,364 |
| 1. Review fixes and audit restorations | `efd2c657` | 22,012 (+322) | 33,364 |
| 2. Injected `state` argument removed from the schemas | `da337d50` | 20,835 (-1,177) | 32,187 (-1,177) |
| 3. Parameter descriptions | no change | 20,835 | 32,187 |
| 4. One `brief` line for each skill | `df4395b9` | 19,963 (-872) | 32,187 |
| 5. Session block in the user message | not shipped | 19,963 | 32,187 |

Total: concise -1,727 characters (-8%) against the start; -38% against the
default profile.

### Step 3: no parameter has a description

No parameter of a bound tool has a `description` in its schema (the
docstrings have no parsed `Args:` sections). The 4,399 characters of
parameter schemas in the concise profile are names, types, defaults,
`maxLength` and the `area_of_interest` enum. These are constraints, so
nothing is removed.

### Step 5: the session block and the prompt cache

Finding: langchain-google-genai puts each `SystemMessage` (at any position)
into Gemini's system instruction. The session block is therefore part of
the system instruction on each call.

Test: behind the flag, the block went into the user's latest message
instead. Same build, concise profile, inner-loop subset, 1 trial each,
`input_token_details.cache_read` read from the thread state of each call:

| Call | Cache read, block in system instruction | Cache read, block in user message |
|---|---|---|
| 1 | 1,997 | 1,997 |
| 2 | 1,994 | 1,994 |
| 3 | 2,000 | 2,000 |
| 4 | 4,000 | 4,000 |
| 5 | 3,996 | 4,002 |
| Share of all input tokens | 43.7% | 43.3% |

- The position of the block does not change the cache. The cache reads
  come in steps of about 1,000, 2,000 and 4,000 tokens. The cached part
  is longer than the system prompt (about 1,800 tokens). Thus the tool
  schemas come before the block in both cases. This is an inference from
  the numbers: Google does not document the order.
- The smoke diff showed possible behaviour changes with the block in the
  user message (1-082 lost `nudge_match` and `clarification_requested`;
  1-009, 1-050 and 1-134 made no chart). It was 1 trial only, but with no
  gain there is no reason to accept the risk.
- Result: not shipped. The code is reverted.
- The earlier figure "cache reads about 4,000 of 7,570 tokens" is the
  default profile. The concise profile gets about 2,000 to 4,000.
- To cache more, the stable prefix must be longer than the next step
  (about 8,000 tokens), or an explicit cache (Gemini `cachedContents`)
  must be used. Not tried.

## Options not built (decision for the user)

### A. Merge the dashboard tools into fewer tools

Today: eight dashboard edit tools (`create_dashboard`, `add_to_dashboard`,
`add_map_widget`, `add_text_widget`, `edit_text_widget`,
`add_dashboard_section`, `edit_dashboard_section`,
`move_dashboard_widget`), 5,630 of the 13,070 schema characters of the
concise profile. `inspect_view_context` is also used outside dashboards
and stays.

- **Change.** For example three tools: `create_dashboard`,
  `add_dashboard_item(kind: insight | map | text | section, ...)` and
  `edit_dashboard_item(kind: text | section | move, ...)`. The tool code
  dispatches on `kind` to the current functions. The `dashboard` skill
  body and the audit table change with it.
- **Expected saving.** About 2,500 to 3,000 characters (about 650 to 800
  tokens) on each orchestrator call, 13% to 15% of the concise fixed
  cost. Most of these tokens are in the cached prefix, so the saving in
  cost is smaller than the saving in tokens. Latency: no measurable
  change (prefill of 700 tokens).
- **Risk.** Each kind needs other arguments. A flat argument list loses
  the `required` fields of the schema: a missing `text` or `layer` becomes
  a run-time error, not a schema error. A nested `anyOf` of objects is
  less reliable with Gemini function calling. The model can choose the
  wrong `kind`.
- **How GOLD shows a regression.** Cases 1-096 to 1-102:
  `dashboard_created`, `dashboard_aoi_match`, `dashboard_widgets_match`,
  `dashboard_widgets_valid`; more model calls (a retry after a run-time
  error) in the efficiency report. Gap: no case edits an existing
  dashboard in a later turn (text edit, section rename, move). Add such
  cases before this change.

### B. Run `pick_aoi` and `pick_dataset` in the same step

Today: `pick_aoi` → `pick_dataset` → `pull_data` → `generate_insights` →
reply, five orchestrator calls. With both pickers in one step, four.

- **Expected saving.** One orchestrator call for each analysis: its input
  (about 4,700 tokens on the concise profile, 15% to 20% of a case's
  input tokens) and its time to first token. The two subagents also run
  at the same time, so the shorter one is hidden. Estimate: 3 to 6 s of
  about 26 s. Not measured.
- **What must change.**
  1. `pick_dataset` reads `aoi_selection` from the state to remove the
     context layers that do not cover the AOI
     (`get_filtered_contextual_layers`). In the same step it sees no AOI,
     or the AOI of an earlier turn. That filter must move to `pull_data`,
     or `pick_dataset` must run it again after the AOI is known.
  2. Both tools write `nudge` (and `messages`). LangGraph stops the run
     with `INVALID_CONCURRENT_GRAPH_UPDATE` when two tools of one step
     write the same key with no reducer (seen once in mt-001). `nudge`
     needs a reducer, and a rule for two nudges in one step (for example:
     the AOI question comes first, the dataset options wait).
  3. The prompt rule "call tools one at a time" gets one exception.
- **Risk.** The wrong context layer for an AOI outside the layer's extent;
  a lost or wrong nudge when both tools ask a question; the AOI of an
  earlier turn used for the filter in a multi-turn thread.
- **How GOLD shows a regression.** `context_layer_match`,
  `dataset_id_match`, `aoi_id_match`, `nudge_match`,
  `clarification_requested` and `scope_match`; errors in the multi-turn
  cases (mt-001, mt-004); `model_calls` in the efficiency report must
  drop from 5 to 4.
- **Smaller, safe part.** A reducer on `nudge` (or
  `parallel_tool_calls=False`) is worth it without this option: it
  removes the mt-001 error (open item 2).
