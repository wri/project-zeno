"""add statistics.canopy_cover and insights.statistics_ids_exact

Revision ID: 5b7e1c3a9d42
Revises: a6d2e9c4b713
Create Date: 2026-11-23 14:40:00.000000

``statistics.canopy_cover`` is the threshold a pull sent to the analytics
API; ``parameters`` keeps meaning what the selection set. Nullable with no
backfill: NULL means a dataset without a threshold, or a pull stored before
this revision.

``insights.statistics_ids_exact`` says whether ``statistics_ids`` lists
exactly the pulls the insight was computed from. Insights saved before this
revision linked every pull of their thread (or none, for /api/analyze and
dashboard templates), so every existing row is false and its links are not
read as the insight's inputs.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b7e1c3a9d42"
down_revision: Union[str, None] = "a6d2e9c4b713"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "statistics", sa.Column("canopy_cover", sa.Integer(), nullable=True)
    )
    op.add_column(
        "insights",
        sa.Column(
            "statistics_ids_exact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("insights", "statistics_ids_exact")
    op.drop_column("statistics", "canopy_cover")
