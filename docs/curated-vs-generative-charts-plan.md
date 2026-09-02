# Curated charts in the agent — design notes

*Status: proposal. Scope: backend (`wri/project-zeno`). Related:
`nrt-monitoring-section-plan.md`, `insight-chart-colors-plan.md`,
`AGENT_ARCHITECTURE.md`.*

## 1. The problem

The product has two ways to make a chart from pulled data:

| Path | Charts from | Reachable from |
|---|---|---|
| **Curated** (also "default" or "deterministic") | A hand-written generator per dataset | `POST /api/analyze`, the NRT section builder |
| **Generative** | An LLM code executor over the pulled rows | The agent, through `generate_insights` |

The agent can only use the generative path. It pays for a code-execution
round trip even when the user asked the dataset's standard question, for
which a curated chart already exists.

This document defines when the agent must use each path, and what to build to
give it the choice.

## 2. Where the two paths sit today

| Concern | Where |
|---|---|
| Generator base class and helpers | `src/api/services/charts/base.py` |
| The generator list | `src/api/services/charts/registry.py` (`DETERMINISTIC_GENERATORS`) |
| Pull + generator match + localisation | `src/api/services/analyze.py` (`AnalyzeService`) |
| REST entry point | `src/api/routers/analyze.py` |
| Recipe entry point | `src/api/services/nrt_monitoring.py` |
| Generative path | `src/agent/subagents/analyst/tool.py` (`Analyst`) |
| Narrative stage | `src/agent/subagents/analyst/text_generator.py` |
| Shared persistence | `src/api/repositories/insight_writer.py` |

Twelve generators cover the twelve catalog datasets, so every dataset has a
curated chart. Three differences decide the criteria.

**A curated pull drops the context layer and the parameters.**
`AnalyzeService.analyze()` pulls with `dataset={"dataset_id": dataset_id}`.
`AnalyticsHandler` reads `context_layer` and `parameters` off that same dict.
Neither reaches the pull. A curated Tree cover loss chart therefore shows all
tree cover, also when the user asked for primary forest. This is a
wrong-answer risk, not a limitation of style.

**A generator is keyed on the dataset, not on the question.**
`ChartGenerator.can_handle()` compares `dataset_id` only. Integrated alerts
has one curated chart, a monthly line by confidence tier. Its
`code_instructions` define a second correct view, a pie of the totals per
tier. A generator cannot give that second view.

**The curated path makes charts and no words.** It produces no
`primary_insight` and no `follow_up_suggestions`. The NRT builder works
around this with a separate section summary (`src/api/services/nrt_summary.py`).
A chat insight needs the narrative.

## 3. The criteria

Do not make this one model judgement. Split it into a gate in code and a
choice in the prompt.

### Layer 1 — the gate (code; the model cannot override it)

Curated is **ineligible** if any condition is true:

| Condition | Why |
|---|---|
| No generator for the `dataset_id` | `can_handle()` finds no match |
| `dataset.context_layer` is set | The curated pull drops it, so the chart answers a different question |
| `dataset.parameters` differ from the generator's assumption (`canopy_cover` other than 30) | Same reason |
| More than one entry in `state["statistics"]` | A generator reads the rows of one dataset; a comparison across datasets or periods is generative by nature |
| `change_over_time_query` is true | The curated path pulls a snapshot (`change_over_time_query=False`) |
| The generator returns no charts, or all rows are zero | There is nothing to show |

Generator coverage is already complete, so the context layer, the parameters
and the count of pulls do the real work here.

### Layer 2 — the choice (the model, when the gate passes)

Use **curated** for the canonical question about a dataset:

- "show me tree cover loss in Para", "what is happening in this area"
- a first look at one area and one dataset
- a dashboard or section build
- a repeated or scheduled run, where results must stay comparable

Use **generative** when the request names a view the curated chart does not
have:

- a specific slice, a ranking, or a top-N
- a comparison between periods, areas, or classes
- a different aggregation ("monthly, not yearly")
- a chart type the generator does not emit ("as a pie", "the split by confidence")
- a refinement of an earlier insight ("now drop the low-confidence tier")

Do **not** use cost or latency as a criterion. That makes correctness depend
on the budget. Use them only to break a tie: if both paths answer the
question, take curated. Curated is cheaper, repeatable, and its titles are
message keys, which `t()` resolves per language.

### The rule

```
1. the gate fails                       -> generative
2. the query names a cut or a transform -> generative
3. the user refines an earlier insight  -> generative
4. all other requests                   -> curated
5. curated produced nothing usable      -> generative, one time
```

## 4. Decisions

**D1 — One tool, one argument.** Add `mode` to `generate_insights`:
`generate_insights(query, mode="default"|"custom")`. A second tool would copy
the preconditions and the "always run insights after a pull" rule into both
`analyze.md` and `pull-data.md`, and would add another entry to a large tool
list. A `mode` argument is as visible in a trace as a tool name.

**D2 — The gate can refuse the mode.** `Analyst.analyze()` applies section 3.1
and falls back to the generative path when curated is ineligible. A model
mistake must not produce a chart that misrepresents the request.

**D3 — Three rungs, not two.** `update_insight_display` already restyles an
existing insight without new data: it renames charts, changes a chart type,
and re-maps a chart to columns it already has. The ladder is therefore
**curated -> restyle -> generative**, and only the last rung costs a
code-execution round trip. A user who asks for a different chart type of the
same data gets rung two.

**D4 — Reuse the pulled data.** The agent must not call `AnalyzeService`,
because that service pulls its own data and `pull_data` has already run. The
agent path reads `source_url` from `state["statistics"]` and fetches the rows
with `fetch_statistics_from_url`, as `Analyst` does today.

## 5. What to build

- **A narrative for curated charts.** Reuse `InsightTextGenerator`. It is
  already decoupled from how the charts were built. Pass
  `executor_context=""`; the grounding is the chart rows plus the dataset
  `cautions` and `presentation_instructions`. A curated insight in chat then
  costs one `SMALL_MODEL` call, not a Gemini round trip.
- **A shared generator step.** Move the generator match and
  `AnalyzeService._localise` into a function both callers use.
  `_localise` is a private static method today, and the localisation must not
  fork.
- **Provenance on the insight.** `InsightOrm` records nothing about which
  path made the charts. Add a field. Without it nobody can measure whether
  the curated choice was correct, and the frontend cannot mark a chart as the
  canonical one. Empty `codeact_types` and `codeact_contents` already mean
  "deterministic charts", so persistence needs no other change.
- **Skill updates.** Step 5 of `analyze.md` states "always run this to
  produce one chart insight". It needs the mode rule of section 3.2 and the
  escalation of D3.

## 6. Tests

| File | Covers |
|---|---|
| `tests/unit/api/services/` (new) | The gate: one test per condition in section 3.1 |
| `tests/unit/agent/subagents/test_analyst_modes.py` (new) | `mode="default"` uses the generator; an ineligible request falls back; the narrative stage runs on curated charts |
| `tests/unit/api/services/test_analyze_service.py` | The shared generator step keeps the REST behaviour |
| `tests/agent` (targeted file) | The model picks the mode for a canonical question and for a specific cut |

## 7. Open points

- **Title form.** Curated titles are message keys that `t()` resolves.
  Generative titles are model-written text. Both reach the database today
  through `/api/analyze`, so this is not new. The text generator on the
  curated path receives titles that are already resolved.
- **A second curated view per dataset.** Integrated alerts shows that one
  generator per dataset is too few. A generator that returns a named set of
  views, from which the caller picks, would remove the most common reason to
  escalate. It is out of scope here.
- **Statistics provenance.** `/api/analyze` writes no `StatisticsOrm` row, so
  its insights carry no dataset or AOI link. The agent path does write one,
  so a curated insight from chat is findable and a curated insight from REST
  is not. The gap is described in `nrt-monitoring-section-plan.md`.
- **Measurement.** With the provenance field in place, count how often the
  agent picks curated and how often the user then asks for a change. That
  ratio says whether section 3.2 is drawn in the right place.
