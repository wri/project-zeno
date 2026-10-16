# Curated charts in `generate_insights`

*Status: proposal. Replaces `curated-vs-generative-charts-plan.md`
(commit `32c16fe8`, never merged).*

## Goal

For LGMS, `generate_insights` shows the curated LGMS charts. The workflow
stays the same for the user: one call, one insight, saved and shown. The
code-execution loop does not run.

The agent does not interpret LGMS data. It shows the standard charts and
nothing else.

## Rules for LGMS

| Rule | Decision |
|---|---|
| Charts | Always the four standard charts. No custom charts, figures, or cuts. |
| Areas | One area per pull. No comparison of areas. |
| Restyle | `update_insight_display` does not change LGMS insights. |
| Interpretation | No numbers, trends, rankings, comparisons, causes, or judgements from LGMS data, from the model or from the agent. |
| Requests outside these rules | The agent declines politely and tells the user what it can show. |

The agent can still:

- tell the user that the charts are shown, and give the chart titles;
- repeat the catalog text for LGMS: `description`, `methodology`,
  `cautions`, `citation`, and the answers in `presentation_instructions`
  (for example, "carbon stock is not in scope").

## Why LGMS first

Today the LGMS `code_instructions` (`catalog/land_ghg_inventory.yml:132`)
make the code executor return one plain table. `LGMSChartGenerator` already
makes four charts from the same rows. The curated path is the only way for
the agent to show LGMS charts.

## Out of scope

- **The LGMS exclusion.** `DEFAULT_EXCLUDED_DATASETS` hides LGMS until the
  public release (PR #784). This plan does not change it. Test under the
  `experimental` profile.
- **Curated charts for other datasets**, and the choice between curated and
  generative charts. See "Later".
- **A provenance column on `InsightOrm`.**

## Design

The design uses one catalog flag. Every guard reads the flag, so no code
checks the LGMS id directly.

### 1. Catalog flag

Add `curated_only: true` to `land_ghg_inventory.yml`. The default is
`false`. `src/agent/datasets/curated_only.py` holds the helper
`is_curated_only(dataset_id) -> bool` and the model-facing texts that the
guards use.

### 2. Shared curated step

Add one function in `src/api/services/charts/`:

```python
async def build_curated_charts(
    dataset_id: int, rows: list[dict], language: str
) -> list[InsightChart]
```

It finds the generator, calls `generate()`, localises titles and labels, and
calls `resolve_chart_colors()`. Move the matching and `_localise` out of
`AnalyzeService`. `AnalyzeService` then calls this function.

`resolve_chart_colors()` sets `dataset_id` on each chart. The guards in
steps 5 and 6 need that value on saved charts.

### 3. `pull_data`: one area only

Add a guard next to the excluded-dataset guard (`pull_data.py:159`). If the
dataset is `curated_only` and the selection has more than one AOI, do not
pull. Return a polite message (new i18n key): the dataset supports one area
at a time, and the user can pick one area.

### 4. `generate_insights`: the curated-only path

In `Analyst.analyze()`, before stage 1:

```
latest = statistics[-1]
if is_curated_only(latest["dataset_id"]):
    rows    = rows of latest pull (source_url + merge_lgms_sections)
    charts  = build_curated_charts(...)
    if not charts: return polite error, no code path
    text    = fixed i18n text, no LLM call
    follow_ups = []
    persist with codeact_parts = []
    return the curated-only tool message
```

Notes:

- Use the latest pull only. `state["statistics"]` holds every pull in the
  thread (`state.py:113`).
- Check again for one AOI. This is a second guard after step 3.
- Do not call `InsightTextGenerator`. The narrative is a fixed i18n string,
  for example: "Land GHG Monitoring System (LGMS) charts for {area},
  {start_year}–{end_year}." No model writes text about LGMS data.
- The tool does not accept a request for custom output. The query does not
  change the result.
- When the latest pull is another dataset, remove curated-only pulls from
  the statistics before the code path. The code executor never receives
  curated-only rows, also not as context for another insight.

### 5. No LGMS data reaches the orchestrator

The orchestrator cannot interpret data that it does not receive. Today two
places send chart rows to it:

| Place | Change |
|---|---|
| `_build_tool_message` (`analyst/tool.py:337`) | For curated-only, send chart titles and the instruction below. Send no rows. |
| `format_chart_data` (`inspect_view_context.py:200`) | If `chart.dataset_id` is curated-only, return one line: "Data withheld: do not interpret this chart." This also covers `format_insights` and dashboards. |

The instruction in the tool message (English, model-facing):

> The standard LGMS charts are now shown to the user. Do not describe,
> summarise, compare, rank, or interpret any values or trends in them, and
> do not give numbers. Tell the user the charts are shown. If the user asks
> for a figure, a trend, a comparison, a different chart, or an explanation
> of the data, decline politely and say that only the standard charts are
> available for this dataset.

### 6. `update_insight_display`: decline

If any chart of the target insight has a curated-only `dataset_id`, return a
polite message and change nothing.

### 7. Reminder on every turn

`SessionContextMiddleware` writes the session block on every turn
(`middleware.py`). When `state["dataset"]` is curated-only, add to the
`Dataset:` line: "standard charts only — do not interpret the data; decline
custom requests." A follow-up question in a later turn ("why did emissions
go up?") then still sees the rule.

### 8. Skill update

In `analyze.md`, add one requirement: for a dataset marked
"standard charts only", call `generate_insights` once, then only confirm the
charts are shown. Do not interpret the data. Decline custom requests,
comparisons of areas, and restyles politely.

## Known gap

LGMS insights created through `POST /api/analyze` before step 2 have no
`dataset_id` on their charts. The guard in step 5 cannot see them. LGMS is
hidden, so there are probably few such rows. Backfill them, or accept the
gap.

## Tests

| File | Covers |
|---|---|
| `tests/unit/api/services/test_curated_charts.py` | Matching, localisation, `dataset_id`; the LGMS charts from the default registry |
| `tests/unit/agent/tools/test_curated_only.py` | Catalog flag; no executor or text-generator call; fixed text; latest pull only; more than one AOI refused; no fallback without data; no curated-only rows to the executor; no rows in the tool message or in `format_chart_data`; session line; restyle refused; `pull_data` refuses two AOIs |

Not automated yet: a live conversation check. Ask "Which year had the
highest emissions?", "Compare Pará and Amazonas", and "Why did soil
emissions rise?" under the `experimental` profile. The agent must decline
and give no numbers. This needs a valid `WRI_BEARER_TOKEN`.

## Later

- Curated charts for other datasets, where the model chooses between curated
  and generative charts. That needs eligibility rules per generator
  (context layer, parameters, one AOI) and a short description of each
  standard chart for the agent.
- Remove the LGMS `code_instructions` when no path uses them.
