# Eval datasets

CSV files in this directory are end-to-end evaluation cases run via the [`gnw_evals`](https://github.com/wri/gnw-evals) CLI against the agent API.

## Schema

Columns match the GOLD CSV one-to-one. The authoritative schema is the `ExpectedData` pydantic model in [gnw-evals/src/gnw_evals/utils/eval_types.py](https://github.com/wri/gnw-evals/blob/main/src/gnw_evals/utils/eval_types.py).

Required:
- `query` — the user message to send to the agent.

Optional (only evaluated if present):
- `expected_aoi_ids` — GADM ID(s). Semicolon-separated for alternates.
- `expected_dataset_id` — dataset numeric ID. Source valid IDs from the [gnw-evals spreadsheet](https://github.com/wri/gnw-evals) — should use that as the reference for current dataset IDs. Semicolon-separated for alternates.
- `expected_context_layer` — dataset-specific; `no_selection` to assert an empty selection.
- `expected_start_date`, `expected_end_date` — `YYYY-MM-DD` or `YYYY`.
- `expected_answer` — natural-language answer; graded by LLM judge.
- `expected_text` — substring/semantic-inclusion check on the agent's reply.
- `expected_clarification` — boolean. Whether the agent should ask for clarification instead of answering.

Metadata:
- `test_id` — short stable id for the case. Use `smoke-<n>` or `bug-<github-issue-number>`.
- `status` — `ready` | `skip` | `rerun`. Leave empty for active cases.
- `test_group` — subdivision tag (e.g. `aoi`, `dataset`, `dates`, `regression`). Filterable from CLI.
- `priority` — free-text label.

## Adding a case

1. Append a row to `evals.csv`. Use only the columns you need; leave others empty.
2. Run locally first (see below) and confirm it passes against your branch.
3. Open a PR. The case will run on the next staging deploy and on every subsequent deploy.

## Running locally

Run these commands from the **project-zeno root directory**.

Set credentials before running:

```bash
export API_TOKEN=<your-gnw-machine-user-api-token>
export ANTHROPIC_API_KEY=<your-anthropic-api-key>
export API_BASE_URL=<your-api-base-url>  # e.g. http://localhost:8000 or https://api.staging.globalnaturewatch.org
```

Key arguments:
- `--test-file` — path to the CSV file containing the eval cases
- `--num-workers` — number of tests to run in parallel
- `--num-trials` — number of times to run each test; use >1 to measure variance across runs
- `--sample-size` — number of tests to run (default: 5); use `-1` to run all
- `--offset` — starting row index into the dataset (after filters); e.g. `--sample-size 5 --offset 5` runs rows 5–9. Ignored when `--random-seed` is set.

Pin to the same gnw-evals SHA the CI workflow uses (see `.github/workflows/evals.yaml`):

```bash
GNW_EVALS_REF=467906518809a64c45e72b3a285c4d55f7819aef

uvx --from "git+https://github.com/wri/gnw-evals@${GNW_EVALS_REF}" gnw_evals \
    --test-file $(pwd)/tests/evals/datasets/evals.csv \
    --num-workers 3 \
    --num-trials 1 \
    --sample-size 5 \
    --offset 0
```

Filter to one test group:

```bash
uvx --from "git+https://github.com/wri/gnw-evals@${GNW_EVALS_REF}" gnw_evals \
    --test-file $(pwd)/tests/evals/datasets/evals.csv \
    --test-group-filter regression \
    --num-workers 3 \
    --num-trials 1 \
    --sample-size 5 \
    --offset 0
```

## Running against staging

Run from the **project-zeno root directory**.

```bash
uvx --from "git+https://github.com/wri/gnw-evals@${GNW_EVALS_REF}" gnw_evals \
    --test-file $(pwd)/tests/evals/datasets/evals.csv \
    --num-workers 3 \
    --num-trials 1 \
    --sample-size 5 \
    --offset 0
```

Or trigger the `Evals` workflow manually from the GitHub Actions tab.
