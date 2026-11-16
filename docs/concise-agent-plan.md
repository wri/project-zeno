# Concise agent plan

Status: in progress. Iterations 1 and 2 are on the `concise` profile (2026-11-16).

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

### GOLD (inner-loop subset, 3 trials)

**These numbers are from the run with the dashboard middleware.** They are
not measured again after its removal. Expect an input-token saving of
about 25% to 30%, not 40%. Measure again before the numbers are used.

Default profile against `--ff concise`. One API process from this branch.
The two runs were started at the same time, so that load and time of day
are the same for both. The runs are not committed.

| Metric (median for each case) | Default | Concise | Change |
|---|---|---|---|
| Orchestrator input tokens | 44,477 | 26,857 | -40% |
| Orchestrator input tokens, p90 | 56,124 | 32,146 | -43% |
| Orchestrator output tokens | 570 | 284 | -50% |
| Answer words | 211 | 64 | -70% |
| Model calls | 5 | 5 | 0 |
| Latency (s) | 29.9 | 25.7 | -14% |

- The input saving is about 3,500 tokens for each model call (17,620 tokens
  over 5 calls). This agrees with the static estimate.
- Dashboard cases make the same number of model calls (6) on both
  profiles: the default model reads skill `dashboard` too.
- Latency: in iteration 1 the concise run was 19% slower, but the runs were
  not at the same time. With the runs at the same time, concise is 14%
  faster. The iteration 1 latency result was most likely drift.

Gating checks, before the re-run: 2 regressions (`charts_answer` on 1-033,
`chart_integrity` on 1-060), 0 recoveries, and 1 gating check lost
(`dashboard_widgets_valid` on 1-096). One concise trial of mt-001 stopped
with an error. Each of these cases was run again with 3 trials:

| Case | Re-run | Verdict |
|---|---|---|
| 1-060 `chart_integrity` | passes 3 of 3 | noise |
| mt-001 (error) | passes 3 of 3 | noise, see open item 2 |
| 1-096 `dashboard_widgets_valid` | not evaluated | not a regression: the user asks only to create the dashboard. The default added widgets in 1 trial of 3; concise added none. |
| 1-033 `charts_answer` | fails 3 of 3 | not caused by this change, see open item 1 |

- 1-080 passes 2 of 3 on concise (3 of 3 failed in iteration 1).
- `charts_answer_judge` (info-only) on 1-009 fails 3 of 3. The chart and the
  figure (3.93%) are correct. The judge wants the answer to say that
  "highest confidence" means "detected by several systems". The default
  answer says it; the short answer does not.
- `answer_traceability` (info-only) is lost on 20 cases. Cause: the check
  reads only bold figures ("no bolded numeric claim found"), and short
  answers have no bold. This closes the open item of iteration 1. The check
  must read plain figures before the short style becomes the default.

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
3. **Injected `state` argument in the schemas.** Eleven tools declare
   `state: Annotated[Dict, InjectedState] | None`. The tools get the state
   at run time (the dashboard cases pass), but with `| None` outside the
   `Annotated` the schema filter does not remove the argument. The model
   therefore sees a `state` parameter (about 70 characters for each tool,
   and the model can fill it). Fix for all profiles:
   `Annotated[Optional[Dict], InjectedState] = None`. Check that the tools
   still get the state.
4. **Skills list.** The skills list is now the largest generated part
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
6. **Review of the rewrite (2026-11-16).** The default prompt and the
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
