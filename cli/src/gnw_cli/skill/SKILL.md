---
name: gnw-cli
description: Answer questions with Global Nature Watch (GNW) data (forest, tree cover loss, land cover, emissions, alerts for countries, admin areas, protected areas, KBAs, indigenous lands) using the `gnw` command line tool, so that every number comes from a file and the analysis can be repeated. Use when a user asks for GNW or Global Forest Watch statistics in a coding environment.
---

# GNW data with the `gnw` CLI

`gnw` pulls GNW statistics into files. Each pull lands in
`gnw/pulls/<result_id>/`:

| File | Holds |
|---|---|
| `rows.csv` | The rows, every column |
| `request.json` | The request sent to the GNW analytics API |
| `provenance.json` | Areas, dates, options, retrieval time, `rows_sha256`, server version and commit |
| `pull.py` | A standalone script (Python 3.9+, no packages) that fetches the same rows again |
| `charts.json` | GNW's curated charts, after `gnw charts` |

`gnw/manifest.json` lists the commands that made each folder.

## Workflow

1. **Find the areas.** `gnw areas "Pará, Brazil"` lists matches with their
   `aoi_id` (`gadm:BRA.14_1`). Never write an area id from memory. When a
   name matches places in more than one country, ask the user which one.
2. **Choose the dataset.** `gnw datasets` lists them; `gnw datasets <id>`
   shows one dataset's dates, context layers, canopy cover options and
   cautions. Read the cautions before you interpret anything.
3. **Pull.** `gnw pull --aoi <id> [--aoi <id> ...] --dataset <id> [--start
   YYYY-MM-DD] [--end YYYY-MM-DD] [--context-layer ...] [--canopy-cover N]`.
   It prints the folder, the row count and the columns, not the rows.
4. **Analyse in code.** Write `gnw/analysis.py` that reads the pulls'
   `rows.csv` files (pandas or the csv module) and computes every number you
   report: totals, changes, rankings, shares. Run it and quote its output.
   Do not read numbers off a file and type them into your answer or into
   code.
5. **Chart.** `gnw charts` (same options as `pull`) writes GNW's own charts
   to `charts.json`: prefer them for the standard view of a dataset. To draw
   other charts, follow the `gnw-charting` skill: the dataset's chart types,
   colors, wording and cautions. Draw them from `analysis.py` too.
   `python .claude/skills/gnw-charting/generators/run.py <dataset_id>
   gnw/pulls/<result_id>/rows.csv` runs GNW's own chart code on a pull's
   rows without the server (needs numpy), so the curated charts can be part
   of the repeatable analysis.

## Every answer ends with

- **What was pulled:** dataset, areas, dates and options, from
  `provenance.json`, including a date range the server fitted to the
  dataset.
- **How to repeat it:** the commands, in order, e.g.
  `python gnw/pulls/<result_id>/pull.py` then `python gnw/analysis.py`.
- **The cautions** of the dataset that apply, and its **citation** with the
  access date filled in.

## Checking a result again

`gnw replay` runs every `pull.py` again. It reports each pull whose rows
differ from the ones first pulled (the data was updated) and exits with an
error when any did. The new rows go to `rows.changed.csv`; `rows.csv` keeps
the rows the analysis was built on, so compare the two before you update an
answer.

## Options

Every command takes `--json` (print JSON instead of a summary), `--out DIR`
(default `gnw`) and `--server URL` (default `$GNW_MCP_URL`, then the public
GNW server). `gnw chart-code <dataset_id>` prints the code GNW draws a
dataset's curated charts with.
