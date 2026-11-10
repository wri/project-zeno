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

## End-to-end eval cases

End-to-end cases (a question in, the final agent state scored) belong in the GOLD regression suite, [wri/gnw-gold-evals](https://github.com/wri/gnw-gold-evals). Add a feature's acceptance cases there.

The CSV cases that used to live in `tests/evals/datasets/` and ran through the [gnw-evals](https://github.com/wri/gnw-evals) CLI and the `Evals` workflow were retired on 2026-10-21. The workflow had never run, and its pinned gnw-evals tag could not score feature flags, nudges or dashboards. The CSVs remain in git history (`git log -- tests/evals/datasets`) if a case is worth porting to GOLD.
