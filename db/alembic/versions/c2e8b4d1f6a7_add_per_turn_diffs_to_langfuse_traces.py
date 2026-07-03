"""add per-turn diff columns to langfuse_traces

Revision ID: c2e8b4d1f6a7
Revises: b1f7a3c9d2e5
Create Date: 2026-07-03 11:00:00.000000

Hand-written (autogenerate disabled). Adds two per-turn signals complementing the
thread-cumulative fields:
- ``insight_created_this_turn``: insight_id became non-null on this turn.
- ``datasets_analysed_this_turn``: this turn's derived->datasets_analysed_cumulative
  minus the previous turn's.
Both are cross-row (depend on the previous turn), so new rows are maintained by the
same ingest recompute as ``turn_index`` and existing rows by the out-of-band
``backfill-turn-fields`` CLI command (schema only here — data backfills stay out of the
blocking deploy migration). List-surface only, so no view change.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2e8b4d1f6a7"
down_revision: Union[str, None] = "b1f7a3c9d2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def downgrade() -> None:
    op.drop_column("langfuse_traces", "datasets_analysed_this_turn")
    op.drop_column("langfuse_traces", "insight_created_this_turn")
