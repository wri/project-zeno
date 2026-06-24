# `search_blogs` subagent flow

How the WRI Insights blog-search subagent turns a query into a cited answer,
and exactly what it hands back to the orchestrator.

```mermaid
flowchart TD
    O([Orchestrator]) -->|"search_blogs(query)"| ST["search_blogs tool"]

    subgraph DA["blog-search deep agent (internal — not returned)"]
        direction TB
        LLM{{"LLM<br/>(SMALL_MODEL)"}}
        SG["sgrep<br/>semantic search"]
        GA["grep_articles<br/>keyword / regex"]
        AM["article_meta<br/>shortlist check"]
        RP["read_paragraphs / read_file<br/>targeted reads"]
        QI["query_index<br/>(static model + bundled index)"]
        IDX[("sgrep index<br/>embeddings.npy + meta.jsonl")]
        MD[("WRI Insights corpus<br/>&lt;slug&gt;.md (§N-tagged)")]

        LLM --> SG --> QI --> IDX
        QI -->|"§N hits + scores"| LLM
        LLM --> GA --> MD
        GA -->|"§N matches"| LLM
        LLM --> AM --> MD
        LLM --> RP --> MD
        LLM ==>|"synthesized answer<br/>with [N](url) markers"| ANS["final AI message"]
    end

    ST -->|"ainvoke(query)"| LLM
    ANS --> EX["extract on return"]

    EX --> CT["_cited_articles_for_search"]
    CT -->|"[N](url) in answer?"| C1["cited-in-text<br/>(articles used)"]
    CT -.->|"else fallback"| C2["shortlist<br/>(article_meta calls)"]

    ST ==>|"Command.update"| OUT

    subgraph OUT["returned to orchestrator state"]
        direction TB
        MSG["messages:<br/>1 ToolMessage = answer text"]
        CA["cited_articles:<br/>slug, title, abstract, url, lastmod, image"]
    end

    C1 --> CA
    C2 --> CA
    ANS --> MSG

    classDef dropped stroke-dasharray: 4 4;
    class SG,GA,AM,RP,QI,IDX,MD dropped;
```

## What crosses the boundary

The subagent returns a `Command` updating two pieces of orchestrator state
(`blog.py` → `search_blogs`):

- **`messages`** — a single `ToolMessage` whose content is the synthesized
  prose answer with inline `[N](url)` citation markers.
- **`cited_articles`** — article-level metadata (`slug`, `title`, `abstract`,
  `url`, `lastmod`, `image`).

The deep agent's internal tool calls (sgrep / grep / article_meta / reads) are
consumed inside `search_blogs` and **not** propagated — they live only in logs
and the Langfuse trace (dashed nodes above).

## IDs

- **Document IDs survive** — the `slug` in each `cited_articles` entry is the
  document ID, joinable to `index.json`.
- **Chunk IDs do not** — the `§N` paragraph tags are research-only and are
  stripped before the answer is returned, so the orchestrator never sees them.

## `cited_articles` semantics

`_cited_articles_for_search` prefers the **cited-in-text** set (articles whose
`[N](url)` markers appear in the answer — precision-oriented) and falls back to
the **shortlist** set (articles opened via `article_meta` — recall-oriented)
only when the answer contains no markers.

## Determinism

`query_index` / sgrep is deterministic (static embedding model, fixed index).
The end-to-end subagent output is **not** — the LLM chooses the queries,
keyword patterns, shortlist, and final synthesis, so the cited set varies run
to run.
