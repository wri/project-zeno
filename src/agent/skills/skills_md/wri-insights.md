---
name: wri-insights
description: Enrich an analysis with WRI Insights published research to ground findings and cite sources.
when_to_use: Before or during full analysis when WRI's published perspective would strengthen the answer (policy context, drivers, methodology, regional background). Also for a standalone research-literature question that does NOT name a place plus a data-shaped topic (e.g. "what does WRI say about deforestation drivers", "any recent WRI research on mangrove restoration"). If the question names a specific place and a data-shaped topic — including "how/why does X impact/affect Y in <place>" phrasing — use `analyze` instead and let `pick_dataset` run first (see `search_blogs`'s routing rule for the exact boundary and an example); call this skill only after a successful `pull_data`, per the workflow below.
requires: search_blogs
---

# Workflow

For a **direct question about WRI research** (no analysis pipeline running), step 1 is the whole job: search, then answer in your usual well-structured markdown — keeping the inline `[N](url)` citation markers on the statements you use.

1. Call `search_blogs` with a short query (topic + place or dataset theme). It runs a research subagent that searches and reads the WRI Insights corpus and returns a **synthesized answer with markdown citations** to wri.org/insights — you do not need to read articles yourself.
2. **Immediately after** the tool returns (and before any other tool call): send a **short intermediate message** to the user that condenses the subagent's answer into 1-3 sentences. **Every paragraph must keep at least one `[N](url)` citation marker** from the tool output. No other tools until this message is sent.
3. In full analysis (`analyze` skill): call `search_blogs` **after** a successful `pull_data` and **before** `generate_insights` when WRI context would add value. In the intermediate message, connect the blog findings to the pulled data topic; then call `generate_insights`, incorporating that context in the analysis query when helpful.
4. If the search returns "index not found" or no results, tell the user to run `uv run python scripts/fetch_wri_insights.py --limit 50` (and build the sgrep index with `sgrep index`) — do not guess article content.

Call tools **one at a time**, never in parallel.

# Citing WRI Insights

- Only cite articles returned by `search_blogs`. Do not invent URLs.
- Cite inline with compact numbered markers: `[N](https://www.wri.org/insights/<slug>)` placed directly after the statement it supports — canonical URL, no `#fragment` or query string. The frontend replaces each marker with a citation icon and shows the article card on hover.
- Number articles by first appearance in **your reply** (renumber if you reuse a subset of the tool's citations) and reuse the same number for repeat citations of the same article.
- Write the prose itself naturally — don't name article titles or wrap citations in "according to ..."; the markers carry the attribution. Do not add a Sources list; the hover cards carry titles and details.

# Ending insights with blog links

The intermediate message (above) satisfies the "answer with links" requirement for the WRI lookup itself. **Additionally**, when you used WRI Insights in a turn that also produces an insight (`generate_insights` or a chart summary):

- End your **user-facing reply** with **one or two affirmative sentences** that tie the chart or finding to WRI's published work.
- Each sentence should carry at least one `[N](url)` citation marker.
- Write in confident, neutral language — state what the data shows and how it relates to WRI's analysis, not hedging questions.

**Example closing (adapt to the actual URLs from tool output):**

> Tree cover loss in the AOI rose sharply after 2020, consistent with regional fire trends described in WRI's analysis of Amazon fire seasons [1](https://www.wri.org/insights/example-article). The chart supports the finding that early-warning systems reduce response time in comparable landscapes [2](https://www.wri.org/insights/another-article).

Place this WRI citation block **after** your 1–2 sentence chart summary, separated by a blank line.
