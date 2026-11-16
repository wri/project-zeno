# Low AI mode plan

Status: phases 0 and 1 are done. Phases 2 to 4 are a proposal.

## Goal

Give the public launch an agent that costs much less than the full agent
and that works with small models. The agent selects a curated chart ("view")
from a library. It does not write chart code. The gold evals
(`wri/gnw-gold-evals`) must continue to pass where a curated view can
answer the question.

The feel of the mode can be different from the full agent. The quality of
the selection (area, dataset, period, view) is the priority.

## Not in this plan

- Changes to zap mode (`POST /api/zap`). Zap stays a separate, text-free
  path. Phase 4 uses its decision method again.
- Changes to the full agent, other than the token savings in "Savings for
  all profiles".
- New datasets.

## Baseline

Measured in phase 0. The sample is 445 turns from two local gold runs on
2026-10-12 (`default` profile, 104 cases, 2 trials), read from the local
Langfuse store. The token counts are measured. The costs are computed from
the token counts with the rates in
`src/api/services/langfuse/model_prices.py`.

One simple question that makes an insight (294 threads with one turn),
median values:

| Component | Model | Input tokens | Calls | Cost (USD) | Share of cost |
|---|---|---|---|---|---|
| Whole turn | | 62,046 | 9 | 0.095 | 100% |
| Orchestrator | `MODEL` (Pro) | 53,614 | 6 | 0.090 | 95% |
| Dataset selection (`pick_dataset`) | `SMALL_MODEL` | 5,760 | 1 | 0.002 | 3% |
| Insight text | `SMALL_MODEL` | 2,014 | 1 | 0.0015 | 2% |
| Place extraction (`pick_aoi`) | `SMALL_MODEL` | 1,441 | 1 | 0.0008 | 1% |
| Code executor | `CODING_MODEL` | not traced | | | |

- One orchestrator round trip sends a median of 9,294 input tokens. The
  system prompt and the schemas of 21 tools are about 8.8k of them
  (estimate from the prompt sizes). The implicit cache of Gemini serves
  about 27% of the orchestrator input.
- The thread history is never trimmed.
- The code executor is not in the sample. The runs are older than the
  change that traces it (#814). To measure it, do a gold run on a build
  with #814, or ingest recent traces from staging or production.
- The gold set has no thread with more than two turns, so long threads are
  not measured.
- A turn that uses `search_blogs` sends about 280k input tokens to its
  nested agent (7 turns in the sample).

## What the gold evals need

The harness reads `GET /api/threads/{id}/state`. It does not read the
stream. A low AI mode must write the same state as the full agent:

- `aoi_selection`, `dataset`, `statistics`, `charts_data`, `nudge`.
- `pull_data` tool calls in `messages`, because the date check reads the
  tool-call arguments.
- A final message that gives the answer: the number, the place, the year,
  or true/false. The checks do not read the insight text for this.

For the 35 numeric cases, the expected figure must also be in the chart
rows within 2%: as a value, a column total or maximum, a row total, or a
percentage share. The chart type is a gating check in one case only.

The 115 active cases by question kind (counts are approximate):

| Kind | Cases | What the mode needs |
|---|---|---|
| One area, one dataset, direct value | 42 | The views of today, and the figure in the final message |
| Derived in one area (peak year, share, trend, rank) | 19 | Facts computed in code |
| Comparison of named areas | 12 | A multi-area view |
| Ranking of subregions or countries | 14 | A multi-area view |
| Metadata, dashboards, imagery, multi-turn | 21 | Paths that exist, with no chart generation |
| Refuse, clarify, suggest | 7 | A reliable "no view fits" result |

## Design

### 1. Views

A view is one named curated chart with its facts. Today a generator is
keyed on a dataset and returns one or two charts
(`src/api/services/charts/`). The plan keeps the generators and adds a
view registry above them.

A view has:

- `id`: a permanent string, for example `tcl.annual_loss`. An id is never
  renamed or used again for a different chart.
- `revision`: an integer. Increase it when the output of the view changes.
- `dataset_ids`: the datasets that the view can show.
- `card`: one or two sentences for the selector. It gives the question
  that the view answers.
- `shape`: `one_area` or `many_areas`, and the context layers and
  parameters that the view accepts.
- `build(rows, period) -> InsightChart`.
- `facts`: the fact kinds that the view can state (see "Facts").

Phase 1 built a part of this. A view in `views.py` has `id`, `revision`,
one `dataset_id`, `card`, `shape` and `from_pull` (false for a view that
only an analysis template can build). The generator of the dataset builds
the chart, and the title key of the chart is `charts.` plus the view id.
`build`, `facts`, more than one dataset, and the accepted context layers
and parameters come with the multi-area views (phase 2) and the selector
(phase 3), which are their first users.

The 12 generators that exist become the first views. Each chart of a
generator is one view. `build_curated_charts` keeps its `titles` filter,
and a title key maps to a view id, so the analysis templates do not change.

New views, in priority order:

1. Generic multi-area views, for each dataset with a total metric:
   - `compare_areas`: one bar for each named area.
   - `rank_subregions`: the top N subregions, largest first.
   - `series_by_area`: one line for each area over time.
2. A second view for datasets with more than one natural question. For
   example, integrated alerts by confidence as a pie, tree cover loss as a
   cumulative line, land cover as composition and as transitions.
3. Views that the picking eval shows are missing (see "Evals").

The multi-area views need a check of the generators first. A generator can
sum several areas with no warning (LGMS does this). A `one_area` view must
refuse a pull with more than one area.

### 2. Facts

A fact is a figure computed in code from the chart rows, with a sentence
from an i18n template. `src/api/services/charts/facts.py` does
this for templates: `total`, `top`, `top_share`. It reads `area_ha` only.

The plan moves the fact code to a module that the views and the templates
share, and extends it:

- Any numeric column with a unit, not only `area_ha`.
- New kinds: `min`, `value_at` (one year or one category), `rank` (the
  n-th largest), `share_of` (one category), `trend` (larger or smaller at
  the end than at the start), `argmax_area` and `sum_areas` for multi-area
  views.

Each fact gives a structured value and a sentence. The final message is
made from the facts. No model computes a figure.

### 3. View selection in `generate_insights`

`generate_insights` gets a `view` argument. Its options come from the view
registry, filtered by the dataset and the number of areas of the latest
pull. The tool result gives the view cards when the model sends no view or
an unknown view, so the list is not in the system prompt.

With a view, the tool does the same steps as `_analyze_curated_only`
(`src/agent/subagents/analyst/tool.py`): load the rows, build the chart,
compute the facts, persist the insight, return the tool message. No code
executor runs and no text generator runs.

The tool message contains the fact sentences. The model copies the fact
that answers the question into the final message, in the language of the
user. This is the only free text in the turn.

When no view fits, the model selects `none`. The tool then returns an
instruction to tell the user what the mode can show, as a nudge with the
nearest views. The mode does not fall back to the code executor (see
"Decisions").

### 4. The `lite` profile

A new profile in `src/agent/agent_config.py`, selected with `ff=lite`:

- Tools: `pick_aoi`, `pick_dataset`, `pull_data`, `generate_insights`
  (view mode only), `send_nudge`. Dashboard, imagery and blog tools are a
  later decision.
- No skills and no `read_skill`. The workflow is four fixed steps, and the
  system prompt states it in a few lines.
- `pick_dataset` returns a short tool message: the selection and the date
  range. Cautions and presentation rules stay out of the history. The fact
  sentences carry the caveats that a view needs.
- `MODEL` for the profile is a small model. `MODEL` resolves at import
  time today (`src/agent/llms.py`), so the profile needs a model setting
  of its own.

Target for one simple question: 5 round trips of about 2.5k fixed tokens,
plus two small subagent calls. That is 15k to 20k input tokens on a small
model, with no `MODEL` or `CODING_MODEL` call.

The gold harness runs against this profile with `--ff lite` and no change.

### 5. Storage and provenance

A view chart is stored as today: `persist_insight` writes `insights` and
`insight_charts` rows with the resolved title, the chart type and the data
rows. A stored chart is a snapshot. A change to a view does not change
stored charts, so they need no version to render.

`insight_charts` has two nullable columns, `view_id` and `view_revision`
(done in phase 1). They are on the chart, not on the insight, because one
insight can hold the charts of several views. A generated chart has null
in both. A chart that `update_insight_display` changes loses its view,
because it is no longer the output of the view. The columns let us:

- Count selected and generated charts.
- Find the charts of a view that had an error.
- Explain a different result when a chart is built again.

The frontend does not get the two fields. It must keep each chart type and
field layout that a stored chart uses.

## Evals

Two measures. The gold run is the gate; the picking eval is the guide.

1. **Gold with `--ff lite`.** Compare with the `default` baseline by
   question kind, not as one number. The harness must not diff runs of
   different profiles, so the `lite` profile gets its own baseline. Expect
   failures in the cases that need custom aggregation; record them as
   known limits.
2. **Picking eval.** A new labelled set: prompt, dataset, area count, and
   the correct view id or `none`. It is deterministic and cheap, as the
   dataset-picker tests in PR #841 are. Start from the gold prompts and add
   decline cases; only six labelled decline cases exist today, which is
   too few.

## Phases

Each phase is one or more PRs and can ship alone.

| Phase | Content | Done when |
|---|---|---|
| 0 (done) | Measure. Take per-turn tokens and cost by component from the Langfuse traces for the `default` profile. | The baseline table in this document has measured numbers. The code executor is not measured. |
| 1 (done) | View registry over the generators (`src/api/services/charts/views.py`). Shared fact module (`src/api/services/charts/facts.py`). `view_id` and `view_revision` columns on `insight_charts`. `/api/analyze`, the templates and the curated-only agent path get the view from `build_curated_charts`. | No change in behaviour; stored charts of curated paths carry a view id. |
| 2 | Multi-area views and second views. Picking eval set. | Each of the six question kinds that needs a chart has a view; the eval set is in the repository. |
| 3 | `view` argument in `generate_insights`. `lite` profile. Short `pick_dataset` message. | Gold runs with `--ff lite`; a `lite` baseline is committed; token numbers are measured. |
| 4 | Only if phase 3 costs too much or small models orchestrate poorly: a fixed pipeline behind `/api/chat`. Code calls the tools in order; the decisions are choice questions as in zap; one text call writes the final message. Target 3k to 6k tokens for one turn. | Same gold result as phase 3 at a lower cost. |

## Savings for all profiles

These are independent of the mode and can go in at any time:

- `pick_dataset` puts cautions (about 2k characters) and presentation
  rules (about 2.4k) in its tool message. Each later round trip and turn
  sends them again. `generate_insights` repeats the cautions.
- The dataset selector prompt contains the selection hints and the
  selection rules two times.
- The history has no trimming. The code executor gets each earlier pull of
  the thread again.
- The session block is a system message before the history and changes
  during a turn. Move it after the history so the prompt prefix can cache.

## Risks

- **Small models and the tool loop.** The open-model tests measured
  orchestration with the full prompt. A short prompt with four tools can
  be easier, but this is not measured. Phase 4 is the answer if it fails.
- **Declines.** Decision models and small models decline poorly. A wrong
  view with a confident figure is worse than a refusal. The picking eval
  must have decline cases before phase 3 ships.
- **Final message.** The model can change a figure when it copies it. The
  info-only `answer_traceability` check in gold finds this; consider a
  code check that the final message contains a fact value.
- **Multi-area pulls.** Rankings of all countries or all subregions are
  large pulls. Check the limits of the analytics API for each dataset.
- **Colours.** Curated charts do not go through `resolve_chart_colors`
  (`src/api/services/charts/curated.py`). Each new view must set its own
  `color_map` until that is solved.

## Decisions

Open, for agreement before phase 3:

1. **No view fits.** Proposed: decline with a nudge, with no fallback to
   the code executor. A fallback under a quota is possible later.
2. **Final message.** Proposed: the model writes one or two sentences from
   the fact sentences. The alternative is template text only, which costs
   less but is weak for the multilingual and caveat cases in gold.
3. **Scope of `lite`.** Proposed: analysis only in the first version.
   Dashboards (7 gold cases) and imagery (1 case) follow through analysis
   templates.
4. **Decision model for phase 4.** jev or a small chat model with
   structured output. Decide after phase 3 results.
