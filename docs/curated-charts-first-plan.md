# Curated charts first plan

Status: implemented behind the `curated-charts` profile (PZB-1681). It
builds on the view registry in `src/api/services/charts/views.py`.

## Goal

In the default agent, `generate_insights` shows a curated chart when a
curated chart can answer the request. The code executor (CodeAct) runs only
when no curated chart can answer it. The agent can offer a custom chart as
a follow-up.

Two rules have priority over the cost:

1. The agent must not give a wrong answer. A chart that does not answer the
   question must not be presented as the answer.
2. When the decision is not clear, the agent shows the curated chart first.

## Evidence

Source: the curated chart demand analysis of 16 Nov 2026 (external users,
4 Sep to 15 Nov 2026), made for the PRD `PRDs/curated-charts-first.md`.
The PRD is not in this repository and was not read for this plan.

| Group | Share of CodeAct charts |
|---|---|
| A generator exists, one area | 77.2% |
| A generator exists, several areas | 6.7% |
| New: area comparison | 5.3% |
| New: sub-region ranking | 4.6% |
| A generator exists, fix first | 2.5% |
| New: alerts by confidence | 0.8% |
| Curated today (LGMS) | 0.7% |
| Stays with CodeAct | 2.3% |

- Tree cover loss by year is 47% of all charts.
- CodeAct has a median of 16.2 s in a chart turn of 34.2 s. A curated chart
  takes 0.1 s.

This plan assumes that a generated chart is expensive. It does not measure
the cost of CodeAct.

## What exists

- 12 generators and 20 views (`src/api/services/charts/`). One shared
  function, `build_curated_charts`, builds and localises the charts.
- `insight_charts.view_id` and `view_revision` (this branch). A generated
  chart has null in both. This is the source flag.
- The curated path in the agent, `Analyst._analyze_curated_only`
  (`src/agent/subagents/analyst/tool.py`). It is for LGMS only, and it
  writes no interpretation.
- Facts in code (`src/api/services/charts/facts.py`): `total`, `peak`,
  `top_share`, for `area_ha` only.
- `format_chart_data` (`inspect_view_context.py`) puts the rows of a chart
  in a tool message, with a size limit.
- `update_insight_display` is in the default profile. A change of chart
  type does not need CodeAct.

## What makes a curated chart wrong

These findings come from the code. Each one becomes a gate or a fix.

| Risk | Cause | Answer in this plan |
|---|---|---|
| Several areas show as one series | Most generators plot the raw rows. A pull of 3 areas gives 3 rows for each year | Gate: a `one_area` view needs exactly one area in the pull |
| The title hides a filter | The title is "Annual Tree Cover Loss" also for a pull in primary forest or at a 10% canopy threshold | Fix: the title or subtitle states the context layer and the threshold |
| A model computes a total | The curated path has no printed totals from code | Fix: facts for each enabled view, in the tool message |
| The chart does not answer the question | A generator is keyed on the dataset, not on the question | The decision rule, and the answer rule: say what the chart shows and offer a custom chart |
| The chart covers a different period than the question | The pull was for the full range | The `analyze` skill sends the period of the user to `pull_data` |
| The request needs two datasets | The curated path reads the latest pull only | Decision rule: custom |
| Wrong colours | Curated charts do not use `resolve_chart_colors`. Land cover and natural lands have no `color_map` | Fix: each enabled generator sets `color_map` from `PALETTES` |
| sLUC sums the years | `SlucEmissionFactorsChartGenerator` adds all years of the range | Fix in phase 2. sLUC is not enabled before that |

A context layer and a canopy threshold are not a reason to refuse a curated
chart. They are filters in the pull request
(`AnalyticsHandler._build_payload`), so the rows have the same shape. The
September plan refused them because `/api/analyze` did not send them. The
agent uses its own pull, which has them.

## Design

### 1. One tool, one new argument

`generate_insights(query, chart="standard" | "custom")`. The default is
`standard`.

The tool description gives the rule to the orchestrator:

- Use `standard` for a first analysis of an area and a dataset, and when
  you are not sure.
- Use `custom` only when the user names something that the standard chart
  does not have: a ranking or a comparison of areas, a different time step,
  a calculation across two datasets, a derived metric, or a change that
  `update_insight_display` cannot make.

The cards of the views are not in the system prompt. The tool result names
the standard chart that was shown.

### 2. The gate in code

The gate runs for `chart="standard"` on the latest pull. The model cannot
change its result.

A pull passes when:

- the dataset has a view with `agent_enabled` (new field on `ChartView`,
  default false, so each view is released by itself);
- the number of areas in the rows agrees with the `shape` of the view;
- the generator returns a chart with rows.

When the gate fails, the tool runs CodeAct as it does today. It does not
refuse. No request gets a worse result than today.

LGMS keeps its `curated_only` path. It never runs CodeAct.

### 3. No generated description; facts in the tool message

Agreed on 2026-11-16: a curated chart gets no generated description. The
chart is curated, and the interpretation is in the chat, where the user
knows that the assistant wrote it. No model runs in `generate_insights`
for a curated chart.

1. Build the charts with `build_curated_charts`.
2. Compute the facts of each view in code: total, peak, largest class and
   its share. `facts.py` gets support for units other than `area_ha` and
   for stacked series.
3. Persist the insight. `primary_insight` is a fixed i18n caption: the
   dataset, the area, the period, the context layer and the threshold. It
   has no figure and no judgement. `follow_up_suggestions` is empty.
4. Return a tool message with the data that the orchestrator needs to
   answer (see section 4).

The orchestrator writes the answer in the chat from the tool message. It
copies the figures. This is how the LGMS path works, without the
instruction that withholds the data.

The state has the same fields as today, so the gold harness needs no
change.

### 4. The data in the tool message

The gold set (`evals/gold`, cases in `evals/gold/cases/v2`, 96 active cases) shows
what a standard question needs. The table gives the question kinds for one
area and the data that answers each of them.

| Question kind | Gold examples | Data in the tool message |
|---|---|---|
| The value of one year or one class | Loss in Colombia in 2025; grassland in 2019; hectares of cultivated grassland; tree cover in 2000 | All rows of the chart, with full precision |
| The total of the period | Primary forest loss 2001 to 2024; loss in intact forest 2020 to 2024 | Fact: the total of each measure for the pulled period |
| The largest or the smallest year | The year with the most loss; the year with the lowest emissions; the peak grassland extent | Facts: the maximum and the minimum of each measure, with the year |
| A comparison of two years or two periods | Grassland 2017 against 2022; gain 2000-2010 against 2010-2020 | The rows. Fact: the change from the first to the last year |
| The largest class, its rank, its share | The largest driver; the second largest natural class; the largest transition; logging against wildfire | The rows, largest first, with the rank and the share of each class |
| Source or sink | The net flux of the Canary Islands | The three rows of the flux chart, with the sign |
| Alerts in a period | Alert area in natural lands, June 2024 to June 2025; high and highest confidence only; August against September | Facts: the total, the total and the share of each confidence level, the total of high and highest, and the totals for each month. The daily rows only when they are few |
| What the figures apply to | The gold `text` checks: state the period, the 2020 baseline, the first year of primary forest | A header: the area, the dataset, the period that the rows cover, the context layer, the canopy threshold, a date range that was changed. Then the cautions of the dataset |

Rules for the message:

- The rows of a chart for one area are small (25 years, 8 classes), so
  they go in the message complete. `format_chart_data` cuts a value to 16
  characters and changes a large table into statistics. The curated path
  needs its own format that keeps each value, and a summary for each view
  that can be large (alerts by day).
- Each figure has its unit. A fact is a structured value and a sentence.
- The message ends with the instruction for the answer (section 5).

The chart must cover the period that the user asks for. The gold check
`charts_answer` looks for the expected figure in the chart rows: as a
value, a column total, a column maximum, a row total, or a share of a
column. A total for 2020 to 2024 is in the chart only if the pull was for
2020 to 2024. The `analyze` skill must tell the orchestrator to send the
period of the user to `pull_data`. The analytics API cuts the rows to
that period, and the total fact is then the answer.

Known limits against gold, with the views of phase 1:

- A question about a part of the confidence levels ("high and highest
  only", the share of the highest level) gets the correct figure in the
  chat from the facts, but the daily chart does not contain the figure as
  one value or one total. `charts_answer` fails. These requests need the
  view "alerts totals by confidence" (phase 2b) or a custom chart.
- About 26 of the active cases compare or rank areas. They go to CodeAct
  until phase 2.
- One case checks the chart type (`bar`), and the LGMS cases check the
  LGMS chart types. No curated view of phase 1 conflicts with them.

### 5. The answer, and the offer of a custom chart

The tool never starts CodeAct by itself after a curated chart, and the
orchestrator does not start it without a request of the user.

The tool message ends with this instruction:

- Answer the question from the figures above. Copy the figures; do not
  calculate new ones.
- If the figures above do not answer the question, do not give an answer
  that they do not support. Tell the user what the chart shows, and tell
  them that they can ask for more detail or for a custom chart.
- Call `generate_insights` with `chart="custom"` only when the user asks
  for something that the standard chart does not have.

An example of the reply for a question that the chart does not answer:
"Here is the tree cover loss for Pará for each year. If you want this
split in a different way, or a different chart, tell me and I will
prepare it." The orchestrator writes the words; the tool gives the rule.

When the chart answers the question, the orchestrator gives the answer.
It can add the offer in one short sentence, and it does not repeat the
offer in each turn. The tool makes no follow-up buttons for a curated
chart.

A request that names a custom cut in the first message ("rank the
districts by loss") still goes to `custom` directly (section 1). That is
a request of the user.

The restyle step stays before CodeAct: a request for a line in place of
bars, or a table, goes to `update_insight_display`. A chart that this tool
changes loses its view id, as designed in phase 1.

### 6. Views for more than one question (phase 2)

Phase 1 has one default set of views for each dataset, so the model
selects nothing. Phase 2 adds views that share a dataset: alerts totals by
confidence, area comparison, sub-region ranking. Then `generate_insights`
gets an optional `view` argument. The options are the enabled views for
the dataset and the number of areas of the pull. The tool result lists the
cards when the view is unknown. This is section 3 of the low AI mode plan,
with CodeAct kept as the fallback.

## Evals

1. **Routing set.** The demand analysis has labelled data: the prompt, the
   dataset, the number of areas and the chart form that CodeAct drew. Make
   a set of about 300 rows with the expected route (`standard`, `custom`,
   or a view id). Remove email addresses and long numbers. The prompts are
   internal to WRI, so the set stays out of the public repository.
   Measure two error kinds separately:
   - curated shown for a request that needed custom, and the orchestrator
     gave an answer that the tool message does not support (the
     wrong-answer kind);
   - custom run for a request that curated could answer (the cost kind).
2. **Gold.** Run gold on the profile with the flag before the default
   changes. Compare by question kind. The numeric cases need the figure in
   the final message and in the chart rows within 2%.
3. **Production.** With `view_id`, count the curated and the generated
   charts for each dataset. Count the turns where a custom chart follows a
   curated chart in the same thread. A high rate for one view shows that
   the view is not the chart that people want.

## Phases

Each phase is one or more PRs.

| Phase | Content | Done when |
|---|---|---|
| 0 | Commit and merge phase 1 of the low AI mode plan (view registry, `view_id`, migration `a6d2e9c4b713`). Build the routing set | The routing set exists |
| 1a | `chart` argument, the gate, facts for all units, the fixed caption, the tool message of section 4, the answer instruction, the period rule in the `analyze` skill, `agent_enabled`. Enable tree cover loss only, on a profile flag | Gold on the flag is not worse than the baseline. The routing set has no wrong-answer error for tree cover loss |
| 1b | Enable the other one-area views in order of demand: loss by driver, grassland, land cover composition, alerts by day, loss from fires, natural lands, forest flux, tree cover gain, tree cover extent. Set the colours for each | 77% of the chart demand can go to a curated chart |
| 1c | Make the flag the default. Update the `analyze` skill, step 5 | The default profile shows curated charts |
| 2a | Several areas for the charts that exist: 5 areas or fewer as a stack by area, more than 5 as one total | A pull of several areas does not go to CodeAct for a total |
| 2b | New views: compare areas (2 to 5), rank sub-regions (top N), alerts totals by confidence. The `view` argument | The three new chart families are curated |
| 2c | Fixes: sLUC shows one year. Land cover transitions are checked from chat | 97.7% of the chart demand can go to a curated chart |

Phase 1a is the large one. Phases 1b and 2 are small steps for each view.

## Relation to the other plans

- **Low AI mode.** This plan uses its phase 1, and it does the multi-area
  views and the `view` argument of its phases 2 and 3 in the default
  profile. The `lite` profile, the small orchestrator model and the fixed
  pipeline stay in that plan. The largest cost of a turn is the
  orchestrator loop, and this plan does not change it.
- **Zap mode.** Its `view` question (phase 6) uses the same registry and
  the same `agent_enabled` views.
- **The September plans.** The gate and the rule "the model cannot change
  the gate" come from them. The `curated_only` flag for LGMS stays as it
  is.

## Risks

- **The orchestrator is the only check.** It can present a standard chart
  as the answer to a question that the chart does not answer. The routing
  set measures this before each view is enabled.
- **Gold cases that got a custom chart.** A single-area gold case whose
  figure is not in the curated chart now ends with an offer, not with the
  answer. Gold on the flag shows which cases these are. Each one is a
  missing fact, a missing view, or a known limit.
- **Figures in the chat.** The orchestrator copies the figures from the
  facts, and it can change one. A fact for each common question keeps it
  from doing arithmetic on the rows.
- **No description where one is shown.** Dashboards, `search_insights` and
  the insight card show `primary_insight`. They get the caption only.
  Check each place before phase 1a.
- **Presentation changes.** CodeAct drew a line for grassland and a
  monthly line for alerts. The generators draw bars and daily bars. Users
  see a different chart for the same request. These are open questions of
  the PRD.
- **Two charts for tree cover loss.** The generator gives the loss and the
  emissions. CodeAct usually drew one. The emissions chart is empty for
  natural forest below a 30% threshold and must be left out then.
- **Dataset rules.** Each catalog entry has `code_instructions` that
  CodeAct follows, for example which rows to exclude. Check each generator
  against the rules of its dataset before the view is enabled.
- **Large pulls.** A ranking of all sub-regions of a country is a large
  pull. Check the limits of the analytics API for phase 2b.

## Decisions

Open, for agreement before phase 1a:

1. **Who selects the route.** Proposed: the orchestrator selects
   `standard` or `custom`, and the gate in code can override `standard`.
2. **The caption.** Proposed: a fixed caption with the dataset, the area,
   the period and the filters. The alternative is no text at all, but
   then nothing on the chart states the context layer or the threshold.
   Agreed on 2026-11-16: the fixed caption.
3. **A standard chart that did not answer.** Agreed on 2026-11-16: no
   automatic custom chart. The agent tells the user what the chart shows
   and offers more detail or a custom chart.
4. **Rollout.** Proposed: one view at a time with `agent_enabled`, on a
   profile flag until gold passes, with tree cover loss first.
5. **Chart forms.** Grassland as bars or as a line, alerts as daily bars
   or as a monthly line, natural lands with the non-natural classes as one
   slice. These follow the PRD.
