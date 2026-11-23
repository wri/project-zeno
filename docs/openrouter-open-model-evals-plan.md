# OpenRouter backend and open-model GOLD sweep — plan

Two connected pieces of work:

1. Add OpenRouter as a model backend in `src/agent/llms.py`.
2. Run the [gnw-gold-evals](https://github.com/wri/gnw-gold-evals) GOLD set
   through the agent with 8 open-weight models, and compare the results.

Piece 2 needs piece 1. Do them in order.

---

## 1. Current state

`src/agent/llms.py` holds one module-level `ChatX` instance per model. A
`MODEL_REGISTRY` dict maps a short name (`sonnet`, `gemini-flash`) to an
instance. Three env vars select from the registry:

| env var | reads | used by |
|---|---|---|
| `MODEL` | registry name | `create_agent(model=...)` in `src/agent/graph.py:302` |
| `SMALL_MODEL` | registry name | 8 call sites, all `with_structured_output` |
| `FALLBACK_MODELS` | comma-separated registry names | `ModelFallbackMiddleware` |

A fourth var is separate and does **not** go through the registry:

| env var | reads | used by |
|---|---|---|
| `CODING_MODEL` | full Google model ID | `GeminiCodeExecutor`, `src/agent/subagents/analyst/code_executors/gemini_executor.py:38` |

`MODEL`, `SMALL_MODEL` and `FALLBACK_MODELS` resolve at **import time**
(`llms.py:123-129`). A change needs an API restart.

### What blocks open models

**The analyst subagent cannot use an open model.** `generate_insights`
sends the pulled dataframes to Gemini and lets Gemini run Python in its
own server-side sandbox (`gemini_executor.py`, `types.ToolCodeExecution`).
No OpenRouter model gives you a code sandbox. The repo has no local
executor — `code_executors/` holds only the Gemini one.

Result: this plan keeps `CODING_MODEL` on Gemini for all runs. The sweep
therefore measures **orchestration**, not analysis. Section 3 says what
that means for the scores.

**`with_structured_output` runs on the small model at 8 call sites.**
Weak models fail here in a way that breaks tools, not just answers. The
sweep keeps `SMALL_MODEL` on Gemini Flash for the same reason, so that a
failure points at the orchestrator and not at a structured-output error
somewhere else.

---

## 2. Add the OpenRouter backend

OpenRouter serves an OpenAI-compatible API. `langchain-openai==1.1.12` is
already a dependency, so no new package is needed.

### 2.1 Settings

Add to `src/agent/config.py`:

```python
openrouter_models: str = Field(default="", alias="OPENROUTER_MODELS")
openrouter_base_url: str = Field(
    default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
)
openrouter_max_tokens: int = Field(default=16_384, alias="OPENROUTER_MAX_TOKENS")
```

`OPENROUTER_API_KEY` stays a plain env var, read by `ChatOpenAI`.

`OPENROUTER_MODELS` is a comma-separated list of OpenRouter model IDs, for
example:

```
OPENROUTER_MODELS=deepseek/deepseek-v4-pro,z-ai/glm-5.3,openai/gpt-oss-120b
```

### 2.2 Registry entries

In `src/agent/llms.py`, build one `ChatOpenAI` per listed ID and register
it under a slug. Derive the slug from the ID so no second list is needed:
`deepseek/deepseek-v4-pro` becomes `or:deepseek-v4-pro`. The `or:` prefix
keeps open-model slugs apart from the hand-written ones.

```python
def _openrouter_slug(model_id: str) -> str:
    """`vendor/name` -> `or:name`. Slugs address the registry; IDs address
    OpenRouter."""
    return "or:" + model_id.split("/", 1)[-1]


def _build_openrouter_models() -> dict[str, BaseChatModel]:
    raw = AgentSettings.openrouter_models.strip()
    if not raw:
        return {}
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise ValueError("OPENROUTER_MODELS is set but OPENROUTER_API_KEY is not")
    models = {}
    for model_id in (part.strip() for part in raw.split(",")):
        if not model_id:
            continue
        models[_openrouter_slug(model_id)] = ChatOpenAI(
            model=model_id,
            base_url=AgentSettings.openrouter_base_url,
            temperature=0,
            max_tokens=AgentSettings.openrouter_max_tokens,
            max_retries=AgentSettings.llm_max_retries,
            timeout=300,
            default_headers={
                # OpenRouter attribution headers; they show the run in the
                # OpenRouter dashboard and are otherwise inert.
                "HTTP-Referer": "https://github.com/wri/project-zeno",
                "X-Title": "project-zeno",
            },
        )
    return models


MODEL_REGISTRY = {
    "sonnet": SONNET,
    ...
    **_build_openrouter_models(),
}
```

Registry lookup, `get_model`, `get_small_model` and `get_fallback_models`
need no change. They already raise a clear error on an unknown name and
already list the valid ones.

### 2.3 Points to check while implementing

- **`max_tokens` is required.** The Anthropic entries set it because the
  provider caps it. Open models mostly do not cap it, but a missing value
  lets a looping model burn the whole context. 16k is enough for this
  agent's turns.
- **`temperature=0`** matches every other registry entry. Some reasoning
  models reject it; if one does, drop the field for that model rather than
  for all of them.
- **`/api/metadata`** reports `current_model.model`. `ChatOpenAI` exposes
  `.model`, so the endpoint keeps working. Verified against the installed
  version.
- **Structured output.** `with_structured_output` uses tool calling by
  default. Every model in section 3 reports `tools` and
  `structured_outputs` support. This still needs a live check per model —
  reported support and real behaviour differ.
- **`AVAILABLE_MODELS`** grows with the env var, so the frontend model
  list follows automatically.

### 2.4 Tests

Add `tests/unit/test_openrouter_registry.py`:

- `_openrouter_slug` maps IDs to slugs.
- An empty `OPENROUTER_MODELS` adds nothing to the registry.
- A set `OPENROUTER_MODELS` with no API key raises.
- A two-model list registers two slugs, each a `ChatOpenAI` with the right
  `model` and `base_url`.

Use `monkeypatch` on the settings object and re-run the builder function
directly. Do not reload the module; `llms.py` has import-time side effects.

### 2.5 Docs

- `.env.example`: add `OPENROUTER_API_KEY` and a commented
  `OPENROUTER_MODELS` line with the `or:` slug rule.
- `docs/AGENT_ARCHITECTURE.md`: one paragraph on the backend and on the
  `CODING_MODEL` limit from section 1.

**Deliverable:** one PR, `feat(agent): add openrouter as a model backend`.

---

## 3. Run the GOLD set with open models

### 3.1 How the harness reaches the agent

`gold run` posts to `POST /api/chat`, then reads
`GET /api/threads/{id}/state` and `GET /api/dashboards/{id}`
(`src/goldset/runner/api.py`). `--env local` points it at
`http://localhost:8000`. It sends a bearer token from `API_TOKEN`.

The harness has no model flag, and `/api/chat` takes no model parameter.
`MODEL` resolves at import time. So one model per API process: **set
`MODEL`, start the API, run the set, stop the API, repeat.**

### 3.2 Held constant across all runs

Everything except `MODEL` stays fixed, or the runs are not comparable:

| setting | value | why |
|---|---|---|
| `SMALL_MODEL` | `gemini-flash` | section 1: isolates the orchestrator |
| `CODING_MODEL` | `gemini-3.1-pro-preview` | no open model has a code sandbox |
| `FALLBACK_MODELS` | *empty* | a fallback to Gemini would hide the failure being measured |
| `--ff` | unset (default profile) | matches the current prod baseline; see the gold repo's CLAUDE.md |
| `--cases-dir` | `cases/v2` | the curated set, 104 active cases |
| `--workers` | 4 | lower than the default 10; a local API and free-tier rate limits are the bottleneck |
| `--trials` | see 3.4 | |

`FALLBACK_MODELS=` empty is the one that is easy to forget. The `.env`
default is `gemini-flash,gemini-flash-lite`, which would silently answer
for a broken open model.

`AOI_PICK_AOI_FIXTURES_MODE=replay` in the local `.env` needs no action.
Only `tests/tools/conftest.py` reads it, so it cannot affect an API-served
run. Checked, because a replayed geocoder would have made `aoi_id_match`
measure the fixture and not the model.

### 3.3 Model slate

Eight open-weight models, live on OpenRouter, all reporting tool and
structured-output support. Prices are USD per million tokens,
input/output, read from the OpenRouter model list.

| # | OpenRouter ID | ctx | in/out $ | why it is in |
|---|---|---|---|---|
| 1 | `deepseek/deepseek-v4-pro` | 1.0M | 0.96 / 1.91 | strongest open general model; the reference point |
| 2 | `z-ai/glm-5.3` | 1.3M | 1.40 / 4.40 | GLM series is tuned for agent use |
| 3 | `moonshotai/kimi-k3` | 1.0M | 3.00 / 15.00 | long-horizon tool use; the cost ceiling of the slate |
| 4 | `qwen/qwen3.8-2.4t-a95b` | 1.0M | 2.00 / 6.00 | largest open MoE |
| 5 | `minimax/minimax-m3` | 1.0M | 0.30 / 1.20 | cheap and long-context |
| 6 | `meta-llama/llama-4-maverick` | 1.0M | 0.20 / 0.70 | Llama baseline; no reasoning mode |
| 7 | `openai/gpt-oss-120b` | 131k | 0.04 / 0.17 | cheapest credible option; tests the context limit |
| 8 | `google/gemma-4-31b-it` | 262k | 0.09 / 0.34 | small-model floor; shows where the prompt gets too hard |

Add `z-ai/glm-5.3-flash` and `mistralai/mistral-small-2603` if a tenth and
eleventh are wanted; both are cheap.

Excluded on purpose: `qwen/*-max`, `qwen/*-plus` and
`mistralai/mistral-medium-*` are proprietary API models, not open weights.
Also excluded: every `:free` variant. They report no structured-output
support and they rate-limit hard.

Also record the two current production models, `gemini` and `sonnet`,
under the same conditions. They are the yardstick.

### 3.3a The slate is not size-controlled

Sizes, from the OpenRouter model descriptions on 2026-09-07 (recorded with
provenance in `.sweep-logs/model_meta.json`):

| model | total | active | arch |
|---|---|---|---|
| `moonshotai/kimi-k3` | 2.8T | not stated | MoE |
| `qwen/qwen3.8-2.4t-a95b` | 2.4T | 95B | MoE |
| `deepseek/deepseek-v4-pro` | 1.6T | 49B | MoE |
| `meta-llama/llama-4-maverick` | not stated | 17B | MoE, 128 experts |
| `openai/gpt-oss-120b` | 117B | 5.1B | MoE |
| `google/gemma-4-31b-it` | 30.7B | 30.7B | dense |
| `z-ai/glm-5.3` | not stated | not stated | — |
| `minimax/minimax-m3` | not stated | not stated | — |

That is about a 90x spread in total parameters and 20x in active
parameters, and two providers publish no figure at all. So this slate
answers "which open model on OpenRouter serves this agent best today",
**not** "how does agent capability scale with model size". Do not read the
ranking as a size curve.

Two consequences for the write-up:

- Size did not predict score in the pilot. `kimi-k3` is the largest model
  in the slate and scored the worst of the frontier group; `deepseek-v4-pro`
  is smaller than both `kimi-k3` and `qwen3.8` and scored the best.
- Active parameters, not total, drive serving cost and latency. Compare
  `gpt-oss-120b` (5.1B active) against the 49-95B-active models on the
  latency columns, not on total size.

### 3.3b Latency is a first-class result, not a footnote

Report `p50`, `p90` and `max` per case, and the count over the run's slow
threshold. p50 alone hides the thing that matters operationally: in the
pilot `glm-5.3` matched `deepseek-v4-pro` exactly on accuracy but carried a
367s worst case against deepseek's 146s, which is the difference between a
usable and an unusable interactive answer.

Two caveats on the numbers:

- Every model's latency includes the shared Gemini code-execution step, so
  the figures are agent-response latency, not model latency. The shared
  component does not vary across models, so comparisons hold.
- `gemini` was the fastest model in the pilot at every percentile and had
  the tightest spread. Moving to an open model costs latency even where it
  buys accuracy.

### 3.4 Two-stage run, because a full sweep is too big

A full official run is 104 cases × 3 trials. The gold repo's CLAUDE.md is
explicit that a regression count needs 3 trials: two trials of the *same*
run report 18-29 spurious regressions, which is more than the 15 real ones
between two different builds. But 3 trials × 8 models is 2,496 agent runs.
Against a single local API that is days, not hours.

So split it:

**Stage 0 — pilot (1 trial, 24 cases, 10 models).** Done. The frozen
case list is `pilot_ids.txt` in the gold-evals checkout: one or two cases
per capability group, 16 groups, 22 of 24 at `status: done`. The list must
stay identical across models or the runs are not comparable. Baselines
`gemini` and `sonnet` run under the same conditions as the yardstick.

**Stage A — screen (1 trial, all 104 cases, 8 models).**
Sorts the models. 832 agent runs. At 4 workers this is roughly 30-60
minutes per model, so about 6 hours end to end plus judge time. Single
trial, so the output is a **ranking and a failure-mode list**, not a
regression count. Report it as such.

**Stage B — confirm (3 trials, top 3 models + `gemini`).**
Only the models that survive stage A. 1,248 agent runs. This is the one
that gives numbers comparable to the committed prod baseline.

Run stage A first, report, then decide on stage B. Do not start stage B
before stage A is read; a model that cannot call tools reliably does not
deserve three trials.

### 3.5 Driver script

Written: `scripts/openrouter_sweep.sh` in the gold-evals checkout, not in
project-zeno — the runs and results belong to the eval repo. Usage:

```bash
CASE_IDS=pilot_ids.txt bash scripts/openrouter_sweep.sh <trials> <workers> <model>...
```

It reads `API_TOKEN`, `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY` from
project-zeno's `.env`, and appends one row per model to
`.sweep-logs/sweep-summary.tsv` with the run ID, the OpenRouter spend for
that window, and the elapsed minutes.

A companion `scripts/compare_models.py` builds the cross-model table. The
ledger has no model field, so it identifies runs by their `build` label,
which the driver writes as `or-sweep <model>`. It warns on a mixed
`caseset_version` or a mixed trial count, because neither is comparable.

For each model, the loop must:

1. Write `MODEL=or:<slug>` into the API process environment.
2. Start `uvicorn src.api.app:app --port 8000` from the project-zeno
   checkout, **without** `--reload`. Reload re-imports `llms.py` and can
   pick up a stale value.
3. Poll `http://localhost:8000/api/metadata` until it answers, then assert
   that `model.model_name` equals the expected OpenRouter ID. This is the
   guard against a run silently using the previous model. It is the single
   most important step in the script.
4. Run `uv run gold run --env local --build "or-sweep <model-id>"
   --trials 1 --workers 4`.
5. Stop the API. Wait for the port to free.
6. Record the run ID and the OpenRouter spend for the window.

Do not stop a stuck sweep with `pkill -f openrouter_sweep.sh`. The pattern
matches the command line of the shell that runs it, so the command kills
itself and prints nothing. Use a bracket in the pattern
(`pkill -f 'openrouter_swee[p]'`) so the pattern text differs from what it
matches.

The `--build` label is the only place the model name is recorded. The
ledger has no model field. Use the exact OpenRouter ID as the label, or
the results cannot be attributed afterwards.

### 3.6 Reading the results

Per the gold repo, for each run: `tools/report_run.py`,
`tools/render_html.py`, `tools/flakiness.py`. Then `tools/diff_runs.py`
between each open model and the `gemini` run from the same sweep — never
against a committed staging or prod run. A local API, a 1-trial run and a
different `caseset` all break comparability.

Expected reading, given the constraints in section 3.2:

- **Retrieval and scope buckets are the real signal.** These are the
  orchestrator's job: pick the AOI, pick the dataset, extract dates, decide
  how much work to do.
- **Analysis and output buckets are partly Gemini's score,** because the
  chart data comes from `GeminiCodeExecutor`. An open model still has to
  call `generate_insights` with the right arguments, so a failure there is
  real, but a pass is not fully the open model's.
- **Explanation is mixed.** The prose is the orchestrator's, the numbers in
  it are not.

Say this in the write-up. A table of bucket scores without it invites the
wrong conclusion.

### 3.6a A confounder found in the first run: the `nudge` channel

The gemini baseline errored on `mt-001` with a 500 from the local API:

```
langgraph.errors.InvalidUpdateError: At key 'nudge':
Can receive only one value per step.
```

`src/agent/state.py:108` declares `nudge: Nudge` as a plain channel, and
its comment says "Last-write-wins, no reducer". A plain LangGraph channel
does not do last-write-wins on two writes in the *same* step — it raises.
Four tools write the key: `send_nudge`, `pick_aoi` and `pick_dataset`
(twice). So when the model puts two of those in one batch of tool calls,
the request 500s **and** the thread's state stays unreadable afterwards,
so the harness cannot score the row either.

This is an agent bug, not a harness or OpenRouter problem, and it predates
this work. It matters here because **models differ in how aggressively they
batch tool calls**, so it will hit each model at a different rate and
confound the comparison. Count `nudge` errors per model and report them
apart from capability failures.

The fix is a reducer that implements what the comment already claims:

```python
def _take_last(_current: Nudge, incoming: Nudge) -> Nudge:
    return incoming

nudge: Annotated[Nudge, _take_last]
```

Do not apply it mid-sweep. Changing agent behaviour between models makes
the runs non-comparable; land it separately, then re-baseline.

### 3.6b Distinguish a capability failure from a tool-call failure

`or:llama-4-maverick` scored 2 of 24 (8%), with buckets at 19-52%. That is
not "worse at the task"; it is a different failure. Read the evidence
before reporting the number:

- The judge reasons say the answer *was* the call: "the actual insight is a
  function call to `pick_aoi()` with a location parameter". The model wrote
  the tool call as prose in the assistant message instead of emitting a
  structured `tool_calls` field, so the agent never ran it.
- Tool executions in the API log confirm a chain that stops early:
  `pick_aoi` 25, `pick_dataset` 3, `pull_data` 3, against
  `or:deepseek-v4-pro`'s 104 / 19 / 18 on the same cases. So the model can
  emit one structured call and then loses the format.
- Its p50 was 14s, the fastest in the sweep. It failed fast rather than
  working slowly, which is the signature of this failure and not of a hard
  question.

**Resolved: it is the model, not the route.** OpenRouter routes a model
across several providers, and two of the five serving
`meta-llama/llama-4-maverick` (DeepInfra, Novita) support no tool calling
at all — they are also the cheap high-context ones that default routing
favours, so the suspicion was reasonable. Re-running pinned to the three
tool-capable providers (`google-vertex`, `parasail`, `digitalocean`) moved
the score from 2/24 to 4/24, which is one or two rows on a single-trial
24-case run and inside noise. The decisive evidence is that the behaviour
did not change at all:

| | unpinned | pinned |
|---|---|---|
| `pick_aoi` executions | 25 | 21 |
| `pick_dataset` | 3 | 3 |
| `pull_data` | 3 | 3 |
| retrieval bucket | 38% | 38% |
| scope bucket | 19% | 19% |

So the conclusion stands as a capability result: this model cannot chain
the agent's tool calls, on any available provider. Provider pinning is
still worth keeping (see below) — it just was not the cause here.

**Keep the pinning support regardless.** Any OpenRouter model in
production needs it: routing is dynamic, providers differ in tool support,
and a route change can silently break tool calling with no error and no
code change on this side. `OPENROUTER_MODELS` accepts
`vendor/model@provider1+provider2`, which sets
`extra_body={"provider": {"only": [...], "allow_fallbacks": True}}` — so
fallbacks stay on but can never leave the pinned set.

The general rule for the write-up: before ranking a model low, check
whether its tools ran at all. A row of zeros across `aoi_id_match`,
`dataset_id_match` and `data_pull_exists` at a *fast* latency means the
plumbing failed, not the reasoning.

### 3.7 Prerequisites to confirm before starting

- `OPENROUTER_API_KEY` with credit. The user has one in another checkout.
- Section 2 merged, or at least on a local branch.
- Local API healthy on the default profile: `make up`, then the API on
  port 8010, then `gold run --api-base-url http://127.0.0.1:8010 --id 1-002
  --id 1-012` with `MODEL=gemini`. This proves the DB, the dataset index and
  the insights index before any open model is blamed for their absence.
  Use a `status: done` case. Do **not** use `1-030` — the gold README shows
  it as a CLI example, but it is `status: todo` and fails by design (its
  `status_reason` reads "Expecting SBTN analysis but using the Blog skill").
- `API_TOKEN` valid against the *local* DB. The token must resolve through
  `fetch_user_from_rw_api`, so either a Resource Watch token or a
  `zeno-machine-user:` token that the local DB holds.
- A rough cost ceiling agreed for stage A.

### 3.8 Cost — measured, not estimated

Measured on `or:deepseek-v4-pro`, case 1-012, one trial: **$0.0074 and
about one minute**. The first estimate in this plan assumed 150k input
tokens per case and was roughly 20x too high. A GOLD case is a handful of
turns, and the tool outputs stay small.

Scaled from the measured figure, per model, per 24-case pilot trial:

| model | in/out $/M | est. pilot cost |
|---|---|---|
| `openai/gpt-oss-120b` | 0.04 / 0.17 | ~$0.01 |
| `google/gemma-4-31b-it` | 0.09 / 0.34 | ~$0.02 |
| `meta-llama/llama-4-maverick` | 0.20 / 0.70 | ~$0.04 |
| `minimax/minimax-m3` | 0.30 / 1.20 | ~$0.06 |
| `deepseek/deepseek-v4-pro` | 0.96 / 1.91 | $0.18 (measured rate) |
| `z-ai/glm-5.3` | 1.40 / 4.40 | ~$0.30 |
| `qwen/qwen3.8-2.4t-a95b` | 2.00 / 6.00 | ~$0.42 |
| `moonshotai/kimi-k3` | 3.00 / 15.00 | ~$0.90 |

Pilot total across the eight: roughly **$2**. A full 104-case, 3-trial
stage B across four models is therefore about **$25-30**, not the
$120-150 first written here. Cost is not a reason to cut the slate.

The real budget is **wall-clock time**: about one minute per case at one
worker. At 4 workers a 24-case pilot is 8-12 minutes per model, so 10
models is under two hours. A 104-case 3-trial run is 312 agent calls per
model, or roughly 1.5-2 hours each.

Gemini still bills separately for `SMALL_MODEL` and `CODING_MODEL` on
every run, and Haiku bills for the judge. Neither varies across models,
so neither affects the comparison.

---

## 4. Order of work

1. Section 2, including the tests and `.env.example`. One PR.
2. Section 3.7 prerequisites. Stop here if the local API is not healthy.
3. One open model, one case, verbose. Confirms the plumbing.
4. One open model, all 104 cases, 1 trial. Confirms the timing and the cost
   model.
5. Stage A for the rest.
6. Report. Then decide on stage B.
