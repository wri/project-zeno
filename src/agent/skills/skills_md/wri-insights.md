---
name: wri-insights
description: Enrich an analysis with WRI Insights published research to ground findings and cite sources.
when_to_use: Before or during full analysis when WRI's published perspective would strengthen the answer (policy context, drivers, methodology, regional background). Also when the user asks about WRI research or wants citations from wri.org/insights.
---

# Workflow

1. Call `search_blogs` with a short query (topic + place or dataset theme). It runs a research subagent that searches and reads the WRI Insights corpus and returns a **synthesized answer with markdown citations** to wri.org/insights — you do not need to read articles yourself.
2. **Immediately after** the tool returns (and before any other tool call): send a **short intermediate message** to the user that condenses the subagent's answer into 1-3 sentences. **Every paragraph must keep at least one markdown link** to a blog post from the tool output. No other tools until this message is sent.
3. In full analysis (`analyze` skill): call `search_blogs` **after** a successful `pull_data` and **before** `generate_insights` when WRI context would add value. In the intermediate message, connect the blog findings to the pulled data topic; then call `generate_insights`, incorporating that context in the analysis query when helpful.
4. If the search returns "index not found" or no results, tell the user to run `uv run python scripts/fetch_wri_insights.py --limit 50` (and build the sgrep index with `sgrep index`) — do not guess article content.

Call tools **one at a time**, never in parallel.

# Citing WRI Insights

- Only cite articles returned by `search_blogs`. Do not invent URLs or titles.
- Cite as `[Article Title](https://www.wri.org/insights/<slug>)` — the article title as link text, the canonical URL with no `#fragment` or query string. The frontend turns these links into article cards, so the link text becomes the card title.
- Link each article at most once per reply (no duplicate URLs), and keep the links in plain prose — not inside headings or bold.

# Ending insights with blog links

The intermediate message (above) satisfies the "answer with links" requirement for the WRI lookup itself. **Additionally**, when you used WRI Insights in a turn that also produces an insight (`generate_insights` or a chart summary):

- End your **user-facing reply** with **one or two affirmative sentences** that tie the chart or finding to WRI's published work.
- Each sentence should include at least one markdown link to the relevant blog post(s).
- Write in confident, neutral language — state what the data shows and how it relates to WRI's analysis, not hedging questions.

**Example closing (adapt to the actual URLs from tool output):**

> Tree cover loss in the AOI rose sharply after 2020, consistent with regional fire trends described in [What's Driving Amazon Fire Seasons](https://www.wri.org/insights/example-article). The chart supports the finding that early-warning systems reduce response time in comparable landscapes, as shown in [Forest Monitoring Systems Explained](https://www.wri.org/insights/another-article).

Place this WRI citation block **after** your 1–2 sentence chart summary, separated by a blank line.
