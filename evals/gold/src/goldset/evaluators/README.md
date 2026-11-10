# Evaluators: check reference

The triage reference for every check the GOLD harness emits: what it measures, what `1.0`, `0.0` and `null` mean, where its evidence lands in the run record, and how to triage a failure. Terms are defined in the [README glossary](../../../README.md#glossary). If this file and the code disagree, the code is right: fix this file in the same PR.

This file quotes no pass rates or stability figures, because they change with every case and agent edit. For current ones, run `uv run python tools/flakiness.py results/runs/<run_id>.json --per-case` on the latest 3-trial run in `results/runs/`.

An evaluator is a function in this directory. It receives the agent's final state (the `GET /api/threads/{id}/state` payload), the case's expected values as an `ExpectedData` (`adapter.py` adds the `expected_` prefix to each key of the case's `expected:` block), the query and, for the dashboard checks, the dashboard fetched from `GET /api/dashboards/{id}`. It returns `<check>_score` fields plus `actual_*` diagnostics and changes nothing. The runner calls every evaluator in `registry.EVALUATORS` and merges the results; each `<check>_score` becomes the ledger check `<check>`. The legacy `overall_score` is not a check.

### Scores: `1.0`, `0.0` and `null`

Every check is `1.0` (pass), `0.0` (fail) or `null` (not evaluated). Each entry below says when an absence scores `null` (the check does not apply) and when it scores `0.0` (something that should be there is missing). That choice matters most: an absence that should fail but scores `null` raises the pass rate without anyone noticing. So an expected AOI that never resolved scores `0.0`, not `null`.

Most checks are opt-in: they run only when the case sets a particular expected value. The exceptions run on any row with the relevant output: `chart_integrity`, `chart_well_formed`, `answer_traceability`, `dashboard_widgets_valid`, and `dashboard_created` (an unsolicited dashboard fails).

The run report's reconciliation line compares the checks a case's expected values imply (`buckets.implied_checks`) with the checks that evaluated. Checks that may legitimately abstain (`charts_answer`, `web_fallback`, `pull_source_match`, the dashboard sub-checks, `date_coverage`) are never implied, so every miss on that line is a real hole.

### Verdicts: gating, info-only and error

`buckets.row_verdict` gives each row one verdict:

- `error`: the API call or a judge call failed, or a ground-truth case could not be graded (see [`ground_truth_match`](#ground_truth_match)). Never counted as a fail.
- `uncovered`: no gating check evaluated. Never counted as a pass.
- `fail`: at least one gating check scored `0.0`.
- `pass`: otherwise.

A gating check can turn a row to `fail`. An info-only check is recorded and reported but never affects a verdict or the release gate (see [Info-only checks](#info-only-checks)). A judge outage never guesses a score: the check stays `null`, its name goes into the entry's `judge_errors`, and the row becomes `error`. The one exception is the info-only `ground_truth_answer`, which keeps its outages out of `judge_errors` (see its entry).

### Where the evidence lands

- `reasons.<check>`: any result field named `<check>_reason` or `<check>_score_reason`, first 500 characters, kept whatever the score. The chart check's field is spelt `chart_answer_score_reason` and stored as `reasons.charts_answer` (`ledger.REASON_ALIASES`).
- `actuals.<check>`: the `actual_*` diagnostics listed in `cli.ACTUALS_FOR_CHECK`, first 300 characters, recorded **only when the check scored `0.0`**. Several evaluators write an explanation into an `actual_*` field when they abstain; those rows score `null`, so the explanation never reaches the ledger. Each entry says where to look instead.
- In a multi-trial run, `checks` holds the majority verdict and `trials[].checks` each trial's scores, but `reasons`, `actuals` and `trace_url` come from the **last trial only**. A check whose majority is `0.0` can therefore have no `actuals` (the last trial passed) or a passing reason.
- `results/artifacts/<run_id>/<uid>.json.gz` (later trials add `_t2`, `_t3`; multi-turn turns use `<uid>_turn<N>`): the raw agent state, with the final answer, code-act output, tool calls, last statistics entry, charts, AOI selection, dataset, nudge and dashboard widgets. Artefacts are gitignored, so they exist only on the machine that ran the run. Evaluator diagnostics are not stored there; re-derive a missing reason from the state.

### Multi-turn cases

Per-turn checks are stored with a turn prefix (`t2.aoi_id_match`), and the verdict, bucket and diff code strips it (`buckets.base_check_name`), so every entry below applies per turn. Per-turn reasons are not in `reasons`: they sit in `turns_detail[<N-1>].reasons`. Actuals are flattened as `actuals["t<N>.<check>"]`.

### Numbers are compared in code

No LLM judge does arithmetic. The judge (by default `claude-haiku-4-5` at temperature 0, `models.HAIKU`; `--judge-backend openrouter-jev-decisions` swaps in TypeSafe JEV through OpenRouter Decisions) extracts or classifies, and code applies the 2% tolerance (`llm_judges.NUMERIC_TOLERANCE`) with one parser, `chart_numeric.parse_expected_number`, so an answer and its chart agree on what "within tolerance" means. `charts_answer` gates on the code comparison alone; `agent_answer` lets the judge overturn a code failure, because the parser cannot read every language's number format.

## Index

This is the canonical check-to-bucket map; other docs link here. Bucket tags come from `buckets.DEDICATED` and `buckets.SHARED`, and the info-only set from `buckets.INFO_ONLY`. The five buckets ask: **retrieval**, did the agent understand the question and fetch the data; **analysis**, are the numbers right; **explanation**, is the prose faithful to the data; **output**, are the charts and dashboards correct; **scope**, did it do the right amount of work. A shared check belongs to two buckets because its failure cannot be pinned on either, so bucket tables count dedicated and shared checks separately. A check with no bucket counts toward none.

"Kind" says whether an LLM judge contributes: deterministic (code only), judge, or mixed (judge and code together). `tools/flakiness.py` holds every check from an evaluator whose `EvaluatorSpec.kind` is `llm_judge` or `mixed` to the judged stability limit (standard deviation at most 0.10 over 3 trials) and the rest to the deterministic limit (0.04). "Runs when" names keys of the case's `expected:` block. `;` means "any of these" in `dataset_id`, `scope`, `nudge_type` and `chart_type`, but "all of these" in `aoi_ids`; `nudge_options`, `dashboard_widgets`, `class_values` and `suggested_datasets` use it as a list separator with rules of their own (see each entry). Which fields the active cases set is counted in [COVERAGE.md](../../../cases/v2/COVERAGE.md#expected-field-census-active-cases).

| Check | Bucket | Role | Kind | Evaluator | Runs when |
|---|---|---|---|---|---|
| [`aoi_id_match`](#aoi_id_match) | retrieval | gating | deterministic | `aoi_evaluator.evaluate_aoi_selection` | `aoi_ids` |
| [`dataset_id_match`](#dataset_id_match) | retrieval | gating | deterministic | `dataset_evaluator.evaluate_dataset_selection` | `dataset_id` |
| [`dataset_parameter_match`](#dataset_parameter_match) | retrieval | gating | deterministic | `dataset_evaluator.evaluate_dataset_selection` | `dataset_parameters` and `dataset_id` |
| [`context_layer_match`](#context_layer_match) | retrieval | gating | deterministic | `dataset_evaluator.evaluate_dataset_selection` | `context_layer` and `dataset_id` |
| [`date_extraction`](#date_extraction) | retrieval | gating | deterministic | `data_pull_evaluator.evaluate_date_extraction` | `start_date` and `end_date` |
| [`date_coverage`](#date_coverage) | none | info-only | deterministic | `data_pull_evaluator.evaluate_date_selection` | `start_date` and `end_date` |
| [`data_pull_exists`](#data_pull_exists) | retrieval | gating | deterministic | `data_pull_evaluator.evaluate_data_pull` | a pull is expected: `answer`, `ground_truth`, or `insight` in `dashboard_widgets`, unless `clarification` is `true` |
| [`answered_without_data`](#answered_without_data) | retrieval | gating | deterministic | `guards.evaluate_guards` | a pull is expected |
| [`pull_source_match`](#pull_source_match) | retrieval | gating | deterministic | `guards.evaluate_guards` | `dataset_id`, and a pull happened |
| [`state_delta`](#state_delta) | retrieval | gating | deterministic | `runner.multiturn.evaluate_deltas` | a turn's `deltas:` block (turn 2 onwards) |
| [`ground_truth_match`](#ground_truth_match) | retrieval | gating | deterministic | `groundtruth_checks.evaluate_ground_truth` | `ground_truth`, with values fetched at run start |
| [`chart_integrity`](#chart_integrity) | analysis | gating | deterministic | `analysis_checks.evaluate_chart_integrity` | any row with charts |
| [`class_value_match`](#class_value_match) | analysis | info-only | deterministic | `analysis_checks.evaluate_class_values` | `class_values` |
| [`charts_answer`](#charts_answer) | analysis and output (shared) | gating | mixed | `llm_judges.resolve_chart_verdict` | `answer`, and charts exist |
| [`charts_answer_judge`](#charts_answer_judge) | none | info-only | judge | `llm_judges.llm_judge_chart` | same rows as `charts_answer` |
| [`agent_answer`](#agent_answer) | analysis and explanation (shared) | gating | mixed | `llm_judges.resolve_answer_verdict` | `answer`, and a final message |
| [`ground_truth_answer`](#ground_truth_answer) | analysis and explanation (shared) | info-only | mixed | `groundtruth_checks.evaluate_ground_truth` | `ground_truth`, with values fetched at run start, and a final message |
| [`expected_text_match`](#expected_text_match) | explanation | gating | judge | `llm_judges.llm_judge_expected_text` | `text`, and a final message |
| [`web_fallback`](#web_fallback) | explanation | gating | deterministic | `guards.evaluate_guards` | a pull is expected, and a final message |
| [`answer_traceability`](#answer_traceability) | explanation | info-only | deterministic | `explanation_checks.evaluate_answer_traceability` | any row with charts and a final message |
| [`chart_produced`](#chart_produced) | output | gating | deterministic | `guards.evaluate_guards` | `answer`, unless `clarification` is `true` |
| [`chart_well_formed`](#chart_well_formed) | output | gating | deterministic | `output_checks.evaluate_chart_well_formed` | any row with charts |
| [`chart_type_match`](#chart_type_match) | output | gating | deterministic | `output_checks.evaluate_chart_type` | `chart_type` |
| [`dashboard_created`](#dashboard_created) | output and scope (shared) | gating | deterministic | `dashboard_evaluator.evaluate_dashboard_created` | `dashboard_created`, or any row where a dashboard was created |
| [`dashboard_aoi_match`](#dashboard_aoi_match) | output | gating | deterministic | `dashboard_evaluator.evaluate_dashboard_aoi` | `aoi_ids`, and a dashboard was fetched |
| [`dashboard_widgets_match`](#dashboard_widgets_match) | output | gating | deterministic | `dashboard_evaluator.evaluate_dashboard_widgets` | `dashboard_widgets`, and a dashboard was fetched |
| [`dashboard_widgets_valid`](#dashboard_widgets_valid) | output | gating | deterministic | `dashboard_evaluator.evaluate_dashboard_widgets` | a fetched dashboard with widgets, or `dashboard_widgets` with none delivered |
| [`clarification_requested`](#clarification_requested) | scope | gating | judge | `clarification_evaluator.evaluate_clarification` | `clarification` |
| [`nudge_match`](#nudge_match) | scope | gating | deterministic | `nudge_evaluator.evaluate_nudge` | `nudge_type` or `nudge_options` |
| [`scope_match`](#scope_match) | scope | gating | deterministic | `scope_checks.evaluate_scope` | `scope` |
| [`suggested_datasets_match`](#suggested_datasets_match) | scope | gating (legacy) | deterministic | `suggested_datasets_evaluator.evaluate_suggested_datasets` | `suggested_datasets` (legacy: the agent no longer writes this field) |

Two expected fields switch on no check of their own: `aoi_source` is read only by `dashboard_aoi_match`, and `dataset_name` by no check at all (it still counts toward the uid, like every expected value). Do not read either as coverage.

## `aoi_id_match`

Retrieval · gating · deterministic · `aoi_evaluator.evaluate_aoi_selection` · runs when: `aoi_ids` is set

**Measures.** Whether the agent resolved the place in the prompt to the expected area-of-interest ids: the set of `src_id`s in `agent_state["aoi_selection"]["aois"]` must equal the expected set. `;` in `aoi_ids` means "all of these", so an either-or AOI expectation cannot be written.

**Scores.** `1.0` when the two sets are equal after normalisation · `0.0` when they differ, or when no AOI was resolved at all · `null` when `aoi_ids` is not set.

**Evidence.** `reasons.aoi_id_match`: none · `actuals.aoi_id_match` (failing rows only): `actual_id`, the resolved ids as a list.

**Triage.**
- Normalisation follows the first resolved AOI's `source`. For `gadm` (the global administrative boundaries dataset), `utils.normalize_gadm_id` drops the trailing `_N` version suffix, maps `-` to `.` and lower-cases, so `BRA.25_1` becomes `bra.25` and `USA.5_1` equals `USA.5_2`. Other sources compare lower-cased strings.
- A multi-AOI result with mixed sources is normalised under the first AOI's rule.
- `aoi_source` is not checked here; only `dashboard_aoi_match` reads it.

## `dataset_id_match`

Retrieval · gating · deterministic · `dataset_evaluator.evaluate_dataset_selection` · runs when: `dataset_id` is set

**Measures.** Whether the agent selected the expected dataset: `agent_state["dataset"]["dataset_id"]` against the expected id. `;` separates acceptable alternatives (for example `8;10`) for cases where two datasets answer the question equally well; any one passes.

**Scores.** `1.0` when the selected id matches an alternative · `0.0` when it matches none, or when no dataset was selected · `null` when `dataset_id` is not set.

**Evidence.** `reasons.dataset_id_match`: none · `actuals.dataset_id_match` (failing rows only): `actual_dataset_id`.

**Triage.**
- `utils.normalize_value` turns `None`, the string `"None"` and whitespace into an empty value, so a state field holding `"None"` reads as no dataset selected.
- Cases must not name the dataset in the prompt (see [cases/README.md](../../../cases/README.md)), so this check measures the agent's routing. A row that flips between trials usually shows real routing variation, not a harness fault.
- This reads the dataset the agent declared. Whether the pull used it is `pull_source_match`'s question.

## `dataset_parameter_match`

Retrieval · gating · deterministic · `dataset_evaluator.evaluate_dataset_selection` · runs when: `dataset_parameters` and `dataset_id` are both set

**Measures.** Whether the selected dataset carries the expected parameters: the filters, class selections or gas basis that decide which number is computed. Both sides are parsed as JSON and compared after keeping only each parameter's `name` and `values`.

**Scores.** `1.0` when the two projections are identical · `0.0` on any difference · `null` when either expected field is missing, or when no dataset was selected (parameters mean nothing without one).

**Evidence.** `reasons.dataset_parameter_match`: none · `actuals.dataset_parameter_match` (failing rows only): `actual_dataset_parameters`, the actual parameters as JSON.

**Triage.**
- The evaluator returns `null` for all three dataset checks when `dataset_id` is not set. A case with parameters but no `dataset_id` therefore shows as a miss on the reconciliation line: add `dataset_id` to the case.
- An expected value that is not valid JSON is compared as a raw string and will almost never match, so a malformed expectation reads as a failure, not an abstention.
- Parameter keys other than `name` and `values` are ignored by design.

## `context_layer_match`

Retrieval · gating · deterministic · `dataset_evaluator.evaluate_dataset_selection` · runs when: `context_layer` and `dataset_id` are both set

**Measures.** Whether the agent applied the expected context layer: an overlay intersected with the dataset, such as land cover or deforestation drivers. The special value `no_selection` asserts that the agent chose no context layer.

**Scores.** `1.0` when the normalised layer names are equal, or, for `no_selection`, when no layer was chosen · `0.0` otherwise · `null` when either expected field is missing, or when no dataset was selected.

**Evidence.** `reasons.context_layer_match`: none · `actuals.context_layer_match` (failing rows only): `actual_context_layer`.

**Triage.**
- `no_selection` is the only way to write a negative expectation. A state field holding the string `"None"` counts as no selection.
- As with `dataset_parameter_match`, a case that sets `context_layer` without `dataset_id` shows as a reconciliation miss: add `dataset_id`.

## `date_extraction`

Retrieval · gating · deterministic · `data_pull_evaluator.evaluate_date_extraction` · runs when: `start_date` and `end_date` are both set

**Measures.** Whether the agent understood the period in the prompt, read from the `start_date`/`end_date` arguments of its own `pull_data` calls (or of its `pick_dataset` calls when no `pull_data` call carried dates). Expected dates may be `YYYY-MM-DD`, `M/D/YYYY` or a bare year, which means 1 January for a start and 31 December for an end.

**Scores.** `1.0` when any of those calls matches the expected window · `0.0` when none matches, or when the agent made no dated call at all (it never scoped a request) · `null` when either expected date is missing or unparseable.

**Evidence.** `reasons.date_extraction`: none · `actuals.date_extraction` (failing rows only): `actual_extracted_start_date` and `actual_extracted_end_date`, the last window the agent used. The full list of windows is not stored; read the artefact's `tool_calls`.

**Triage.**
- A bound the agent left out is not checked, so `pull_data(start_date="2001-01-01")` with no end date passes an expectation that names both bounds. This is deliberate: open-ended requests are legitimate.
- Any matching call passes, so a comparative query that pulls twice is not penalised.
- [cases/README.md](../../../cases/README.md) rules out date expectations on annual datasets, which always pull their full range: set dates only on date-scoped cases such as alerts or imagery.

**Why it is built this way.** The `start_date`/`end_date` recorded in agent state are unreliable: for the same query they have held the requested window, the dataset's full extent or a rolling window ending today. The tool arguments are the consistent signal; `date_coverage` reads the state fields, info-only.

## `date_coverage`

No bucket · info-only · deterministic · `data_pull_evaluator.evaluate_date_selection` · runs when: `start_date` and `end_date` are both set

**Measures.** Whether the date range recorded in agent state (`start_date`/`end_date`, falling back to the last statistics entry's dates) contains the requested period. Containment, not equality, because the agent may pull a wider range and slice it in code.

**Scores.** `1.0` when the recorded range contains the expected one · `0.0` when it does not, or when the recorded range is missing or unparseable · `null` when either expected date is missing or unparseable.

**Evidence.** `reasons.date_coverage`: none · `actuals.date_coverage` (failing rows only): `actual_start_date` and `actual_end_date`, the recorded range (absent when none was recorded).

**Triage.**
- Never file a finding on this check alone; `date_extraction` is the scored date check.
- It sits in no bucket and never affects a verdict or the release gate.

**Why it is built this way.** The recorded range is unreliable (see `date_extraction`), so as a gating check it would fail correct answers. Scoring a missing range as `0.0` is tolerable only because the check does not gate.

## `data_pull_exists`

Retrieval · gating · deterministic · `data_pull_evaluator.evaluate_data_pull` · runs when: a pull is expected (`answer` or `ground_truth` is set, or `dashboard_widgets` contains `insight`, unless `clarification` is `true`)

**Measures.** Whether an analytics pull happened: the last entry in `agent_state["statistics"]` must carry a `source_url` or an `id`, or at least one row of inline data. "A pull is expected" is `ExpectedData.expects_data_pull`, the same rule `answered_without_data` and `web_fallback` use.

**Scores.** `1.0` when the last statistics entry passes that test · `0.0` when it does not, including when there is no statistics entry · `null` when no pull is expected.

**Evidence.** `reasons.data_pull_exists`: none · `actuals.data_pull_exists` (failing rows only): `data_pull_error`, either `no data retrieved` or `insufficient rows of data retrieved`.

**Triage.**
- A failure here usually explains the `chart_produced` and `charts_answer` failures on the same row: treat them as one finding, not three.
- The common cause is the agent offering a choice (a nudge) instead of pulling. If the case sets `scope`, `actuals.scope_match` then reads `clarify` or `suggest`.
- A map-only dashboard case (no `insight` widget) does not require a pull.

## `answered_without_data`

Retrieval · gating · deterministic · `guards.evaluate_guards` · runs when: a pull is expected (the `data_pull_exists` rule)

**Measures.** A confident answer with nothing behind it: a final message of at least 80 characters (`guards.SUBSTANTIVE_ANSWER_CHARS`) when no pull happened and no dataset was selected. A pull happened when the last statistics entry has a `source_url`, an `id` or non-empty data (`guards._data_was_pulled`).

**Scores.** `1.0` when the row is clean · `0.0` when all three conditions hold · `null` when no pull is expected.

**Evidence.** `reasons.answered_without_data`: none · no `actuals`. Read `actuals.agent_answer` if that check also failed, or the artefact's `final_answer`.

**Triage.**
- An agent that selects a dataset and then fails to pull passes this guard; `data_pull_exists` reports that failure.
- An ungrounded answer under 80 characters slips through. The threshold separates answers from refusals and greetings.
- `agent_answer` at `1.0` beside this check at `0.0` means a right-sounding answer with no data behind it, often from web knowledge: check `web_fallback` on the same row.

## `pull_source_match`

Retrieval · gating · deterministic · `guards.evaluate_guards` · runs when: `dataset_id` is set and a pull happened

**Measures.** Whether the pull used the expected dataset: the `dataset_id` key of the last statistics entry against the expected id, with the same `;` alternatives as `dataset_id_match`.

**Scores.** `1.0` when the pull's id matches an alternative · `0.0` when it names a different dataset · `null` when `dataset_id` is not set, no pull happened, or the statistics entry has no `dataset_id` key.

**Evidence.** `reasons.pull_source_match`: none · `actuals.pull_source_match` (failing rows only): `actual_pull_source`, the pull's dataset id. When the entry has no `dataset_id`, the evaluator writes a note naming the `source_url` and `id` it saw, but the row scores `null`, so the note never reaches the ledger: read the artefact's `statistics_last`.

**Triage.**
- `dataset_id_match` at `1.0` beside this check at `0.0` means the agent declared the right dataset and pulled from a different one.
- Only the last statistics entry is compared, so on a query that pulls twice only the second pull counts.

**Why it is built this way.** `source_url` and `id` are not compared. Source URLs name datasets by slug (`/v0/land_change/<slug>/analytics`), not by id, so matching a short id such as `11` against a URL would hit dates (`2024-11-01`) and miss every correct slug.

## `state_delta`

Retrieval · gating · deterministic · `runner.multiturn.evaluate_deltas` (outside this directory and the registry) · runs when: a multi-turn case's turn has a `deltas:` block (turn 2 onwards)

**Measures.** The state changes a turn asserts against the previous turn: `changed` (the field must differ), `retain` (it must be identical, which catches lost context) and `absent` (it must be empty, which catches state carried over by mistake). The snapshot fields (`runner.multiturn.SNAPSHOT_FIELDS`) are `aoi_ids`, `dataset_id`, `context_layer`, `start_date`, `end_date`, `suggested_datasets`, `nudge_type` and `dashboard_id`, taken from the same `actual_*` values the other checks read; the dates are the tool-call dates `date_extraction` reads.

**Scores.** `1.0` when every asserted change holds · `0.0` when any fails · `null` when a delta names a field outside the snapshot (`schema/case.schema.json` lists the same names, so a typo fails at authoring time).

**Evidence.** Stored as `t<N>.state_delta`. The reason is in `turns_detail[<N-1>].reasons.state_delta`, a `;`-joined list such as `dataset_id should have been retained: '4' -> '11'` · no `actuals`.

**Triage.**
- A turn that errors ends the conversation: later turns record no checks, and the row's verdict is `error`, not a partial score.
- The `suggested_datasets` snapshot field is legacy and always empty, because the agent no longer writes it. Assert on `nudge_type` instead.

## `ground_truth_match`

Retrieval · gating · deterministic · `groundtruth_checks.evaluate_ground_truth` · runs when: `ground_truth` is set and its values were fetched at run start

**Measures.** Whether the agent's own data pull contains the figure the analytics API returns for the case's selector (see [Run-time ground truth](../../../cases/README.md#run-time-ground-truth-ground_truth)). The harness fetches the expected values once per run, before the first trial. After each trial the runner reads the table behind the agent's last `statistics` entry (its `source_url`) and applies the selector to it, and every expected value must be matched within 2% (`llm_judges.NUMERIC_TOLERANCE`). Both sides query the same API, so this measures whether the agent built the right request and read the right number, not the data itself. A readable pull decides alone: a chart that happens to show the right figure cannot rescue a pull built with the wrong area, dataset, window or parameters. Only when the pulled table cannot be read does the check fall back to the figures in `charts_data`.

**Scores.** `1.0` when every expected value is found within tolerance · `0.0` when the readable pull lacks a value or gives a different one, or when the agent made no pull at all (a numeric question answered without data is a failure, not an abstention) · `null` when `ground_truth` is not set, or when the pull could not be read and no chart figure matched (the harness could not see, so there is no verdict against the agent). If the selector names a column the fetched response lacks, or no values were fetched for the case, both ground-truth checks stay `null` and the row gets an `error`, so the check never passes against nothing.

**Evidence.** `reasons.ground_truth_match`: the selector, then for each value the expected figure, what the agent's pull (or the chart fallback) gave and the difference, and whether that is within tolerance · `actuals.ground_truth_match` (failing rows only): `agent_ground_truth`, the same comparison · the entry's `ground_truth` object records what was fetched, its `digest`, and in `agent_values` the agent's own figure per trial (taken from its pull only, never from the chart fallback).

**Triage.**
- Only the last pull is graded. A trial that pulls more than once (a retry with corrected parameters, or two areas pulled separately) is graded on its final pull, as every check that reads `statistics` is. `agent_values` and the artefact describe the last pull only, so look for earlier pulls in the trace at `trace_url`. Several areas in one request are fine: the selector spans every id the request names.
- A flip between two runs while the case's `digest` moved is a data bump, not a regression: `tools/diff_runs.py` lists it separately and flags it when the agent's figure matches neither run's values ([Comparing two runs](../../../results/README.md#comparing-two-runs)).
- An unresolved selector is reported when the run starts (the prefetch line names the cases) and every trial of the case errors. Fix the selector against the API's column names ([cases/README.md](../../../cases/README.md#run-time-ground-truth-ground_truth), rule 1); it is not an agent failure.
- It shares an evaluator with the judged `ground_truth_answer`, whose `kind` is `mixed`, so `tools/flakiness.py` holds it to the judged stability limit.

## `chart_integrity`

Analysis · gating · deterministic · `analysis_checks.evaluate_chart_integrity` · runs when: the row produced charts (no expectation needed)

**Measures.** Whether each chart's record data was joined correctly: every field a chart's `xAxis` or `yAxis` names must be non-null in every record that has that key. Nulls there are the signature of two record sets merged into one array.

**Scores.** `1.0` when no axis field is null · `0.0` when any is · `null` when there are no charts.

**Evidence.** `reasons.chart_integrity` names the chart index, its type, the axis, the field and how many records are padded, for example `chart 0 (pie): xAxis field 'driver' is null in 3/10 records` · no `actuals`.

**Triage.**
- A failure usually means the agent merged two tables (say a ranking and a breakdown) into one array, and its prose then often quotes the wrong figure. File it against the agent.
- A key missing from every record is a `chart_well_formed` failure, not this one. Whether a chart should exist at all is `chart_produced`'s question.
- Only `xAxis` and `yAxis` are inspected.

## `class_value_match`

Analysis · info-only · deterministic · `analysis_checks.evaluate_class_values` · runs when: `class_values` is set

**Measures.** Per-class figures under a total, which `agent_answer` only notices if an error moves the total past tolerance. `class_values` lists `name=value` pairs separated by `;` (`mangroves=15,444 hectares; other=3 ha`). For each class the check finds the records, in every chart's data and in the last statistics entry, whose string fields contain the class name (case-insensitive), and takes the closest number in them; it must be within 2%.

**Scores.** `1.0` when every class is within tolerance · `0.0` when any class misses or matches no record, or when there are no data records at all · `null` when the expectation is malformed or a class value has no parseable number.

**Evidence.** `reasons.class_value_match`: none · `actuals.class_value_match` (failing rows only): `actual_class_values`, one finding per class, such as `mangroves: closest 15,444.00 (0.00%)` or `short vegetation: no matching record`. Abstention notes score `null` and never reach the ledger.

**Triage.**
- Matching is a substring test on any string field, so a short class name can match the wrong record.
- If the chart breaks the figure down by something other than the classes (by county instead of by land-cover class, say), the expectation cannot pass: fix the case.
- Records from the statistics entry count too, so a class can pass on data the chart never plots.

## `charts_answer`

Analysis and output (shared) · gating · mixed · `llm_judges.resolve_chart_verdict` · runs when: `answer` is set and the row produced charts

**Measures.** Whether the charts' own data contains the figure in `answer`, within 2%, computed in code by `chart_numeric.evaluate_numeric_support`. The candidates are every numeric value (except label-like keys such as `year`, `date`, `id` and `rank`, listed in `chart_numeric._NON_MEASURE_KEYS`), every column's sum and maximum, per-record sums across two or more measure columns and their grand total, and, when the expected figure is a percentage, each value's share of its column. The chart judge also runs, but its opinion is recorded separately as `charts_answer_judge` and never changes this score.

**Scores.** `1.0` when the closest candidate is within 2% · `0.0` when it is not, or when the chart data holds no number at all · `null` when `answer` has no figure to check (a yes/no answer, a place name, a first number that is a year or zero, or an ambiguous decimal such as `230.003`), or when the judge call failed (the row becomes `error`).

**Evidence.** `reasons.charts_answer` starts with the comparator's `deterministic check: ...` sentence and ends with the judge's. `the judge (info-only) disagreed on framing` means the row passed on the data and the judge objected; `overriding the judge (info-only)` means it failed on the data and the judge approved; `no numeric claim to check deterministically; not scored` is the `null` case · `actuals.charts_answer` (failing rows only): the charts' `insight` prose, not their data.

**Triage.**
- Act on the numbers; judge objections in the reason are info-only.
- `parse_expected_number` reads the first number in `answer`, so write the figure first (`25.5 Mha`, not `In 2020, 25.5 Mha were lost`, which abstains on the year). It converts only scale words (`thousand`, `million`, `billion`) and hectare units (`Mha`, `kha`, `ha`); give any other figure in the unit the chart uses. An expectation that is not a figure but contains a digit (`Sentinel-2`) still yields one, so put it in `text`.
- Chart payloads over 80,000 characters are cut to fit (trailing charts dropped, then data rows halved, marked `"_truncated": true`), so a failure on a very large chart may come from the cut.
- A judge outage makes this check `null` even though code decides it, because the comparator runs only after the judge call returns.

**Why it is built this way.** The judge's arithmetic is unreliable (asked about 25 yearly values summing to 25.31 Mha, it reported 27.4 Mha and 26.0 Mha), and its framing opinions flipped between identical trials. [cases/README.md](../../../cases/README.md) also rules out failing a case on chart choice.

## `charts_answer_judge`

No bucket · info-only · judge · `llm_judges.llm_judge_chart` · runs when: the same rows as `charts_answer`

**Measures.** The chart judge's opinion: whether the chart set suits the query on structure and coverage (the right measure, place, period and breakdown). It sees the chart JSON and the agent's code-act output, and its prompt forbids judging numbers. `resolve_chart_verdict` returns it as `judge_score`.

**Scores.** `1.0` when the judge approved · `0.0` when it objected · `null` when `charts_answer` did not run, or when the judge call failed (recorded in `judge_errors` as `charts_answer`).

**Evidence.** No reason of its own: the judge's sentence is inside `reasons.charts_answer` · no `actuals`.

**Triage.**
- `charts_answer` at `1.0` beside this check at `0.0` is expected and needs no action: the data holds the figure and the judge disliked the framing (for example "the user would need to manually sum all regions").
- It counts toward no bucket and never affects a verdict or the release gate. It is kept so the judge's reliability can be tracked.

## `agent_answer`

Analysis and explanation (shared) · gating · mixed · `llm_judges.resolve_answer_verdict` · runs when: `answer` is set and the final message is not empty

**Measures.** Whether the final message gives the expected answer. The judge (`llm_judges.ANSWER_JUDGE_PROMPT`) classifies the expectation as boolean, numeric, year or named entity, and scores boolean, year and named-entity rows itself. On numeric rows it only copies the main figure from the answer into `extracted_number`, and code compares that with `answer` within 2%, using the same parser as `charts_answer`.

**Scores.** `1.0` when the code comparison passes, or when it fails and the judge says the answer matches · `0.0` when both say no (on non-numeric rows, when the judge says no) · `null` when `answer` is not set, the final message is empty, or the judge call failed (the row becomes `error`). The judge's own score also decides when the code comparison cannot run: an empty extraction, a number either side cannot parse, or a percentage on one side only.

**Evidence.** `reasons.agent_answer`: the judge's sentence, or on numeric rows `deterministic check: expected ..., extracted ... from "...", a ...% difference, ...`, where `overriding the deterministic check (locale-blind number parsing)` marks a judge rescue · `actuals.agent_answer` (failing rows only): the final answer text.

**Triage.**
- The judge can rescue a code failure because the parser reads only English scale words and `.` as the decimal point, so it misreads correct answers such as `61.19万公顷` or `289,11 hectares`. A rescue is the expected outcome on non-English answers.
- Prose and chart are scored separately: `agent_answer` at `1.0` with `charts_answer` at `0.0` means right prose and a wrong or incomplete chart.
- Shared between two buckets, so a failure is not attributed to either.

**Why it is built this way.** The judge applied its own tolerance inconsistently on identical input, so code does the comparison; the rescue covers what the parser cannot read.

## `ground_truth_answer`

Analysis and explanation (shared) · info-only · mixed · `groundtruth_checks.evaluate_ground_truth` · runs when: `ground_truth` is set, its values were fetched at run start, and the final message is not empty

**Measures.** Whether the final message states the fetched figure: the usage half of run-time ground truth, where `ground_truth_match` is the retrieval half. A row can pull the right table and then state a different number. The judge (`llm_judges.judge_answer`) only extracts which number in the prose answers the question; code compares it with each fetched value within 2%.

**Scores.** `1.0` when every extracted figure is within tolerance · `0.0` when any is outside it · `null` when `ground_truth` is not set, the final message is empty, the judge returns no comparable figure for a value (nothing parseable, or a percentage), or the judge call fails.

**Evidence.** `reasons.ground_truth_answer`: for each value, the expected figure, the figure the prose states and the difference, or `JUDGE ERROR: ...` on an outage · `actuals.ground_truth_answer` (failing rows only): `agent_ground_truth_answer`.

**Triage.**
- A judge outage never turns the row to `error`. Unlike every other judged check, this one keeps the failure out of `judge_errors`, because an info-only check must not touch a verdict; the row is still decided by its gating checks, such as `ground_truth_match`.
- On a case that uses `ground_truth` instead of `answer`, `agent_answer` and `charts_answer` do not run, so this is the only check of the figure the answer states, and it does not gate.

## `expected_text_match`

Explanation · gating · judge · `llm_judges.llm_judge_expected_text` · runs when: `text` is set and the final message is not empty

**Measures.** Whether the answer contains a stated piece of information or does a stated thing, such as a caveat, a term or a refusal. The judge accepts semantic equivalents (`30 x 30 resolution` matches `30-meter by 30-meter pixels`) and treats an instruction-shaped expectation as met if the response does it.

**Scores.** `1.0` when the response includes it · `0.0` when the response omits it, contradicts it or only weakly implies it · `null` when `text` is not set, the answer is empty, or the judge call failed (the row becomes `error`).

**Evidence.** `reasons.expected_text_match`: one judge sentence · `actuals.expected_text_match` (failing rows only): the final answer text.

**Triage.**
- `text` is the home for behaviour and terminology that `answer` cannot express, but it is judged: read the reason before filing.
- Keep one expectation per `text` and make sure it cannot conflict with the case's `answer`. Two expectations that need different trials to pass make the row flap.

## `web_fallback`

Explanation · gating · deterministic · `guards.evaluate_guards` · runs when: a pull is expected and the final message is not empty

**Measures.** Whether an answer that should come from pulled data cites the web instead: any link (`http://`, `https://` or `www.`) in the final message outside the product's own domains (`guards._OWN_DOMAINS`: `globalnaturewatch.org` and `globalforestwatch.org`).

**Scores.** `1.0` when there is no outside link · `0.0` when there is at least one · `null` when no pull is expected or the answer is empty.

**Evidence.** `reasons.web_fallback`: none · `actuals.web_fallback` (failing rows only): `actual_web_links`, up to five distinct links.

**Triage.**
- The check looks at links, not provenance: a web-knowledge answer that cites nothing passes here, and `answered_without_data` covers it.
- `wri.org` links fail on purpose: they usually mean the agent answered from a WRI blog post instead of pulling data.

**Why it is built this way.** `globalforestwatch.org` is allow-listed because the product serves its own map tiles from it and links its dashboards for figures it has just pulled.

## `answer_traceability`

Explanation · info-only · deterministic · `explanation_checks.evaluate_answer_traceability` · runs when: the row produced charts and a final message (no expectation needed)

**Measures.** Whether the headline figure in the answer appears in the charts beside it. The claim is the first bold segment (`**...**`) that holds a number with a unit, scale word or percent sign (`explanation_checks._MEASURE_RE`); the comparator behind `charts_answer` checks it within 2%.

**Scores.** `1.0` when the chart data contains the claim · `0.0` when it does not · `null` when there are no charts or no answer, no bold segment qualifies, or the claim has no checkable number (a year, an ambiguous decimal).

**Evidence.** `reasons.answer_traceability`: the comparator's explanation, or `no bolded numeric claim found` (stored even on `null` rows) · `actuals.answer_traceability` (failing rows only): the claim text.

**Triage.**
- A `0.0` beside `agent_answer` at `1.0` means the prose states a figure its own chart does not show.
- Only the first qualifying claim is checked: this is a headline check, not an audit of every number.

**Why it is built this way.** Bold numbers without a unit are mostly counts and ranks (`**2** datasets`, `top **5**`), which were the main source of false failures; the unit rule filters them out.

## `chart_produced`

Output · gating · deterministic · `guards.evaluate_guards` · runs when: `answer` is set, unless `clarification` is `true`

**Measures.** Whether a case whose expected answer needs data produced a chart: `agent_state["charts_data"]` must not be empty. Chart quality belongs to `chart_well_formed`, `chart_integrity` and `charts_answer`.

**Scores.** `1.0` when there is at least one chart · `0.0` when there is none · `null` when `answer` is not set or `clarification` is `true`.

**Evidence.** `reasons.chart_produced`: none · no `actuals`. A `0.0` means exactly that `charts_data` was empty.

**Triage.**
- If `data_pull_exists` also failed, the missing chart follows from the missing pull: one finding.
- Some rows pull, answer correctly and simply leave out the chart. Whether every data answer must have a chart is a product question no case edit can settle, so treat a lone `chart_produced` flip as weak evidence.

**Why it is built this way.** Without it, a missing chart only leaves `charts_answer` at `null`, and the row is scored on its prose alone.

## `chart_well_formed`

Output · gating · deterministic · `output_checks.evaluate_chart_well_formed` · runs when: the row produced charts (no expectation needed)

**Measures.** Basic chart structure: each chart entry must be an object with non-empty record data, and every field its `xAxis` or `yAxis` names must exist in at least one record.

**Scores.** `1.0` when every chart passes · `0.0` when any chart fails · `null` when there are no charts.

**Evidence.** `reasons.chart_well_formed`, one problem per chart joined by `;`, for example `chart 1 (pie): empty data` or `chart 1 (pie): xAxis references field 'driver' absent from data` · no `actuals`.

**Triage.**
- It overlaps `chart_integrity` on purpose and splits by cause: a broken chart spec is an output failure (this check); mis-joined data under a sound spec is an analysis failure (`chart_integrity`).
- `actual_max_pie_slices` is computed for pie charts but has no threshold and is not stored in the ledger.

## `chart_type_match`

Output · gating · deterministic · `output_checks.evaluate_chart_type` · runs when: `chart_type` is set

**Measures.** Whether the first chart's `type` is one of the `;`-separated alternatives in `chart_type`, ignoring case.

**Scores.** `1.0` when it is · `0.0` when it is not, or when no chart was produced (a type expectation implies a chart) · `null` when `chart_type` is not set.

**Evidence.** `reasons.chart_type_match`: none · `actuals.chart_type_match` (failing rows only): `actual_chart_type`.

**Triage.**
- Only `charts_data[0]` is inspected, so a row whose second chart has the expected type fails.
- Chart type is the agent's least predictable output, and [cases/README.md](../../../cases/README.md) advises against staking a verdict on it; a case that does should list alternatives (`bar;table`). The census in COVERAGE.md shows whether any active case sets the field.

## `dashboard_created`

Output and scope (shared) · gating · deterministic · `dashboard_evaluator.evaluate_dashboard_created` · runs when: `dashboard_created` is set, or a dashboard was created on any row

**Measures.** Whether the agent created a dashboard this turn, read from `agent_state["dashboard_id"]`. `dashboard_created` takes `true`, `false` or no value.

**Scores.** Expected `true`: `1.0` if created, `0.0` if not · expected `false`: `1.0` if not created, `0.0` if created · no expectation: `0.0` if created (an unsolicited dashboard), `null` if not.

**Evidence.** `reasons.dashboard_created`: none · `actuals.dashboard_created` (failing rows only): `actual_dashboard_created`, the boolean.

**Triage.**
- This check can fail a case that never mentions dashboards: an unsolicited dashboard is a scope failure.
- Dashboards are on the agent's default tool profile, so a `0.0` is an agent failure, not a run-configuration artefact. Never diff two runs with different `ff` (see [Comparing two runs](../../../results/README.md#comparing-two-runs)).
- Shared between two buckets, so a failure is not attributed to either.

## `dashboard_aoi_match`

Output · gating · deterministic · `dashboard_evaluator.evaluate_dashboard_aoi` · runs when: `aoi_ids` is set and a dashboard was fetched

**Measures.** Whether the created dashboard covers exactly one area, the one the case expects. After any turn that sets `dashboard_id`, the runner fetches the dashboard from `GET /api/dashboards/{id}`; its single AOI's id is compared with `aoi_ids` (normalised as in `aoi_id_match`) and, when the case sets it, its source with `aoi_source`.

**Scores.** `1.0` when there is exactly one AOI and it matches · `0.0` when the AOI count is not one, or the id or source differs · `null` when there is no dashboard payload (none was created, or the fetch failed) or `aoi_ids` is not set.

**Evidence.** `reasons.dashboard_aoi_match`: none · `actuals.dashboard_aoi_match` (failing rows only): `actual_dashboard_aoi_id` and `actual_dashboard_aoi_count`.

**Triage.**
- A failed fetch looks the same as no dashboard: both score `null`. Check `dashboard_created` on the row, and the run's console output for `Warning: failed to fetch dashboard`, before concluding.
- This is the only check that reads `aoi_source`; an empty `aoi_source` skips the source comparison.

## `dashboard_widgets_match`

Output · gating · deterministic · `dashboard_evaluator.evaluate_dashboard_widgets` · runs when: `dashboard_widgets` is set and a dashboard was fetched

**Measures.** The dashboard's widget types as a multiset: order is ignored, counts matter. `dashboard_widgets` lists types separated by `;`, for example `insight;insight;map`.

**Scores.** `1.0` when the multisets are equal · `0.0` on any difference, including one missing widget · `null` when `dashboard_widgets` is not set or there is no dashboard payload.

**Evidence.** `reasons.dashboard_widgets_match`: none · `actuals.dashboard_widgets_match` (failing rows only): `actual_dashboard_widget_types`.

**Triage.**
- `insight` in `dashboard_widgets` also means a pull is expected, which switches on `data_pull_exists`, `answered_without_data` and `web_fallback`. A map-only dashboard case does not.
- When no dashboard was created this check is `null`, and `dashboard_created` carries the failure.

## `dashboard_widgets_valid`

Output · gating · deterministic · `dashboard_evaluator.evaluate_dashboard_widgets` · runs when: a fetched dashboard has widgets, or `dashboard_widgets` is set and none arrived

**Measures.** Whether each widget's content resolved (`dashboard_evaluator._widget_is_valid`): an `insight` widget needs a non-null `insight`; a `text` widget needs `config.text` (or a flat `text` key, for older payloads); a `map` widget needs a `tile_url` under `config.dataset` or `config.imagery`. Any other widget type is invalid.

**Scores.** `1.0` when every widget is valid · `0.0` when any widget is invalid, or when widgets were expected and none arrived · `null` when there is no dashboard payload, or when no widgets arrived and none were expected.

**Evidence.** `reasons.dashboard_widgets_valid`: none · no `actuals`. Read `actuals.dashboard_widgets_match` if it failed, or the artefact's `dashboard_widgets`.

**Triage.**
- A widget type the product adds later fails this check until `_widget_is_valid` learns it. That is a harness update, not an agent regression.
- There is no way to write "expect zero widgets" (an empty value means no expectation), so an empty dashboard on a case with no widget expectation scores `null`.

**Why it is built this way.** An empty dashboard fails only when widgets were asked for. Failing it otherwise would reward the agent for adding widgets nobody requested.

## `clarification_requested`

Scope · gating · judge · `clarification_evaluator.evaluate_clarification` · runs when: `clarification` is set

**Measures.** Whether the agent asked the user for clarification instead of attempting the task. `llm_judges.llm_judge_clarification` reads the first chart's `insight` if there is one, otherwise the final message. An answer followed by an optional offer to go further is not a clarification.

**Scores.** `1.0` when the judge's verdict matches the expectation (`true`, `1` or `yes`; `false`, `0` or `no`) · `0.0` when it does not, in either direction · `null` when `clarification` is not set or holds any other value (the judge is not called), or when the judge call failed (the row becomes `error`).

**Evidence.** No reason: the judge's explanation goes to `clarification_explanation`, which is not a reason field, so the ledger drops it · `actuals.clarification_requested` (failing rows only): the judge's boolean.

**Triage.**
- `clarification: true` turns off every check that expects a pull (`data_pull_exists`, `answered_without_data`, `web_fallback`, `chart_produced`).
- When the case can name the nudge it expects, `nudge_match` and `scope_match` read it from state and are steadier than this judge.

**Why it is built this way.** No state field records a question asked in prose, so this needs a judge. It gates without having passed the judged-check admission rule because it came from the earlier harness already gating (see [Info-only checks](#info-only-checks)).

## `nudge_match`

Scope · gating · deterministic · `nudge_evaluator.evaluate_nudge` · runs when: `nudge_type` or `nudge_options` is set

**Measures.** The agent's nudge: its structured offer of a choice, stored in the `nudge` state field as `{type, options, data?}`. The type must be one of the `;`-separated values in `nudge_type`, ignoring case. For `nudge_options`, every option the agent offers must match an expected option and at least one must; options match by case-insensitive substring in either direction, so `Odisha, India` matches `Puri, Odisha, India (District)`. The agent need not offer every expected option.

**Scores.** `1.0` when every part the case sets passes · `0.0` when any part fails, including options expected and none offered · `null` when neither field is set.

**Evidence.** `reasons.nudge_match`: none · `actuals.nudge_match` (failing rows only): `actual_nudge_type` and `actual_nudge_options`.

**Triage.**
- One extra option that the case does not list fails the check.
- For `aoi_choice` and `dataset_choice` nudges the model writes the type and the option wording, hence the loose matching; only `send_nudge` with fixed arguments is fully predictable.
- A clarification asked in prose with no `nudge` in state is invisible here; `clarification_requested` judges the prose.

## `scope_match`

Scope · gating · deterministic · `scope_checks.evaluate_scope` · runs when: `scope` is set

**Measures.** Whether the agent did the right kind of work. `scope_checks.classify_scope` puts the final state in one class, checked in this order (an agent that pulled data has analysed, whatever else it did): `analyse`, a pull happened · `suggest`, no pull and a `dataset_choice` nudge (or the legacy `suggested_datasets` field) · `clarify`, no pull and any other nudge, such as `aoi_choice` · `none`, anything else, which matches an expected `refuse`. `scope` takes `;`-separated alternatives, and `analyze` is accepted for `analyse`.

**Scores.** `1.0` when the observed class is one of the alternatives · `0.0` when it is not · `null` when `scope` is not set, or when any alternative is not a valid class (the whole expectation abstains rather than scoring on the rest).

**Evidence.** `reasons.scope_match`: none · `actuals.scope_match` (failing rows only): `actual_scope`, the observed class, so triage reads as "expected `suggest`, observed `analyse`".

**Triage.**
- An agent that asks in prose without setting a nudge classifies as `none`, so expect `clarify` only where a nudge is expected.
- An invalid value scores `null`, which the reconciliation line reports as a missing check: look there for typos.
- Use alternatives (`refuse;suggest`) when the case's own `text` allows two behaviours; a single value would flap between trials.

**Why it is built this way.** It reads state instead of asking a judge, because judged scope classification was too unstable across trials.

## `suggested_datasets_match`

Scope · gating · deterministic · `suggested_datasets_evaluator.evaluate_suggested_datasets` · runs when: `suggested_datasets` is set · **legacy**

**Measures.** Whether the agent's `suggested_datasets` state field is a non-empty subset of the expected dataset ids. The agent no longer writes this field: it was replaced by `nudge`, and dataset suggestions now arrive as a `dataset_choice` nudge.

**Scores.** `1.0` when at least one suggestion matches and none falls outside the expected set · `0.0` when the field is empty or holds an unexpected id, which today means every time · `null` when `suggested_datasets` is not set.

**Evidence.** `reasons.suggested_datasets_match`: none · `actuals.suggested_datasets_match` (failing rows only): `actual_suggested_datasets` (absent when the field is empty).

**Triage.**
- A `0.0` here is a case to update, not an agent regression.
- Do not write new cases against this field. Use `nudge_type: dataset_choice` (`nudge_match`) or `scope: suggest` (`scope_match`).
- The check stays because one parked case (`1-085`, `status: not doing`) still sets the field, pending a rewrite onto `nudge_type`/`nudge_options`.

## Info-only checks

An info-only check (`buckets.INFO_ONLY`) is recorded and reported but never affects a row verdict or the release gate: `tools/diff_runs.py` lists its regressions but never fails `--fail-on-regression` or `--fail-on-coverage-loss` on them (its headline shows them as a separate info-only count), `tools/flakiness.py` labels it `info-only` instead of holding it to a stability limit, and COVERAGE.md leaves it out of its coverage counts.

| Check | Why it is info-only | What would let it gate |
|---|---|---|
| `date_coverage` | The state field it reads records different ranges for the same query (see `date_extraction`). | A change in the agent so that state records the requested window. No threshold applies. |
| `answer_traceability` | On its first run, claim extraction picked up unitless bold counts and ranks; the unit rule now filters them. | A 3-trial run with no extraction false positives (claims that are not real measures). |
| `class_value_match` | Its expected figures were copied from unverified working notes, so its failures reported bad expectations, not bad behaviour. | A review that verifies its cases' expected figures against the source data. |
| `ground_truth_answer` | It is judged, and every new judged check starts info-only. `ground_truth_match` already gates the same figure deterministically, so gating the prose too would count one failure twice. | A standard deviation of at most 0.10 over 3 trials. |
| `charts_answer_judge` | It is the chart judge's framing opinion, which flipped between identical trials; `charts_answer` gates on the code comparison alone. | A standard deviation of at most 0.10 over 3 trials. [cases/README.md](../../../cases/README.md) separately rules out failing a case on chart choice. |

New judged checks start info-only and gate only once a 3-trial run shows a standard deviation of at most 0.10. Three judged checks gate without having passed that step (`agent_answer`, `expected_text_match` and `clarification_requested`), because they came from the earlier gnw-evals harness already gating; `tools/flakiness.py` still holds them to the judged limit.

Two interactions to keep in mind when reading a bucket table:

- `date_coverage` and `charts_answer_judge` sit in no bucket. `answer_traceability` and `class_value_match` are tagged to explanation and analysis, and `ground_truth_answer` is shared between analysis and explanation. `buckets.summarize_buckets` does not filter info-only checks, so they count toward those buckets' pass and evaluated tallies and `rows_covered`, while never touching a verdict.
- `buckets.implied_checks` implies `class_value_match` whenever `class_values` is set, so its absence shows on the reconciliation line, while COVERAGE.md leaves info-only checks out of its coverage counts. The two count slightly different populations.

## Adding a check

1. Decide whether an absence scores `null` (the check does not apply) or `0.0` (a failure), and write the reason in the evaluator's docstring and in this file's entry.
2. Write the evaluator in this directory and register it in `registry.EVALUATORS` with its `score_fields` and `kind`. The runner merges every evaluator's result and later evaluators overwrite earlier keys, so use output names no other evaluator writes. `kind` (`deterministic`, `llm_judge` or `mixed`) decides which stability limit `tools/flakiness.py` applies.
3. Name reason fields `<check>_reason` so the ledger keeps them, and list the `actual_*` fields that explain a failure in `cli.ACTUALS_FOR_CHECK`.
4. In `buckets.py`, put the check in `DEDICATED` or `SHARED` (or neither, if it should count toward no bucket), and also in `INFO_ONLY` if it must not gate. `tests/test_buckets.py::test_every_registered_check_is_tagged_exactly_once` fails if a registered check is in none of the three sets, a tagged name is not registered, or a check is in both `DEDICATED` and `SHARED`.
5. If a case's expected values guarantee the check must evaluate, add it to `buckets.implied_checks`, so a silent `null` shows on the reconciliation line. Leave out checks that may legitimately abstain.
6. A new expected field also needs an `ExpectedData` field in `eval_types.py`, an entry in `FIELD_CHECKS` in `tools/coverage_doc.py`, and authoring guidance in [cases/README.md](../../../cases/README.md).
7. Ship a deterministic check after a clean run on known-good cases. Ship a judged check info-only until a 3-trial run shows a standard deviation of at most 0.10.
8. Add a row to the [Index](#index) and an entry to this file. When a check's semantics change, pass `--note` on the next run, so a diff against an earlier run is not read as an agent change.
