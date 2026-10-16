"""add agent/tool llm usage split to langfuse_traces

Revision ID: f3a8c1d5b204
Revises: 9c4e1d7f2a60
Create Date: 2026-09-03 11:20:00.000000

Token columns used to be derived from the AIMessage stream, which only carries
the calls the agent made itself — an LLM call inside a tool returns a
ToolMessage and so was counted nowhere. Parser v3 sources them from the trace's
generation observations instead and records the split:

* ``agent_tokens`` / ``agent_cost`` — what the agent spent itself (this is what
  ``turn_tokens`` used to hold).
* ``tool_tokens`` / ``tool_cost`` — the remainder, spent by LLM calls inside
  tools. Roughly a third of cost on the measured production trace.
* ``generation_count`` — how many LLM calls the turn made in total.

``turn_tokens`` steps up for any turn whose tools call an LLM, so re-run
ingestion over the window you care about (``ingest-langfuse-traces --backfill
--since``) to put existing rows on the new basis. The analytics view is
recreated to expose the new columns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a8c1d5b204"
down_revision: Union[str, None] = "9c4e1d7f2a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "langfuse_traces"
_VIEW = "langfuse_traces_analytics"

_NEW_COLUMNS = (
    ("agent_tokens", sa.Integer()),
    ("tool_tokens", sa.Integer()),
    ("agent_cost", sa.Float()),
    ("tool_cost", sa.Float()),
    ("generation_count", sa.Integer()),
)

# Projection as of b1f7a3c9d2e5 (stored is_final_turn_in_thread + turn_index).
_PRIOR_COLS = """
    id,
    session_id,
    user_id,
    environment,
    trace_timestamp,
    outcome,
    has_answer,
    answer_is_refusal,
    had_tool_call,
    tool_error_count,
    aoi_name,
    aoi_type,
    primary_dataset_name,
    has_insight,
    is_global,
    insight_id,
    turn_input_tokens,
    turn_output_tokens,
    turn_tokens,
    turn_tool_calls,
    latency_seconds,
    total_cost,
    prompt,
    is_final_turn_in_thread,
    turn_index"""

# New columns are appended, so CREATE OR REPLACE accepts the wider view.
_CREATE_VIEW = f"""
CREATE OR REPLACE VIEW {_VIEW} AS
SELECT{_PRIOR_COLS},
    agent_tokens,
    tool_tokens,
    agent_cost,
    tool_cost,
    generation_count
FROM {_TABLE};
"""

# REPLACE cannot drop columns, so the downgrade recreates the view.
_PRIOR_VIEW = f"""
CREATE VIEW {_VIEW} AS
SELECT{_PRIOR_COLS}
FROM {_TABLE};
"""


def upgrade() -> None:
    for name, type_ in _NEW_COLUMNS:
        op.add_column(_TABLE, sa.Column(name, type_, nullable=True))
    op.execute(_CREATE_VIEW)


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {_VIEW};")
    op.execute(_PRIOR_VIEW)
    for name, _ in reversed(_NEW_COLUMNS):
        op.drop_column(_TABLE, name)
