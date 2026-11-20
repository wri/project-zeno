# Small models for the orchestrator: findings (2026-11-20)

This report continues `docs/openrouter-model-evals-2026-11-18.md`. It answers five questions:

1. Is it useful to fine-tune a small model for the orchestrator?
2. How much money does DeepSeek V4.1 Flash save when it runs only the orchestrator?
3. What does DeepSeek V4.1 Flash cost on hosts other than OpenRouter?
4. Can a model that we can host on Amazon Bedrock do the work of the orchestrator?
5. Why is a smaller model more expensive for each question?

## Summary

- A small model that we can host ourselves cannot replace DeepSeek V4.1 Flash or Gemini Flash as the orchestrator yet. The best candidate, Nemotron 3 Super 120B, scores 25 of 30 with a prompt change. DeepSeek scores 29 and Gemini scores 28 on the same code.
- When DeepSeek V4.1 Flash runs only the orchestrator (decisions on Gemini Decision 1, subagents and code executor on Gemini), the saving is about $0.006 to $0.008 for each question. This is about 25 to 35% of the total cost.
- Weak models fail mostly because they do not act (they stop, or they ask the user), not because they give wrong answers. A prompt rule to act first recovers part of this gap. The rule does not change the DeepSeek score.
- A smaller model is not cheaper for each question on OpenRouter. It gets a small cache discount or none, and it makes more calls.
- Do not fine-tune the full orchestrator now. Fine-tuning is a better fit for the single decision calls (dataset, area and view selection).

## 1. Fine-tune a small model for the orchestrator?

Reference: [gazet PR 17](https://github.com/developmentseed/gazet/pull/17), a small model (Qwen 0.8B to 2B, LoRA) that writes DuckDB spatial SQL.

What gazet shows:

- Fine-tuning helps a narrow task a lot: from 0% zero-shot to about 50 to 60% on tables that the model did not see in training.
- The model memorises its training material: 69% on known tables, 44% on new tables.
- Data and training are cheap: about $52 of data, and 20 minutes on one A100.
- The task is a good fit: one input, one output, and a check that runs in milliseconds (run the SQL).

Why the orchestrator is a harder target:

- It is a loop of about 5 tool calls with a prompt of 7,000 to 8,000 tokens, not one output.
- A check needs the full GOLD pipeline (area search, data pull, Gemini code executor). One sample takes minutes, so reinforcement learning is not practical.
- The tools and the prompt change every few weeks. A fine-tuned model locks in the current tool contracts.
- The code executor stays on Gemini in all cases.

What helps a fine-tune here:

- The world is closed (fixed datasets, tools and area types), so memorisation is useful.
- We have real traces: BENCHMARK runs and production traces in Langfuse. Check consent and policy before we use user prompts for training.

Recommendation:

- Fine-tune the single decision calls first (dataset, area, view). They are one-shot and closed, the labels come from GOLD runs, and they do not change when the loop changes.
- To test a fine-tuned orchestrator later, hold out whole question families, not single questions. Stop when the score on the held-out families is less than about 80%.

## 2. Cost saving with DeepSeek V4.1 Flash as the orchestrator only

Assumption: decisions use Gemini Decision 1. The subagents and the code executor stay on Gemini.

| Cost for each question | All Gemini, with decisions | DeepSeek orchestrator |
|---|---|---|
| Orchestrator | $0.0097 | $0.0015 to $0.0035 (depends on the host) |
| Subagents (Gemini) | about $0.0066 | about $0.0066 |
| Decisions (Gemini Decision 1) | about $0.0002 | about $0.0002 |
| Code executor (Gemini) | about $0.0063 | about $0.0063 |
| **Total** | **about $0.023** | **about $0.015 to $0.017** |

- Saving: about $6 to $8 for each 1,000 questions, or $600 to $800 for each 100,000 questions.
- Latency: a DeepSeek call takes about 2.2 s, a Gemini call about 1.0 s. Expect about 5 to 10 s more at the median.
- Sources: Gemini orchestrator from the PR #911 and PR #922 full runs (thread state, list price). DeepSeek orchestrator from the OpenRouter generation records of the PR #911 full run. Subagents and code executor from the 30-question Langfuse sample (section 1.3 of the 2026-11-18 report).
- Limits: the 30-question sample has only easy questions. The decision cost is an estimate. This exact combination did not run end to end.

## 3. DeepSeek V4.1 Flash prices on other hosts

Most prices come from aggregator sites, not from the providers. Check the price list of the provider before a decision. The cost for each question uses the DeepSeek orchestrator tokens of the PR #911 run (5,500 input not cached, 21,500 cached input, 1,000 output).

| Host | Input / cached input / output (for each 1M tokens) | Orchestrator cost for each question |
|---|---|---|
| DeepSeek API, off-peak | $0.15 / $0.003 / $0.60 | about $0.0015 |
| DeepSeek API, peak | $0.30 / $0.006 / $1.20 | about $0.0030 |
| Together AI | $0.30 / $0.006 / $1.20 | about $0.0030 |
| Google Vertex AI (MaaS) | $0.30 / $0.03 / $1.20 | about $0.0035 |
| Azure Foundry | $0.30 / not known / $1.20 | about $0.0030 to $0.0035 |
| Fireworks on Azure | $0.375 / not known / $1.50 | about $0.0044; about $0.012 with no cache discount |
| OpenRouter (charged, 2026-11-18) | mixed providers | $0.0020 |

- The cached input price is the most important number. About 80% of the orchestrator input comes from the cache. A host with no cache discount can cost more than Gemini.
- Vertex AI is probably the practical choice: the same vendor as Gemini for billing and data agreements.
- The DeepSeek API is the cheapest, but it runs in China. Check this against the WRI data policy.

## 4. Models on Amazon Bedrock

Bedrock notes:

- Most open-weight models on Bedrock are serverless (pay for each token), not self-hosted. Custom Model Import is the nearest option to self-hosting. Secondary sources say that imported Qwen3 and gpt-oss models do not support the Converse API, so tool calls need `InvokeModel`.
- Bedrock is about one model generation behind. We did not find DeepSeek V4.1 Flash on Bedrock (DeepSeek V3.2 is there).

Models on Bedrock that the 2026-11-18 screen did not include: MiniMax M2.5, Qwen3-Next-80B-A3B and Nemotron 3 Super 120B. Other Bedrock models are too large (Kimi, GLM 4.7, DeepSeek V3.2, Mistral Large 3) or are smaller versions of models that failed the first screen (gpt-oss-20b, Ministral, Gemma).

Setup:

- 30 BENCHMARK `2026-draft-5` questions (the list of the first screen), 1 attempt each.
- The candidate is `MODEL` and `SMALL_MODEL`, through OpenRouter with `require_parameters`. `FALLBACK_MODELS` is empty. `CODING_MODEL` stays on Gemini.
- Code: this branch at `53542ec9`, which is `feat/jev-decisions` `5e1732c1` (main merged) plus the OpenRouter backend. Dataset selection uses Gemini Decision 1.
- The two reference models ran again on the same code, because the code changed after the first screen.

| Model | Size (total / active) | Passed (of 30) | Main failure | Median / 90th percentile | Cost for each question |
|---|---|---|---|---|---|
| *DeepSeek V4.1 Flash (reference)* | 284B / 13B | **29** | none | 25 s / 59 s | $0.0042 |
| *Gemini Flash (reference)* | not published | **28** | none | 25 s / 39 s | not on OpenRouter |
| `nvidia/nemotron-3-super-120b-a12b` | 120B / 12B | 21 | explanation and analysis | 30 s / 73 s | $0.0054 |
| `minimax/minimax-m2.5` | about 230B / 10B | 16 | retrieval: stops without a data pull | 52 s / 82 s | $0.0078 |
| `qwen/qwen3-next-80b-a3b-instruct` | 80B / 3B | 11 | retrieval: stops without a data pull | 18 s / 49 s | $0.0020 |

The first screen (2026-11-18, PR #911 code) for comparison: Muse Ember 27 (not open weights), Qwen3.6-35B-A3B 26, Qwen3.8-27B 26, Muse Glimmer 30B 22, all other models 19 or less.

## 5. Failure to act, not wrong answers: proactive prompt test

Qwen3-Next failed mostly because it did not act:

- It said "no dataset" and did not call `pick_dataset` (10 questions).
- It asked the user what type of area a place is (5 questions).
- It stopped after one failed area search (3 questions).

Test: a temporary prompt section (not in this branch) told the model to:

- call `pick_dataset`, and let `pick_dataset` decide if a dataset measures the topic;
- not ask the user for the area type, and use the most probable type;
- after a failed area search, try one more time with a broader name;
- not ask the user to confirm a step that it can do.

| Model | Original prompt | Proactive prompt | Median latency (original / proactive) |
|---|---|---|---|
| DeepSeek V4.1 Flash | 29 | 29 | 25 s / 21 s |
| Nemotron 3 Super 120B | 21 | **25** | 30 s / 44 s |
| Qwen3-Next-80B-A3B | 11 | 17 | 18 s / 32 s |

- The rule halves the retrieval failures of Qwen3-Next (12 to 6). But 5 questions still get "no dataset" with no tool call, so the model does not follow the rule every time.
- Nemotron 3 Super fails `ch-aoi-118`, `ch-causal-006`, `ch-comp-055`, `ch-comp-174` and `ch-trend-053`. `ch-aoi-118` fails on most models, and Gemini also fails `ch-causal-006`.
- The rule does not make DeepSeek worse (it misses `ch-quant-118` instead of `ch-quant-175`). It is safe to keep as a permanent rule.
- One attempt on 30 questions has a noise of about 1 to 2 questions.

## 6. Why is a smaller model more expensive for each question?

OpenRouter generation records for the orchestrator calls of the proactive runs (30 questions):

| | DeepSeek V4.1 Flash | Nemotron 3 Super | Qwen3-Next |
|---|---|---|---|
| Orchestrator calls | 127 | 139 | 304 |
| Input tokens for each call | 8,400 | 8,400 | 13,400 |
| Input from the cache | 64% | 0% | 17% |
| Output for each call (thinking) | 400 (156) | 400 (315) | 56 (0) |
| Cost for each 1,000 calls | $0.81 | $1.11 | $1.31 |
| Main providers | CoreWeave, Wafer, InferenceNet | DeepInfra | DeepInfra, Parasail |

- Cache: input is about 95% of the tokens. DeepSeek gets most of its input from the cache at a large discount. The Nemotron provider gave no cache discount.
- More calls: a weak model searches again and tries again. Qwen3-Next made 2.4 times more calls than DeepSeek, with prompts that are 60% longer.
- Thinking: Nemotron writes about 2 times more thinking tokens than DeepSeek, at the output price.
- When we host a model ourselves, we control the cache (vLLM and SGLang use the shared prompt prefix again), and we pay for GPU time, not for tokens. The OpenRouter price of a model tells little about the cost to host it ourselves.

## Proposed next steps

1. Run Nemotron 3 Super with the proactive rule on the full BENCHMARK (269 questions, 3 attempts) to measure the real gap.
2. Add the proactive rule to the prompt, after a full BENCHMARK run on Gemini and DeepSeek.
3. Run DeepSeek as the orchestrator on the decision model code on the full BENCHMARK, to measure cost and latency end to end.
4. Plan a fine-tune of one decision call (for example dataset selection) as the first small-model experiment.

## Files

Local, not committed: `~/bench-runs/small-model-sweep/` (`SCREEN.md`, `sweep.sh`, `bedrock-922/`, `bedrock-922-proactive/`), `~/bench-runs/911/gen_stats_{ds,nemo,qwen}-pro.json` (generation records).

Price sources: [DeepSeek V4.1 Flash on OpenRouter](https://openrouter.ai/deepseek/deepseek-v4.1-flash), [LiteLLM model list](https://models.litellm.ai/models/deepseek-v4.1-flash), [Microsoft Foundry blog](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/deepseek-v4-1-flash-is-coming-to-microsoft-foundry/4556431), [Artificial Analysis providers](https://artificialanalysis.ai/models/deepseek-v4-1-flash-1017/providers), [Mercatus](https://www.mercatus-ai.com/blog/deepseek-v4-1-flash-api-pricing), [BenchLM](https://benchlm.ai/deepseek/api-pricing). Bedrock: [Models at a glance](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html), [six open-weight models (2026-02)](https://aws.amazon.com/about-aws/whats-new/2026/02/amazon-bedrock-adds-support-six-open-weights-models), [Custom Model Import code samples](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-model-import-code-samples.html).
