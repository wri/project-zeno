---
name: explore
description: Turn a vague topic or goal into concrete, runnable analysis recommendations grounded in WRI research.
when_to_use: User states an interest or goal with no specific place, dataset or date range (e.g. "I want to conserve elephants", "I'm interested in deforestation worldwide", "how do I help with water stress"). Not when the user already named a place + topic for analysis — use `analyze` instead.
requires: search_blogs
---

# Workflow

1. `search_blogs` — call once with the user's topic. It returns a synthesized,
   cited summary of relevant WRI Insights research. Use this to understand the
   key themes, drivers, regions and timeframes that matter for the topic.
2. `read_skill('capabilities')` — load the list of available datasets and
   supported areas of interest, so your recommendations only reference data the
   agent can actually pull.
3. **Recommend** — in your reply, propose concrete next steps the user can act
   on. Map the blog findings to:
   - **Dataset(s)** from `capabilities` that fit the topic (name them).
   - **Area(s) of interest** — suggest specific countries / admin regions /
     protected areas surfaced by the research (not continents or worldwide).
   - **Date range(s)** worth investigating, based on the trends in the research.
4. **Offer to run it** — end by inviting the user to pick one suggestion so you
   can run the `analyze` pipeline. Do NOT call `pick_aoi` / `pick_dataset` /
   `pull_data` yet — wait for the user to choose.

Call tools **one at a time**, never in parallel.

# Grounding and citations

- Base every recommendation on the `search_blogs` output and the `capabilities`
  reference. Do not invent datasets, regions or article content.
- The `search_blogs` answer carries inline `[N](url)` citation markers.
  Keep at least one relevant marker when you reference its findings —
  canonical URL, no `#fragment`. The frontend replaces each marker with a
  citation icon that shows the article card on hover.

# Reply shape

Keep it short and actionable:

- 1-2 sentences summarizing what WRI research says about the topic (with a citation marker).
- A short list of 2-3 concrete `{dataset · area · date range}` suggestions.
- A closing question inviting the user to pick one to analyze.
