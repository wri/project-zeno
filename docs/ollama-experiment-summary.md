# Running Zeno on Ollama Cloud — Experiment Summary

**Branch:** [`ollama-experiments`](https://github.com/wri/project-zeno/tree/ollama-experiments) · **Status:** working prototype, not yet production-hardened · ~3 min read

## TL;DR

- The full Zeno agent runs end-to-end on **Ollama Cloud** open models — orchestration, geocoding, dataset selection, and code-driven insights — with **no Gemini in the chat path** (only the dataset RAG embeddings still use Gemini).
- Open models are reliable enough **once the prompts/schemas tolerate them** — most of the work was robustness plumbing, not model swapping.
- We also replaced Gemini's managed code sandbox with a **pure-Python sandbox (no Docker)** that provably blocks network, exec, and secret access.
- **Deployable to internal/trusted use today.** The remaining gate for public/untrusted traffic is **validation + ops** (run an eval suite, measure the upstream), *not* security or missing capability — the code-execution security blocker is built and tested.

## What we changed

1. **Ollama Cloud integration** — added `ChatOllama` models to the model registry (bearer-key auth against `https://ollama.com`), selectable via the existing `MODEL` / `SMALL_MODEL` / `CODING_MODEL` env vars.
2. **A provider-agnostic structured-output helper** — forces the tool call but accepts either a tool call *or* JSON in message content, with a self-correcting retry. Open models often emit JSON in content or drop fields; this absorbs that.
3. **A local code executor** (smolagents, in-process) to replace Gemini's native code execution, then a **sandboxed subprocess executor** for safety.
4. **Schema/prompt robustness** — relaxed non-essential required fields and showed the coding model the real dataframe schema + sample rows so it stops guessing column names.

## Final model roles

| Role | Model | Why |
|---|---|---|
| Orchestrator (`MODEL`) | `gpt-oss:120b` | Solid tool-calling driver |
| Small model (`SMALL_MODEL`) | **`gemma4:31b`** | Best end-to-end: Gemini-level geocoder calibration **and** reliable dataset selection; smaller/faster |
| Coding model (`CODING_MODEL`) | `qwen3-coder:480b` (fallback `gpt-oss`) | Writes the analysis code in the executor |

## Key findings

- **No single open model wins on raw benchmarks — test the whole pipeline.** `nemotron` looked best on the hardest dataset task in isolation but *over-sets the geocoder's `subregion`*, which breaks AOI lookup (the very first step). `gemma4:31b` won on the **end-to-end** path.
- **The blocker is usually the schema, not the model.** Deeply-nested required fields (e.g. an explanatory `reason`) made every open model fail validation while picking the right answer. Relaxing those fields is model-agnostic and fixed it.
- **Ground the coding model in the data.** It was writing defensive code that `raise`d when a guessed `date` column didn't exist. Showing real columns/dtypes/sample rows up front removed the guessing.
- **Tier gate:** the strongest models (`qwen3.5`, `glm-5.x`, `deepseek-v4`, `kimi-k2.x`) require a **paid Ollama subscription**; `gemma4` is the best of the free-tier-accessible set.

## The code executor & the sandbox

Three executors live behind one factory (`CODE_EXECUTOR`):

| Mode | What it is | Use for |
|---|---|---|
| `gemini` | Google's managed sandbox | Fallback / parity |
| `local` | smolagents, **in-process** | Dev / trusted input only |
| `sandboxed` | locked-down **subprocess** | Untrusted input — **no Docker needed** |

The **`sandboxed`** executor runs each generated code block in a separate Python process with: a scrubbed env (no keys in the process), an empty temp cwd, `setrlimit` CPU/file caps, and a **seccomp syscall filter** (Linux) blocking network, `execve`, and `fork`. Tests prove that network egress, shell/exec, and reading the parent's secret env are all blocked, while pandas/numpy compute still works.

## Is it deployable?

These are **two independent axes** — keep them separate when planning follow-up
work. Security is largely *built*; reliability/ops is *unmeasured*.

**Axis 1 — Security (code execution): mostly solved.**
The headline risk (LLM-generated code running in-process with our secrets) is
**built and tested** — `CODE_EXECUTOR=sandboxed` blocks network, exec, and
secret-env access. This is no longer the blocker.
Residuals (only matter for hostile multi-tenant): seccomp is Linux-only;
fork-bomb DoS is still possible; and only `generate_insights` is sandboxed — the
orchestrator/subagent paths (DB + API calls) carry the usual agent prompt-
injection risk, same as today's Gemini setup.

**Axis 2 — Reliability + ops: not yet measured (the real remaining gate).**
This is a *verification* gap, not a *build* gap. We have no eval suite — both
failure modes we found were caught by luck during manual testing — and Ollama
Cloud's free-tier limits / latency / cost / SLA are unquantified. Until these are
measured we don't know the real success rate or whether the upstream holds up.

| Target | Security | Reliability/Ops | Verdict |
|---|---|---|---|
| Local / dev | n/a | n/a | ✅ As-is |
| Internal, trusted, single-tenant | ✅ `local` or `sandboxed` | acceptable on faith | ✅ Go now |
| Public / untrusted, multi-tenant | ✅ `sandboxed` (+ close fork-bomb/Linux residuals) | ❌ **needs eval suite + measured Ollama limits** | ⏳ Gated on Axis 2, not Axis 1 |

## How to run

```env
MODEL=gpt-oss
SMALL_MODEL=gemma4
CODING_MODEL=qwen3-coder
CODE_EXECUTOR=sandboxed   # or "local" for dev
OLLAMA_API_KEY=<key from ollama.com/settings/keys>
```

## Evals (to fill in)

No automated eval suite yet — reliability so far is anecdotal (a handful of live
runs). Record structured results here as we run them.

```text
Setup
  date:           <yyyy-mm-dd>
  models:         MODEL=<...>  SMALL_MODEL=<...>  CODING_MODEL=<...>
  executor:       CODE_EXECUTOR=<local|sandboxed|gemini>
  dataset/suite:  <eval set name + size>
  baseline:       <e.g. gemini-3-flash on same suite>

Results (vs baseline)
  geocoder accuracy:        __ / __   ( __% )   baseline: __%
  dataset selection acc.:   __ / __   ( __% )   baseline: __%
  insight/chart valid:      __ / __   ( __% )   baseline: __%
  end-to-end task success:  __ / __   ( __% )   baseline: __%
  median latency / query:   __ s                baseline: __ s
  cost / 1k queries:        $__                 baseline: $__

Failure modes observed
  - <model>: <what broke> -> <fix or status>

Verdict
  - <ship / iterate / blocked-by> ...
```

## Residual risks / next steps

- **Sandbox is Linux-only** for the syscall filter (macOS dev falls back to env-scrub + rlimits; network not blocked). Fork-bomb DoS is still possible (bounded by CPU limit + per-block timeout) — left open to avoid breaking pandas threads.
- **Still depends on Gemini** for dataset RAG embeddings (`GOOGLE_API_KEY` required).
- **No automated eval** of the Ollama path yet — reliability is validated by a handful of runs, not a suite. This is the main gap before trusting it in production.
- **Free-tier limits/latency/cost** of Ollama Cloud are unquantified.

## Code

Branch [`ollama-experiments`](https://github.com/wri/project-zeno/tree/ollama-experiments) on `wri/project-zeno`. Key commits: [`c9d7858`](https://github.com/wri/project-zeno/commit/c9d7858) (gemma4 small model), [`b615a19`](https://github.com/wri/project-zeno/commit/b615a19) (schema preview for the executor), [`d1e6c49`](https://github.com/wri/project-zeno/commit/d1e6c49) (pure-Python sandbox + tests). Sandbox lives in `src/agent/subagents/analyst/code_executors/` (`subprocess_executor.py`, `_sandbox_worker.py`); tests in `tests/tools/test_sandbox_executor.py`.
