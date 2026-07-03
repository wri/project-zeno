"""add per-turn diff columns to langfuse_traces

Revision ID: c2e8b4d1f6a7
Revises: b1f7a3c9d2e5
Create Date: 2026-07-03 11:00:00.000000

Hand-written (autogenerate disabled). Adds two per-turn signals complementing the
thread-cumulative fields:
- ``insight_created_this_turn``: insight_id became non-null on this turn.
- ``datasets_analysed_this_turn``: this turn's derived->datasets_analysed_cumulative
  minus the previous turn's.
Both are cross-row, so ongoing rows are maintained by the same ingest recompute as
``turn_index``; this backfills existing rows once, partitioned by
COALESCE(session_id, id) (null-session singletons have no predecessor). List-surface
only, so no view change.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2e8b4d1f6a7"
down_revision: Union[str, None] = "b1f7a3c9d2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Backfill the per-turn diffs for every row from current table state, using the
# same COALESCE(session_id, id) partition/order as the turn_index backfill so a row
# and its predecessor are adjacent in the window.
#   - insight_created_this_turn: insight_id present and differs from the prior turn.
#   - datasets_analysed_this_turn: this turn's cumulative datasets minus the prior
#     turn's (EXCEPT over the unnested arrays; prior is {} on the first turn).
_BACKFILL = """
WITH ranked AS (
    SELECT id,
           insight_id,
           lag(insight_id) OVER w AS prev_insight,
           ARRAY(SELECT jsonb_array_elements_text(
               COALESCE(derived->'datasets_analysed_cumulative', '[]'::jsonb)
           )) AS cur_ds,
           lag(ARRAY(SELECT jsonb_array_elements_text(
               COALESCE(derived->'datasets_analysed_cumulative', '[]'::jsonb)
           ))) OVER w AS prev_ds
    FROM langfuse_traces
    WINDOW w AS (
        PARTITION BY COALESCE(session_id, id)
        ORDER BY trace_timestamp ASC NULLS LAST, id ASC
    )
)
UPDATE langfuse_traces t
SET insight_created_this_turn =
        (ranked.insight_id IS NOT NULL
         AND ranked.insight_id IS DISTINCT FROM ranked.prev_insight),
    datasets_analysed_this_turn = ARRAY(
        SELECT unnest(ranked.cur_ds)
        EXCEPT
        SELECT unnest(COALESCE(ranked.prev_ds, ARRAY[]::text[]))
    )
FROM ranked
WHERE t.id = ranked.id;
"""


def upgrade() -> None:
    op.add_column(
        "langfuse_traces",
        sa.Column("insight_created_this_turn", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "langfuse_traces",
        sa.Column(
            "datasets_analysed_this_turn",
            sa.ARRAY(sa.String()),
            nullable=True,
        ),
    )
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.drop_column("langfuse_traces", "datasets_analysed_this_turn")
    op.drop_column("langfuse_traces", "insight_created_this_turn")
