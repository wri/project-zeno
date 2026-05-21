---
name: wri-insights
description: Search WRI Insights blog posts for published research to ground analysis and cite sources.
when_to_use: Before or during full analysis when WRI's published perspective would strengthen the answer (policy context, drivers, methodology, regional background). Also when the user asks about WRI research or wants citations from wri.org/insights.
---

# Workflow

1. Call `wri_insights` with a short query (topic + place or dataset theme). Use `max_articles=2` unless the user needs broader coverage.
2. **Immediately after** the tool returns (and before any other tool call): send a **short intermediate message** to the user summarizing what WRI published material adds — **every paragraph must include at least one markdown link** to a blog post from the tool output (title link, `[§N](url#pN)`, or the canonical URL). No other tools until this message is sent.
3. Read returned articles for the next steps. Each article has a **URL:** line and paragraph tags like `[§1](url#p1)` — reuse these in your summary.
4. In full analysis (`analyze` skill): call `wri_insights` **after** a successful `pull_data` and **before** `generate_insights` when WRI context would add value. In the intermediate message, connect the blog findings to the pulled data topic; then call `generate_insights`, incorporating that context in the analysis query when helpful.
5. If the index is missing, tell the user to run `uv run python scripts/fetch_wri_insights.py --limit 50` — do not guess article content.

Call tools **one at a time**, never in parallel.

# Citing WRI Insights

- Only cite articles returned by `wri_insights`. Do not invent URLs or titles.
- When quoting a specific claim, use the paragraph link from the tool output, e.g. `[§3](https://www.wri.org/insights/example#p3)`.
- For general reference to an article, link the title or a short phrase to the **URL:** from that article.

# Ending insights with blog links

The intermediate message (above) satisfies the "answer with links" requirement for the WRI lookup itself. **Additionally**, when you used WRI Insights in a turn that also produces an insight (`generate_insights` or a chart summary):

- End your **user-facing reply** with **one or two affirmative sentences** that tie the chart or finding to WRI's published work.
- Each sentence should include at least one markdown link to the relevant blog post(s).
- Write in confident, neutral language — state what the data shows and how it relates to WRI's analysis, not hedging questions.

**Example closing (adapt to the actual URLs from tool output):**

> Tree cover loss in the AOI rose sharply after 2020, consistent with regional fire trends described in [WRI's analysis of Amazon fire seasons](https://www.wri.org/insights/example-article). The chart supports [WRI's finding that early-warning systems reduce response time](https://www.wri.org/insights/another-article#p4) in comparable landscapes.

Place this WRI citation block **after** your 1–2 sentence chart summary, separated by a blank line.
