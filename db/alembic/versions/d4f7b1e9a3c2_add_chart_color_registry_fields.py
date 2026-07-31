"""add chart color registry fields to insight_charts

Revision ID: d4f7b1e9a3c2
Revises: ceea2a027738
Create Date: 2026-07-24 00:00:00.000000

Phase 2 of the insight chart color registry (see
docs/insight-chart-colors-plan.md): persists the dataset_id colors were
resolved against plus the resolved color_map/series_color/divergent_colors
onto each chart, so a later display revision can re-resolve colors without
re-running the code executor.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4f7b1e9a3c2"
down_revision: Union[str, None] = "ceea2a027738"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "insight_charts", sa.Column("dataset_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "insight_charts",
        sa.Column(
            "color_map",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "insight_charts", sa.Column("series_color", sa.String(), nullable=True)
    )
    op.add_column(
        "insight_charts",
        sa.Column("divergent_colors", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("insight_charts", "divergent_colors")
    op.drop_column("insight_charts", "series_color")
    op.drop_column("insight_charts", "color_map")
    op.drop_column("insight_charts", "dataset_id")
