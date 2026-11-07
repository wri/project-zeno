---
name: gnw-charting
description: Chart and describe Global Nature Watch (GNW) data the way GNW does: which chart to draw for each dataset, its colors, the wording to use and avoid, its cautions and citation, and GNW's own curated chart code, the columns of each dataset's rows, and how to keep an analysis repeatable. Use when analysing, charting, summarising or presenting data from the GNW MCP server (pull_data, curated_charts) or the gnw CLI.
---

# Charting GNW data

Data from the Global Nature Watch MCP server comes with rules: each dataset
has a way GNW charts it, colors it, and words it, and cautions a reader must
see. This skill holds those rules, one file per dataset, made from GNW's
catalog and chart code.

## Workflow

1. **Prefer the curated charts.** `curated_charts` returns the charts GNW
   itself shows for a dataset, drawn by code GNW maintains, with their data
   and colors. When the user wants the standard view of a dataset, render
   those specs as they are, keep their titles, and say they are GNW's
   charts.
2. **Draw your own** when the question needs another view (a comparison, a
   subset, a different breakdown). Read the dataset's file below first: its
   "How to chart it" rules are GNW's, and they override the general advice
   here. The dataset's curated generator (in `generators/`) shows how GNW
   filters, sorts and sums the same rows, and
   `python generators/run.py <dataset_id> rows.csv` runs GNW's generator on
   a pull's rows outside GNW (it needs numpy): the curated charts, made in
   your own analysis.
3. **Present it** as the dataset's "How to present it" says, with the
   wording guide below, the cautions that apply, and the citation.

## Repeatable analysis

Every pull comes with what it takes to repeat it: `pull_data` and
`curated_charts` return the request sent to the analytics API, the pull's
provenance, and `script`, a standalone `pull.py` (Python 3.9+, no packages)
that fetches the same rows into `gnw/pulls/<result_id>/rows.csv`. The `gnw`
CLI writes these files itself.

- **When you can run code, analyse in code.** Run `pull.py` (or `gnw pull`)
  and compute every number you report from `rows.csv`: totals, changes,
  shares, rankings. Each dataset's file lists its columns, types and units,
  so you can write the code before you see the rows.
- **Keep it in one script** that starts from the pulls' `rows.csv` files and
  draws the charts too, so `python pull.py` then `python analysis.py`
  repeats the whole result.
- **Never copy numbers** from a tool result into code or into the answer as
  data; read them from the files.
- **End the answer with** what was pulled (dataset, areas, dates and
  options, including a date range the server fitted to the dataset), how to
  repeat it (the scripts or commands, in order), the cautions that apply,
  and the citation with the access date filled in.
- **Without code** (in a chat), quote only numbers a tool returned, and
  offer the user the result's `pull.py`, which repeats the pull.

`pull.py` warns when the rows it fetches differ from the ones first pulled
(`rows_sha256`): the data was updated since.

## Rules for every chart

- Chart only numbers a tool returned. Never fill in a missing year or area.
- Use the dataset's colors (in its file, or from `get_dataset`). A chart with
  one series takes the series color; categories take their category colors.
  Do not invent colors for categories the palette lists.
- One metric per chart: area and emissions, or area and counts, go in
  separate charts. A title names only the metric(s) plotted, the area and
  the period, e.g. "Annual Tree Cover Loss in Pará (2018-2023)".
- Give units on the axis or in the title (ha, MgCO2e).
- State the options the pull ran with: the canopy cover threshold, the
  context layer, and any date range the server fitted to the dataset.
- Sort a time series by date and a ranking by value.
- Keep a pie to 6-8 slices; group the rest as "Other".

## Chart types

GNW renders these types: `line`, `bar`, `stacked-bar`, `grouped-bar`, `pie`, `area`, `scatter`, `table`. Use the same names when you hand a
chart to GNW, in the `InsightChart` shape the curated charts come in
(`chart_type`, `x_axis`, `y_axis`, `color_field`, `series_fields`,
`chart_data`, `color_map`, `series_color`).

- **line**: a time series or trend; several series in wide format.
- **bar**: comparisons and rankings, and annual totals.
- **stacked-bar**: composition within each category or year.
- **grouped-bar**: several metrics side by side, in long format.
- **pie**: part of a whole.
- **area**: cumulative or stacked time series.
- **scatter**: two variables against each other.
- **table**: detail that a chart would not show well, such as transitions.

## Wording

- Use dataset cautions/limitations proactively but briefly (e.g. clarify tree cover loss vs deforestation when relevant).
- Avoid strong or vague claims without evidence.

**Avoid:** overwhelming, severe, exceptional, critical, concerning, highly, substantial, considerable, notable, remarkable, important, major, crucial, key, strong, robust, dramatic, meaningful (vague), alarming, worrying, problematic, challenging, unfavorable, promising, encouraging, favorable.

**Prefer:** decline, decrease, increase, remain stable, fluctuate.

**Use carefully (need justification):** trend (if not calculated), significant (if not statistical), validated, accurate (without comparison).

- Use markdown with blank lines between sections.

## Datasets

| Id | Dataset | Curated charts | File |
|---|---|---|---|
| 1 | Global land cover | yes | [datasets/01-global-land-cover.md](datasets/01-global-land-cover.md) |
| 2 | Global natural/semi-natural grassland extent | yes | [datasets/02-global-natural-semi-natural-grassland-extent.md](datasets/02-global-natural-semi-natural-grassland-extent.md) |
| 3 | SBTN Natural Lands Map | yes | [datasets/03-sbtn-natural-lands-map.md](datasets/03-sbtn-natural-lands-map.md) |
| 4 | Tree cover loss | yes | [datasets/04-tree-cover-loss.md](datasets/04-tree-cover-loss.md) |
| 5 | Tree cover gain | yes | [datasets/05-tree-cover-gain.md](datasets/05-tree-cover-gain.md) |
| 6 | Forest greenhouse gas net flux | yes | [datasets/06-forest-greenhouse-gas-net-flux.md](datasets/06-forest-greenhouse-gas-net-flux.md) |
| 7 | Tree cover | yes | [datasets/07-tree-cover.md](datasets/07-tree-cover.md) |
| 8 | Tree cover loss by dominant driver | yes | [datasets/08-tree-cover-loss-by-dominant-driver.md](datasets/08-tree-cover-loss-by-dominant-driver.md) |
| 9 | Deforestation (sLUC) Emission Factors by Agricultural Crop | yes | [datasets/09-deforestation-sluc-emission-factors-by-agricultural-crop.md](datasets/09-deforestation-sluc-emission-factors-by-agricultural-crop.md) |
| 10 | Tree cover loss due to fires | yes | [datasets/10-tree-cover-loss-due-to-fires.md](datasets/10-tree-cover-loss-due-to-fires.md) |
| 11 | Integrated alerts | yes | [datasets/11-integrated-alerts.md](datasets/11-integrated-alerts.md) |

`generators/base.py` holds the helpers the generators share.
