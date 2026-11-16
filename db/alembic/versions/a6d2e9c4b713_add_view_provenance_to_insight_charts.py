"""add curated view provenance to insight_charts

Revision ID: a6d2e9c4b713
Revises: b5e2a9c41d07
Create Date: 2026-11-10 00:00:00.000000

A curated chart is built by a named view (src/api/services/charts/views.py).
``view_id`` and ``view_revision`` record which view built a stored chart, and
at which revision. Both are null for a chart that the code executor made, and
for every chart stored before this migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6d2e9c4b713"
down_revision: Union[str, None] = "b5e2a9c41d07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "insight_charts", sa.Column("view_id", sa.String(), nullable=True)
    )
    op.add_column(
        "insight_charts",
        sa.Column("view_revision", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("insight_charts", "view_revision")
    op.drop_column("insight_charts", "view_id")
