"""add input_source and nudge columns to langfuse_traces

Revision ID: 9f723bd32c77
Revises: e7c1f4a92b58
Create Date: 2026-09-23 12:00:00.000000

Hand-written (autogenerate disabled). Persists how each chat turn's query was
produced, read from the per-turn Langfuse trace metadata that /api/chat sets:
- ``input_source``: typed, nudge, starter_prompt, ... (see InputSource in
  src/api/schemas.py). NULL means unknown (traces from before the field
  existed), never "typed".
- ``nudge_type``: the clicked nudge's type, for nudge turns.
- ``nudge_match``: the server-side cross-check that the query equals an option
  of the thread's pending nudge.

Indexed on ``input_source`` so trace analytics can filter clicks. Schema only:
existing rows stay NULL; re-ingesting a window fills any that carry the
metadata. List-surface only, so no view change.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f723bd32c77"
down_revision: Union[str, None] = "e7c1f4a92b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "langfuse_traces",
        sa.Column("input_source", sa.String(), nullable=True),
    )
    op.add_column(
        "langfuse_traces",
        sa.Column("nudge_type", sa.String(), nullable=True),
    )
    op.add_column(
        "langfuse_traces",
        sa.Column("nudge_match", sa.Boolean(), nullable=True),
    )
    op.create_index(
        "ix_langfuse_traces_input_source",
        "langfuse_traces",
        ["input_source"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_langfuse_traces_input_source", table_name="langfuse_traces"
    )
    op.drop_column("langfuse_traces", "nudge_match")
    op.drop_column("langfuse_traces", "nudge_type")
    op.drop_column("langfuse_traces", "input_source")
