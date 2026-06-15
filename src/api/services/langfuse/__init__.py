"""Langfuse trace ingestion: parse traces into structured Postgres rows,
fetch them from the Langfuse API, and orchestrate the daily/backfill ingestion.

The parser (`parse`) reads ``trace.output`` as the agent's own ``AgentState``
snapshot (src/agent/state.py) rather than scraping message text.

"""
