# OpenRouter models in place of Gemini Flash: benchmark results (2026-11-18)

> **Do not merge.** This document and the OpenRouter backend are for visibility. They record an evaluation, not a product change.

## Summary

| | Gemini Flash (`424c04e2`) | DeepSeek V4.1 Flash | Muse Ember |
|---|---|---|---|
| **North Star** (right on most of 3 attempts, 269 questions) | 80.7% (217) | 80.7% (217) | 78.0% (209 of 268) |
| Right every time | 69.9% | 69.1% | 63.8% |
| Latency, median / 90th percentile (`stream_s`) | 16.6 s / 51.6 s | 27.0 s / 67.0 s | 20.7 s / 47.7 s |
| Cost for each question, orchestrator and subagents | more than $0.0093 (orchestrator only) | $0.0048 | $0.0059 |

- DeepSeek V4.1 Flash has the same accuracy as Gemini Flash. It is about 10 s slower at the median. It costs less than half.
- Muse Ember is 2.7 points lower than Gemini Flash and DeepSeek (not significant, McNemar p = 0.27). It is faster than DeepSeek and costs about the same. Most of its extra failures are in retrieval: it stops without a data pull on multi-area comparisons and sLUC questions. In 3 attempts it called the model 468 to 617 times in a loop.
- No model smaller than DeepSeek V4.1 Flash, other than Muse Ember, came near the reference on the screen (section 2).
- The code executor (`generate_insights`) stays on Gemini in all runs. It is not in the cost numbers.

## Setup

- **Agent:** PR #911 (`feat/concise-agent`), profile `ff=concise`, local API. DeepSeek ran on `9b36fdc8`. Muse Ember ran on `11ceec0f`, which has the same code as the Gemini reference `424c04e2` (the later commits change only docs). These hashes are from before `feat/concise-agent` was rebased on 2026-11-18. After the rebase, `424c04e2` is `387b68fc`.
- **Provider routing:** the screen and the Muse Ember run used `provider.require_parameters`. The DeepSeek run did not, but it had no tool-call failures.
- **Models:** MODEL and SMALL_MODEL are the candidate, through OpenRouter. FALLBACK_MODELS and SMALL_FALLBACK_MODELS are empty, so Gemini cannot answer for a candidate. CODING_MODEL stays on Gemini, because only the Gemini code executor has a sandbox.
- **OpenRouter backend:** this branch. `OPENROUTER_MODELS` registers one `ChatOpenAI` for each OpenRouter ID under an `or:` slug (for example `or:muse-ember`). Each request sets `provider.require_parameters`, so OpenRouter sends it only to a provider that supports tool calls and structured output.
- **Harness:** gnw-gold-evals `main` (`e5937ae`) plus the `chart_well_formed` fix `fa337b5` (not pushed), BENCHMARK `2026-draft-5`, 269 questions, 3 attempts, 10 workers.
- **Cost:** the change in the OpenRouter key usage during each run. Other use of the key during a run would be in it. Tokens come from the thread state of each attempt. The thread state records the orchestrator calls, but not the subagent calls or the code executor.

## 1. Full runs

### 1.1 DeepSeek V4.1 Flash

`deepseek/deepseek-v4.1-flash` (284B total, 13B active parameters).

| | Prod (Gemini, default profile) | `3a9075df` (Gemini) | `424c04e2` (Gemini) | DeepSeek |
|---|---|---|---|---|
| **North Star** | 78.4% (211) | 81.4% (219) | 80.7% (217) | **80.7% (217)** |
| Right every time | 65.1% | 69.9% | 69.9% | 69.1% |
| Right at least once | 86.2% | 87.7% | 88.1% | 88.5% |
| Failure modes (scope, retrieval, analysis, explanation) | 2, 31, 7, 18 | 0, 22, 9, 19 | 0, 27, 6, 19 | 1, 27, 8, 16 |
| Attempts with no reply | 1 of 807 | 7 of 807 | 1 of 807 | 2 of 807 |

Against `424c04e2`, DeepSeek gains 22 questions and loses 22 (McNemar p = 1.0). Some losses are not from the model:

- `ch-quant-009`: the DeepSeek run does not have the `424c04e2` deforestation fix.
- `chart_integrity` (mis-joined record sets): `ch-comp-076`, `ch-quant-171`, `ch-trend-037`. The Gemini runs do not show this failure.
- `ch-dataset-171` calls `search_blogs` on 3 of 3 attempts.

**Latency.** Median 27.0 s, 90th percentile 67.0 s. The `424c04e2` run in the same hour, on the same local database: 16.6 s and 51.6 s.

There was no throttling. The OpenRouter generation records of all 3,441 orchestrator calls show 13 responses with status 429 (all from the provider Wafer) and 1 with 504. In each of these 14 calls, OpenRouter sent the request again to a different provider, and that provider answered. The time to the first token (median 0.6 s) and the generation time (median 1.5 to 2.1 s) did not change from the start to the end of the run.

DeepSeek is slower because each model call is slower. From the checkpoint timestamps, a DeepSeek orchestrator call takes 2.2 s (median), against 1.0 s for Gemini Flash. With 5 calls for each attempt, that is about 5 s more for each question. DeepSeek writes more output for each call (about 180 tokens, half of them thinking, against about 80 for Gemini). The speed also depends on the provider: OpenRouter used 23 providers, with a median generation time from 0.7 s (Together) and 0.8 s (Crusoe) to 3.6 s (OpenInference). Pinning fast providers can make DeepSeek faster.

The first questions of a run are faster than the next ones in all runs, also with Gemini. The cause is the order of the questions: from minute 5 to minute 20 the harness runs questions with slow analytics requests, and the tool time goes up. The model time does not change.

**Cost.** The OpenRouter key spent $3.86 for 807 attempts: $0.0048 for each question. The generation records give the orchestrator cost: $1.63, or $0.0020 for each attempt. The subagents cost the remaining $2.23. Orchestrator tokens for each attempt (medians, from the thread state):

| | Gemini Flash (3 runs) | DeepSeek V4.1 Flash |
|---|---|---|
| Model calls | 5 | 5 |
| Input, not cached | 14,400 | 5,500 |
| Input, cache read | 12,000 (45%) | 21,500 (74%) |
| Output | 380 to 400 | 1,012 (478 thinking) |
| All tokens | 28,300 | 32,200 |
| Orchestrator cost for each attempt | $0.0093 | $0.0020 (OpenRouter generation records) |

DeepSeek uses about 14% more tokens. All its calls cost about half of the Gemini orchestrator calls alone. The Gemini thread states record 0 thinking tokens; if Gemini bills thinking that the state does not record, the Gemini cost is higher.

### 1.2 Muse Ember

`meta/muse-ember`. Meta does not publish its size. It is a hosted model, not open weights. Both providers (Meta and Google) have the same price: $0.10/M input, $0.004/M cache read, $0.50/M output.

| | Prod (Gemini, default profile) | `424c04e2` (Gemini) | DeepSeek | Muse Ember |
|---|---|---|---|---|
| **North Star** | 78.4% (211) | 80.7% (217) | 80.7% (217) | **78.0% (209 of 268)** |
| Right every time | 65.1% | 69.9% | 69.1% | 63.8% |
| Right at least once | 86.2% | 88.1% | 88.5% | 82.8% |
| Consistency | 175 of 211 | 188 of 217 | 186 of 217 | 171 of 209 |
| Failure modes (scope, retrieval, analysis, explanation) | 2, 31, 7, 18 | 0, 27, 6, 19 | 1, 27, 8, 16 | 1, 37, 6, 15 |
| Attempts with no reply | 1 of 807 | 1 of 807 | 2 of 807 | 3 of 807 |

The harness could not score `ch-causal-029` on any attempt, so the denominator is 268.

| Type | Prod | `424c04e2` (Gemini) | DeepSeek | Muse Ember |
|---|---|---|---|---|
| Quantification | 70 of 84 | 73 | 71 | 71 |
| Comparison | 46 of 57 | 49 | 51 | 44 |
| Monitoring | 30 of 41 | 30 | 31 | 29 |
| Causal | 20 of 31 | 19 | 18 | 20 |
| Trend | 20 of 23 | 21 | 20 | 20 |
| Refusal | 5 of 9 | 7 | 7 | 8 |
| Geospatial | 8 of 9 | 7 | 8 | 7 |
| Portfolio | 6 of 9 | 6 | 6 | 6 |
| Dataset | 6 of 6 | 5 | 5 | 4 |

Against `424c04e2`, Muse Ember gains 16 questions and loses 24 (McNemar p = 0.27). Against DeepSeek, the same counts (p = 0.27). The difference is not significant at this sample size, but the losses have a pattern:

- **Retrieval (13 of 24).** The model answers without a data pull. Most are comparisons of several areas (`ch-comp-151` Riau, Jambi and West Kalimantan; `ch-comp-155` Sabah and Sarawak; `ch-aoi-090` Pará and Paraná; `ch-comp-174`) and sLUC emission questions (`ch-quant-033`, `ch-comp-038`, `ch-trend-037`).
- **Explanation (7).** The reply has the figures but not the required text, for example `ch-quant-193` (alerts through an API) and `ch-quant-176` (share of Spain).
- Comparison is the weakest type: 44, against 49 for Gemini and 51 for DeepSeek.

**Loops.** Three attempts called the model 468, 590 and 617 times: "Go to 9.5N, 79.5W", "Describe the pattern of deforestation in the Amazon" and "Were there any alerts within 10 km of this mill at -1.25, 101.45". They used 106M of the 121M cache-read tokens of the run, about $0.70. DeepSeek and Gemini have no such loops. A limit on model calls for each turn would stop this.

**Latency.** Median 20.7 s, 90th percentile 47.7 s. This is faster than DeepSeek (27.0 s, 67.0 s) and between the two Gemini figures (16.6 s, 51.6 s). The Muse run was at 13:00, not in the same hour as the other runs. An orchestrator call takes 1.4 s (median, checkpoint timestamps), between Gemini (1.0 s) and DeepSeek (2.2 s). A sample of 994 generation records shows no throttling (one 504, answered by the second provider).

**Cost.** The OpenRouter key spent $4.75 for 807 attempts: $0.0059 for each question, about 20% more than DeepSeek ($0.0048). Muse Ember has one price, so the split is known: the orchestrator calls cost $2.11 (thread state tokens), and the subagents cost about $2.64. Without the 3 loops, the cost is about $0.0050 for each question.

| Orchestrator, medians for each attempt | Gemini Flash | DeepSeek V4.1 Flash | Muse Ember |
|---|---|---|---|
| Model calls | 5 | 5 | 5 |
| Input, not cached | 14,400 | 5,500 | 5,100 |
| Input, cache read | 12,000 | 21,500 | 17,200 |
| Output | 380 to 400 | 1,012 (478 thinking) | 1,797 (1,278 thinking) |
| All tokens | 28,300 | 32,200 | 33,400 |
| Orchestrator cost for each attempt | $0.0093 | $0.0015 to $0.0043 | $0.0017 (mean $0.0035, with the loops) |

## 2. Model screen

The screen looks for a model smaller than DeepSeek V4.1 Flash that is as good. It used 30 BENCHMARK questions, 1 attempt each. The 30 questions cover all question types and datasets. DeepSeek and Gemini are right on all 3 attempts of each of them in the full runs, so the reference is 30 of 30, and a miss is a capability gap, not noise. One attempt on 30 questions has a noise of about 1 to 2 questions.

| Model | Size (total / active) | Right (of 30) | No reply | Median / p90 | Cost for each question | Main failure |
|---|---|---|---|---|---|---|
| *DeepSeek V4.1 Flash (reference)* | 284B / 13B | *30* | | *23.8 s / 65.2 s* | *$0.0048* | |
| *Gemini Flash (reference)* | not published | *30* | | *17.8 s / 38.2 s* | | |
| `meta/muse-ember` | not published | **27** | 0 | 22.9 s / 46.5 s | $0.0054 | none |
| `qwen/qwen3.6-35b-a3b` | 35B / 3B | 26 | 0 | 68.0 s / 115.8 s | $0.012 | slow, long thinking |
| `qwen/qwen3.8-27b` | 27B dense | 26 | 1 | 62.2 s / 182.9 s | $0.022 | slow, long thinking |
| `meta/muse-glimmer-30b` | 30B dense | 22 | 1 | 66.1 s / 108.3 s | $0.027 | slow |
| `nvidia/nemotron-3.5-lightning` | 30B / 3B | 19 | 0 | 39.7 s / 168.6 s | $0.0096 | repeats `pull_data` (126 calls) |
| `mistralai/ministral-14b-2512` | 14B dense | 17 | 0 | 15.9 s / 43.2 s | $0.0038 | retrieval |
| `openai/gpt-oss-120b` | 117B / 5.1B | 16 | 0 | 15.3 s / 79.7 s | $0.0039 | retrieval |
| `mistralai/ministral-8b-2512` | 8B dense | 15 | 0 | 18.5 s / 39.9 s | $0.0028 | all stages |
| `z-ai/glm-4.7-flash` | about 30B | 14 | 13 | 156.6 s / 191.9 s | $0.0031 | no reply, slow |
| `google/gemma-4-31b-it` | 31B dense | 13 | 7 | 14.1 s / 375.4 s | $0.021 | repeats `pick_aoi` (293 calls) |
| `google/gemma-4-26b-a4b-it` | 25B / 3.8B | 11 | 4 | 14.8 s / 84.8 s | $0.0047 | repeats `pick_aoi` (134 calls), no data pull |
| `upstage/solar-mini4` | 35B / 3B | 8 | 3 | 16.1 s / 22.1 s | $0.0065 | stops before the data pull |
| `meta/muse-spark-1.3-contributor` | not published | not scored | | | | refused by the account data policy |

- A smaller model is not cheaper or faster here. The two Qwen models think for a long time: they are about 3 times slower than DeepSeek and cost more for each question.
- The fast and cheap models (Ministral, gpt-oss-120b) fail at the data pull on about one third of the questions.
- Gemma 4 and Nemotron repeat one tool call many times. This is a model failure: `require_parameters` was on, so each request went to a provider with tool calls.
- `meta/muse-spark-1.3-contributor`: OpenRouter refused each call with "Paid model training violation". The account blocks providers that train on prompts, and the contributor tier does. The account setting was not changed.
- `ch-aoi-118` ("Show me the Cerrado") fails on most models.

## 3. OpenRouter pricing

OpenRouter sends a request to one of several providers of a model. The prices of the providers are different. `deepseek/deepseek-v4.1-flash` had 38 providers, at $0.051 to $0.45/M input and $0.34 to $1.80/M output. The `/models` list shows the price of one provider, and that value changed during the day. So the cost in this document is the key spend for each run, not tokens multiplied by a list price. The OpenRouter generation record of each call (`/api/v1/generation?id=gen-…`; the id is in the `response_metadata` of each AI message) gives the provider, the latency and the cost that OpenRouter charged. For the DeepSeek orchestrator calls, the charged cost was $1.63.

## Files

Local, not committed: `~/bench-runs/911/deepseek-v4.1-flash/` (DeepSeek run), `~/bench-runs/small-model-sweep/` (screen, `SCREEN.md`, `sweep.sh`, `analyze.py`, `full-muse-ember/`), `~/bench-runs/911/thread_tokens.py` (tokens from the checkpoints).
