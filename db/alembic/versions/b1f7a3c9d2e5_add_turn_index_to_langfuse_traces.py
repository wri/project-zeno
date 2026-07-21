"""add turn_index to langfuse_traces

Revision ID: b1f7a3c9d2e5
Revises: a1b2c3d4e5f6
Create Date: 2026-07-03 10:00:00.000000

Hand-written (autogenerate disabled). Adds the stored per-turn ordinal ``turn_index``
(1-based within a session by trace_timestamp) so turn-position analytics is
index-filterable rather than a per-request window, and starts using
``is_final_turn_in_thread``. The ``langfuse_traces_analytics`` view is rewritten to
read the stored flag (dropping its row_number() window) and expose ``turn_index``.

Schema only: new rows are populated by the ingest recompute, and existing rows by the
out-of-band ``backfill-turn-fields`` CLI command (data backfills stay out of the
blocking deploy migration). Both columns read NULL for existing rows until that command
runs — endpoints and the view tolerate NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1f7a3c9d2e5"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VIEW = "langfuse_traces_analytics"

# Base column projection shared by both the new and old view definitions.
_VIEW_BASE_COLS = """
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
    prompt"""

# New: read the stored is_final_turn_in_thread and expose turn_index (both now
# maintained on the base table), so the view is a plain projection with no window.
_VIEW_NEW = f"""
CREATE OR REPLACE VIEW {_VIEW} AS
SELECT{_VIEW_BASE_COLS},
    is_final_turn_in_thread,
    turn_index
FROM langfuse_traces;
"""

# Old: is_final_turn_in_thread computed via a row_number() window, no turn_index.
_VIEW_OLD = f"""
CREATE OR REPLACE VIEW {_VIEW} AS
SELECT{_VIEW_BASE_COLS},
    (
        row_number() OVER (
            PARTITION BY COALESCE(session_id, id)
            ORDER BY trace_timestamp DESC NULLS LAST, id DESC
        ) = 1
    ) AS is_final_turn_in_thread
FROM langfuse_traces;
"""


def upgrade() -> None:
    op.add_column(
        "langfuse_traces", sa.Column("turn_index", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_langfuse_traces_turn_index", "langfuse_traces", ["turn_index"]
    )
    # Serves the common "first turns, newest first" read directly (no sort).
    op.create_index(
        "ix_langfuse_traces_first_turn",
        "langfuse_traces",
        [sa.text("trace_timestamp DESC")],
        postgresql_where=sa.text("turn_index = 1"),
    )
    # View now reads the stored is_final_turn_in_thread + exposes turn_index.
    op.execute(_VIEW_NEW)


def downgrade() -> None:
    # The old view has fewer columns than the new one, so REPLACE can't shrink it.
    op.execute(f"DROP VIEW IF EXISTS {_VIEW};")
    op.execute(_VIEW_OLD)
    op.drop_index(
        "ix_langfuse_traces_first_turn", table_name="langfuse_traces"
    )
    op.drop_index(
        "ix_langfuse_traces_turn_index", table_name="langfuse_traces"
    )
    # is_final_turn_in_thread was unpopulated before this migration.
    op.execute("UPDATE langfuse_traces SET is_final_turn_in_thread = NULL;")
    op.drop_column("langfuse_traces", "turn_index")
