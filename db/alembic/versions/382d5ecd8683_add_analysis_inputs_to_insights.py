"""add analysis_inputs to insights

Revision ID: 382d5ecd8683
Revises: a6d2e9c4b713
Create Date: 2026-11-04 17:25:45.000000

A snapshot of the inputs an insight was computed from: one entry per data
pull, with its areas, dataset, dates, canopy cover and context layer. It is
written once, when the insight is saved. ``statistics_ids`` cannot give it,
because it links every pull of the thread, not only the pulls the chart used.

Nullable with no default and no backfill: NULL means the inputs were not
recorded, which is the case for every insight saved before this revision.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "382d5ecd8683"
down_revision: Union[str, None] = "a6d2e9c4b713"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "insights",
        sa.Column("analysis_inputs", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("insights", "analysis_inputs")
