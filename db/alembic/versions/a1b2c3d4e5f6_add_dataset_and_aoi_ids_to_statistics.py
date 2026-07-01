"""add dataset_id and aoi_ids/aoi_sources to statistics

Revision ID: a1b2c3d4e5f6
Revises: e0e882fba200
Create Date: 2026-06-30 00:00:00.000000

Persist the catalog dataset id and the src_ids (with their sources) of the
analysed AOIs alongside the existing human-readable names, so the insights
listing endpoint can filter by stable ids instead of names. src_id is only
unique per source, so aoi_sources is stored parallel to aoi_ids. All columns
are nullable / defaulted so existing rows stay valid without backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e0e882fba200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "statistics",
        sa.Column("dataset_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "statistics",
        sa.Column(
            "aoi_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "statistics",
        sa.Column(
            "aoi_sources",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )

    # Backfill dataset_id for existing rows from their dataset_name. The mapping
    # is a self-contained snapshot of the dataset catalog
    # (src/agent/datasets/catalog/*.yml) at migration time -- deliberately NOT
    # imported from app code so the migration stays offline and stable. Rows
    # whose dataset_name predates a catalog rename simply stay NULL. aoi_ids /
    # aoi_sources are intentionally left at their [] default: src_id and source
    # were never persisted for historical rows and cannot be reliably recovered.
    op.execute(
        """
        UPDATE statistics AS s
        SET dataset_id = m.dataset_id
        FROM (VALUES
            ('Global all ecosystem disturbance alerts (DIST-ALERT)', 0),
            ('Global land cover', 1),
            ('Global natural/semi-natural grassland extent', 2),
            ('SBTN Natural Lands Map', 3),
            ('Tree cover loss', 4),
            ('Tree cover gain', 5),
            ('Forest greenhouse gas net flux', 6),
            ('Tree cover', 7),
            ('Tree cover loss by dominant driver', 8),
            ('Deforestation (sLUC) Emission Factors by Agricultural Crop', 9),
            ('Tree cover loss due to fires', 10),
            ('Integrated alerts', 11)
        ) AS m(dataset_name, dataset_id)
        WHERE s.dataset_name = m.dataset_name
          AND s.dataset_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("statistics", "aoi_sources")
    op.drop_column("statistics", "aoi_ids")
    op.drop_column("statistics", "dataset_id")
