# Eval datasets

CSV files in this directory are end-to-end evaluation cases run via the [`gnw_evals`](https://github.com/wri/gnw-evals) CLI against the agent API.

## Schema

Columns match the GOLD CSV one-to-one. The authoritative schema is the `ExpectedData` pydantic model in [gnw-evals/src/gnw_evals/utils/eval_types.py](https://github.com/wri/gnw-evals/blob/main/src/gnw_evals/utils/eval_types.py).

Required:
- `query` — the user message to send to the agent.

Optional (only evaluated if present):
- `expected_aoi_ids` — GADM ID(s). Semicolon-separated for alternates.
- `expected_dataset_id` — dataset numeric ID. Source valid IDs from the dataset catalog YAML configs in `src/agent/datasets/catalog/`.
- `expected_context_layer` — dataset-specific; `no_selection` to assert an empty selection.
- `expected_start_date`, `expected_end_date` — `YYYY-MM-DD` or `YYYY`.
- `expected_answer` — natural-language answer; graded by LLM judge.
- `expected_text` — substring/semantic-inclusion check on the agent's reply.
- `expected_clarification` — boolean. Whether the agent should ask for clarification instead of answering.

Metadata:
- `test_id` — short stable id for the case. Use `smoke-<n>` or `bug-<github-issue-number>`, for example.
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
export API_TOKEN=<wri-bearer-token>
export ANTHROPIC_API_KEY=<your-anthropic-api-key>
export API_BASE_URL=<your-api-base-url>  # e.g. http://localhost:8000 or https://api.staging.globalnaturewatch.org
```

Full options:

```
Usage: gnw_evals [OPTIONS]

Options:
  --api-base-url TEXT     Base URL for API tests (env var: API_BASE_URL)
  --api-token TEXT        API token for authentication (env var: API_TOKEN)
  --sample-size INTEGER   Sample size: 1 means run single test, -1 means run all rows
  --eval-set              Which eval set to run: gold, location_id, dataset_id,
                          dataset_interpretation, analysis_results,
                          analysis_interpretation, guardrail, date_selection, or all
  --test-file TEXT        Path or URL to test dataset CSV file
  --test-group-filter     Filter by test_group column
  --status-filter TEXT    Filter by status column (comma-separated values)
  --output-filename TEXT  Custom filename (timestamp will be appended)
  --num-workers INTEGER   Number of parallel workers for test execution
  --random-seed INTEGER   Random seed for sampling (0 means no random sampling)
  --offset INTEGER        Offset for getting subset. Ignored if random_seed is not 0
  --num-trials INTEGER    Number of trials per test for robustness measurement
  --help                  Show this message and exit.
```

The commands below use tag `zeno-evals-v1` from the [gnw-evals](https://github.com/wri/gnw-evals) repo. Update the tag in the commands if a newer version is released.

```bash
# Filter to one test group with --test-group-filter
# --sample-size -1 runs all matching rows (default is 5)
uvx --from "git+https://github.com/wri/gnw-evals@zeno-evals-v1" gnw_evals \
    --test-file $(pwd)/tests/evals/datasets/evals.csv \
    --test-group-filter regression \
    --sample-size -1 \
    --num-workers 3 \
    --num-trials 1
```

Or trigger the `Evals` workflow manually from the GitHub Actions tab.
