# ADR-001: Standalone Insight Artifacts

**Status:** Proposed
**Date:** 2026-03-25

---

## Context

Zeno currently operates as a conversational analyst: the agent pulls data, runs analysis, and returns chart data embedded in the LangGraph conversation state. When the conversation ends or the thread is discarded, the insight is gone. Retrieving it later requires loading the full checkpointer state for that thread.

This creates several problems:

- **Insights are not reusable.** A chart generated in one conversation cannot be referenced or rendered in another without replaying the thread.
- **Insights are not self-contained.** To understand what a chart shows — what data it was built from, what code produced it — you need the surrounding conversation context.
- **Insights cannot be edited.** There is no mechanism for the agent or user to refine a chart after it is produced. A new conversation run is required.
- **The agent is framed as an analyst.** Its outputs are answers, not artifacts. This limits the paradigm to Q&A rather than collaborative content creation.

The desired shift is to treat insights the same way an IDE assistant treats code edits: the agent helps create a persistent artifact that lives independently of the conversation that produced it. The conversation is the working context; the insight is the output.

---

## Decision

Refactor `generate_insights` to persist each insight as a database record (`InsightOrm`) and return only its UUID in agent state. The frontend fetches the insight by ID from a dedicated API endpoint rather than reading it from thread state.

This mirrors the existing pattern for custom areas (`CustomAreaOrm`), which are also created by the agent and fetched independently.

---

## Implementation

### 1. Database: `InsightOrm`

New table in `src/api/data_models.py`:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Auto-generated PK |
| `user_id` | String FK, nullable | Nullable to support anonymous sessions |
| `thread_id` | String FK, nullable | For traceability back to the originating conversation |
| `query` | String | The user's original question — makes the insight self-explanatory without the conversation |
| `inputs` | JSONB | `{aoi_names, dataset_name, start_date, end_date, source_urls}` — full data provenance |
| `title` | String | |
| `chart_type` | String | |
| `insight` | String | 2-3 sentence key finding |
| `follow_up_suggestions` | JSONB | Suggested next steps generated alongside the insight |
| `chart_config` | JSONB | `{xAxis, yAxis, seriesFields, groupField, colorField, stackField}` |
| `data` | JSONB | Array of chart data rows |
| `code` | JSONB | Encoded code blocks (`codeact_parts`) — provenance and reproducibility |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

### 2. Pydantic schema

Add `InsightModel` (read only) to `src/api/schemas.py`. No update schema in this phase — editing is deferred to a future ADR.

### 3. API endpoints

```
GET  /api/insights/{insight_id}          → InsightModel
GET  /api/insights?thread_id=&user_id=  → list[InsightModel]
```

### 4. Tool refactor

`src/agent/tools/generate_insights.py` — after generating chart data and metadata:

1. Open a DB session via `get_session_from_pool()` (already available to tools via the global pool)
2. Create and commit an `InsightOrm` record
3. Return only `insight_id` in the `Command` update:

```python
Command(update={
    "insight_ids": [str(insight_orm.id)],
    "messages": [ToolMessage(content=tool_message, ...)],
})
```

All other fields previously returned (`charts_data`, `codeact_parts`, `insight`, `follow_up_suggestions`) are removed from state — the DB record is the single source of truth.

### 5. Agent state

`src/agent/state.py` — remove `insights`, `charts_data`, `codeact_parts`. Add:

```python
insight_ids: list[str]
```

#### Passing `user_id` and `thread_id` to the tool

The tool needs `user_id` and `thread_id` to populate the foreign keys. These are not currently in `AgentState`. The chosen approach is to add them to `AgentState` and set them at graph entry, making them available to all tools uniformly.

Alternative considered: inject via LangGraph `RunnableConfig` configurable keys. This is slightly cleaner architecturally (tools shouldn't need to know about users) but adds complexity and is inconsistent with how other context (e.g., `user_persona`) is currently passed. Revisit if more tools need user-scoped access.

### 6. Alembic migration

Generate via:
```
alembic revision --autogenerate -m "add_insights_table"
```

Using the existing setup at `db/alembic.ini`.

### 7. Frontend

The stream now emits `insight_ids: ["<uuid>"]` instead of `charts_data: [...]`. The frontend:

1. Receives `insight_ids` from the stream
2. Calls `GET /api/insights/{id}` to fetch the full record
3. Renders the chart from the API response (same fields as today's `charts_data[0]`)
4. Can cache insights by ID and reuse across conversations

### 8. System prompt / agent persona

With insights as artifacts, the agent's framing should change — it is a content author, not a conversational analyst. The system prompt in `src/agent/prompts.py` should be reviewed and updated to reflect:

- How the agent refers to what it produces ("I've created an insight you can view" vs. "here is my analysis")
- How follow-up suggestions are framed (refining an artifact vs. re-running analysis)
- The overall persona and role description

---

## Consequences

### Positive

- Insights are independently fetchable and renderable without loading conversation state
- Insights carry their own provenance (`query`, `inputs`, `code`) — self-explanatory without surrounding context
- Foundation for future editing, sharing, and insight galleries
- Agent state becomes lighter — no large data blobs in the checkpointer
- Consistent with the existing custom areas pattern

### Negative / Trade-offs

- **Breaking change:** existing conversations with `charts_data` in checkpointed state will not render charts after this migration. The frontend will find `insight_ids` empty for old threads.
- **Potential future work:** a one-time migration script to backfill `InsightOrm` records from existing checkpointer state is possible but not in scope here. If there is significant user data worth preserving, this should be addressed before shipping.
- Adds a DB write to every `generate_insights` call — negligible overhead but a new failure mode (tool succeeds but DB write fails). Should be handled with a clear error in the `ToolMessage`.
