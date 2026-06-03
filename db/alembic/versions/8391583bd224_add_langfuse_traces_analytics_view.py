"""add langfuse_traces_analytics view

Revision ID: 8391583bd224
Revises: a7d17cad8386
Create Date: 2026-06-03 15:15:32.632677

The sanctioned analytics surface over langfuse_traces. It exposes the turn-level
derived columns plus a computed ``is_final_turn_in_thread`` flag so consumers can
pick one representative row per thread (for cumulative fields) without re-deriving
the dedup logic. Session-less traces (null session_id) are treated as singleton
threads via COALESCE(session_id, id).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8391583bd224"
down_revision: Union[str, None] = "a7d17cad8386"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VIEW = "langfuse_traces_analytics"

_CREATE = f"""
CREATE OR REPLACE VIEW {_VIEW} AS
SELECT
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
    (
        row_number() OVER (
            PARTITION BY COALESCE(session_id, id)
            ORDER BY trace_timestamp DESC NULLS LAST, id DESC
        ) = 1
    ) AS is_final_turn_in_thread
FROM langfuse_traces;
"""


def upgrade() -> None:
    op.execute(_CREATE)


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {_VIEW};")
