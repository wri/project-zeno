# Step-level evals

This directory holds step-level evals: each test runs one agent step against a fixed `AgentState` fixture and has an LLM judge score the output against a written rubric. `test_judge_flow.py`, for example, runs `generate_insights` on a GHG net-flux fixture and checks the chart type and the source/sink wording.

- `judge.py`: runs the step (`run_generate_insights`) and the judge (`judge_output`, using `SMALL_MODEL`), returning a `Verdict`.
- `conftest.py`: fixtures. The database is overridden to no-ops; the LLM calls are real.
- `fixture_data.py`: the `AgentState` fixtures.

## Running

These tests call real LLM APIs, so the model keys in your `.env` must be set. No database is needed.

```bash
uv run pytest tests/evals
```

Each session writes a JSON file with every test's query, tool output, judge prompt, judge response and verdict to `tests/evals/results/` (gitignored).

## Routing set

The routing set measures curated charts first (`docs/curated-charts-first-plan.md`). Each case is a chart request of a user, with the dataset, the number of areas, and the route that the request must take: `standard` (a curated chart) or `custom` (a chart from the code executor). The harness is in `routing/routing_set.py`. It does not call a model.

The harness counts two kinds of error:

- **Wrong answer**: the agent shows a curated chart for a request that needs a custom chart.
- **Cost**: the code executor runs for a request that a curated chart answers.

`routing/seed.jsonl` has a small set of invented prompts. The real prompts of the demand analysis are internal to WRI. Do not add them to this repository. Keep them in a file outside the repository, and give its path to the harness:

```bash
uv run python -m tests.evals.routing.routing_set /path/to/routing-set.jsonl
```

You can also set `ZENO_ROUTING_SET` to the path. The file can be JSON Lines or CSV. The fields are in the docstring of `routing_set.py`. The unit tests of the format are in `tests/unit/agent/test_routing_set.py`.

## End-to-end eval cases

End-to-end cases (a question in, the final agent state scored) belong in the GOLD regression suite, [wri/gnw-gold-evals](https://github.com/wri/gnw-gold-evals). Add a feature's acceptance cases there.

The CSV cases that used to live in `tests/evals/datasets/` and ran through the [gnw-evals](https://github.com/wri/gnw-evals) CLI and the `Evals` workflow were retired on 2026-10-21. The workflow had never run, and its pinned gnw-evals tag could not score feature flags, nudges or dashboards. The CSVs remain in git history (`git log -- tests/evals/datasets`) if a case is worth porting to GOLD.
