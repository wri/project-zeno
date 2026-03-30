# Evals

Evals are end-to-end tests that run real LLM calls against a rubric. Unlike unit tests, which assert on deterministic logic, evals assert on LLM _behavior_... whether the agent produced the right output, chose the right tool, triggered the right guardrail.

The patterns below are not an exhaustive list — they're examples of what's already been built and a starting point for thinking about coverage. If you're adding a feature that involves LLM behavior at any stage of the pipeline, consider whether an eval fits.

---

## Eval patterns (so far)

### 1. `generate_insights` judge evals (`tests/evals/`)

Used to evaluate whether `generate_insights` produces correct visualizations and insights given pre-baked data. The pattern:

1. **Pre-bake the agent state** — construct a `statistics` fixture with realistic data (see `fixture_data.py`)
2. **Call `generate_insights` directly** — skip the rest of the agent pipeline
3. **Let an LLM judge the output** — `judge.py` sends the chart type, data preview, and insight text to Haiku with a rubric, which returns PASS/FAIL with per-requirement explanations
4. **Assert on the verdict**

```python
async def test_tree_cover_loss_bar_chart(run_insights, judge, tcl_state):
    result = await run_insights("Show tree cover loss in Para Brazil", tcl_state)
    verdict = await judge(
        query="Show tree cover loss in Para Brazil",
        rubric="""
        - Chart type is bar
        - X-axis is year
        - Y-axis is area in hectares
        - Data covers 2015–2022
        """,
        tool_output=result,
    )
    assert verdict.passed, verdict.comment
```

Results are written to `tests/evals/results/` as JSON, keyed by branch and timestamp, so you can compare pass rates across branches.

**What runs for real:** The `generate_insights` LLM call (Gemini Flash).

**What is mocked:** Everything upstream — no DB, no RAG, no analytics API. You own the `statistics` input.

---

### 2. Agent-level routing evals (`tests/evals/test_pick_aoi_evals.py`)

Used to evaluate whether the full agent makes the right tool calls and respects guardrails given a user query. The pattern:

1. **Mock the I/O boundaries** — spatial DB queries and the analytics API orchestrator are replaced with DataFrames and stub responses
2. **Run the full agent graph** — real LLM calls decide which tools to invoke and with what arguments
3. **Inspect the agent state** — assert on what ended up in state (e.g. `aoi_selection`, tool messages)

```python
async def test_eval_which_state_brazil_most_tcl_2019(structlog_context):
    steps = await _run_agent(
        query="Which state in Brazil had the most tree cover loss in 2019",
        mock_aoi_df=BRAZIL_AOI_RESULT,
        mock_subregion_df=BRAZIL_STATES_RESULT,   # 26 states
    )
    aoi_selection = _get_aoi_selection(steps)
    assert len(aoi_selection["aois"]) == 26
    assert not any("too many" in m.lower() for m in _collect_tool_messages(steps))
```

**What runs for real:** The agent's reasoning loop, tool selection, `pick_aoi`'s LLM-based disambiguation, `pick_dataset`'s RAG + LLM call, `generate_insights`.

**What is mocked:**
- `query_aoi_database` and `query_subregion_database` — patched at the module level in `pick_aoi.py`, so the PostGIS queries return fixed DataFrames
- `data_pull_orchestrator.pull_data` — patched on the global singleton instance (not the tool itself, which is already captured by reference in the compiled graph), so the WRI analytics API is never called

The mock DataFrames are the test's "input hypothesis" — they represent what the DB _would_ return for a given query. The LLM still has to interpret the query correctly and call the right tools.

---

## Other patterns worth considering

The two patterns above cover tool output quality and end-to-end routing. Here are other cuts that could be useful as the agent grows:

**Single-tool LLM evals.** The same judge pattern from pattern 1 can be applied to any tool with an LLM step — not just `generate_insights`. `pick_aoi` has an LLM disambiguation step (when multiple candidate locations match, it selects the best one). `pick_dataset` runs a RAG + LLM selection. Both are candidates for isolated evals that call just that tool with controlled inputs and assert on the selection made.

**Dataset onboarding evals.** When adding a new dataset YAML, write an eval that confirms the full pipeline works for a representative query: the agent finds the dataset via RAG, pulls data, and produces a sensible chart. This catches misconfigured `prompt_instructions`, wrong column assumptions, or broken API endpoints before the dataset ships.

**Multi-turn conversation evals.** The agent maintains state across turns via the PostgreSQL checkpointer. A multi-turn eval would run two or more sequential queries in the same `thread_id` and assert that context carries over correctly — e.g. "Show deforestation in Para" followed by "Now compare it to Amazonas" should reuse the dataset selection from turn 1. These require the real DB checkpointer or a memory checkpointer substitute.

**Adversarial / out-of-scope evals.** Queries that the agent should _not_ answer — requests for data the system doesn't have, geographies that don't exist, questions outside environmental monitoring. Assert that the agent responds with a graceful refusal rather than hallucinating data or crashing. The anti-pattern guardrail test in `test_pick_aoi_evals.py` is an example of this applied to AOI limits; the same pattern extends to semantic refusals.

**Prompt regression evals.** After modifying the system prompt in `get_prompt()` or any dataset's `prompt_instructions`, run a fixed set of evals against the new prompt to detect unintended regressions in routing or output quality. These are the same evals you already have — the value is in running them as a before/after comparison.

---

## How they complement unit tests

```
Unit tests          →  deterministic logic (limit constants, date parsing, validation functions)
Agent-level evals   →  routing & guardrails (did the agent call the right tool with the right args?)
Tool-level evals    →  single-tool LLM behavior (did pick_dataset choose the right dataset?)
generate_insights   →  output quality (is the chart type right? does the insight answer the question?)
evals
```

Unit tests run in milliseconds with no LLM or DB. Evals are slow (seconds to tens of seconds per test) and cost tokens. Run unit tests on every change; run evals on features that involve LLM behavior.

---

## Using evals for TDD

The workflow for adding a new feature:

### Step 1 — Write a failing eval first

Before implementing, write an eval that captures the intended behavior. It should fail. This forces you to be specific about what the LLM _must_ do — not just what you hope it does.

For a guardrail:
```python
# This should fail before the guardrail is implemented
async def test_eval_my_new_guardrail(structlog_context):
    steps = await _run_agent(query="...", mock_aoi_df=..., mock_subregion_df=oversize_df)
    assert any("too many" in m.lower() for m in _collect_tool_messages(steps))
```

For a generate_insights behavior:
```python
# This should fail before the chart logic is fixed
async def test_new_chart_behavior(run_insights, judge, my_state):
    result = await run_insights("...", my_state)
    verdict = await judge("...", rubric="- Chart must be stacked bar\n- ...", tool_output=result)
    assert verdict.passed, verdict.comment
```

### Step 2 — Implement the feature

Make the minimal change to pass the eval. Don't gold-plate.

### Step 3 — Lock in the behavior with a unit test

If the feature includes deterministic logic (a limit constant, a validation function, a date parser), add a unit test for it. Unit tests are the regression guard; evals are the behavior spec.

### Step 4 — Check pass rates across branches

```bash
# Run evals on your branch
pytest tests/evals/ -v

# Results land in tests/evals/results/
# Compare pass rates to main
```

---

## Adding eval coverage for a new feature

### When to add a `generate_insights` judge eval

Add one when you change:
- How `generate_insights` selects chart types
- Dataset-specific prompt instructions (`prompt_instructions`, `code_instructions`, `presentation_instructions` in a dataset YAML)
- How data is preprocessed before charting
- Refusal/guardrail behavior inside `generate_insights`

**How:**
1. Add a state fixture to `fixture_data.py` — copy the shape of an existing one, swap in realistic data for your dataset
2. Add the fixture to `conftest.py` (state fixture + `@pytest.fixture` wrapper)
3. Write the test in a new or existing `tests/evals/test_*.py` file using `run_insights` + `judge`
4. Write the rubric as a bullet list of requirements — be specific about chart type, axis labels, data columns, units

### When to add an agent-level routing eval

Add one when you change:
- `pick_aoi` tool behavior (new guardrails, new subregion types, limit changes)
- `pick_dataset` selection logic
- Agent prompt instructions that affect tool call routing
- New end-to-end flows (new tool sequences, new fallback behaviors)

**How:**
1. Identify the mock boundaries — what DB queries or API calls does the new path exercise?
2. Build mock DataFrames that represent the boundary condition you're testing (e.g. exactly at a limit, just over a limit, ambiguous matches)
3. Write the eval in `tests/evals/test_<feature>_evals.py` using `_run_agent`
4. Assert on agent state (`aoi_selection`, `dataset`, `statistics`) and tool messages (guardrail text)

### Mocking reference

| What you want to stub | How |
|---|---|
| PostGIS AOI lookup | `patch("src.agent.tools.pick_aoi.query_aoi_database", AsyncMock(side_effect=...))` |
| PostGIS subregion lookup | `patch("src.agent.tools.pick_aoi.query_subregion_database", AsyncMock(side_effect=...))` |
| Dataset RAG | `patch("src.agent.tools.pick_dataset.rag_candidate_datasets", AsyncMock(side_effect=...))` |
| Analytics API | `patch.object(data_pull_orchestrator, "pull_data", AsyncMock(return_value=DataPullResult(...)))` |

> **Important:** Do not patch `src.agent.tools.pull_data.pull_data` (the tool itself). The LangGraph graph captures tool references at compile time, so the patch won't take effect. Patch `data_pull_orchestrator.pull_data` instead — it's a method on the global singleton that the tool calls at runtime.

### Rubric writing tips (for judge evals)

- List each requirement as a short, falsifiable statement
- Be specific: "chart type is bar" not "chart looks reasonable"
- Include negative cases: "does not include non-forested land in the total"
- One requirement per line — the judge grades each independently, which makes failures easy to diagnose

### Infrastructure boilerplate

Every eval test file needs these no-op fixtures to suppress DB setup from the root conftest:

```python
@pytest.fixture(scope="function", autouse=True)
def test_db(): pass

@pytest.fixture(scope="function", autouse=True)
def test_db_session(): pass

@pytest.fixture(scope="function", autouse=True)
def test_db_pool(): pass
```

And set the asyncio loop scope at the module level:

```python
pytestmark = pytest.mark.asyncio(loop_scope="session")
```

The `tests/evals/conftest.py` handles LLM client reset for the eval session. You don't need to add `reset_google_clients` to individual test files.
