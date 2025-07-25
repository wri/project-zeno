"""Replace geometry by geometries column

Revision ID: d8398e3c6f00
Revises: 43dba25074cc
Create Date: 2025-07-25 13:21:45.700129

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa
from geoalchemy2 import Geometry


# revision identifiers, used by Alembic.
revision: str = 'd8398e3c6f00'
down_revision: Union[str, None] = '43dba25074cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("custom_areas", "geometry")
    op.add_column(
        "custom_areas",
        sa.Column("geometries", postgresql.JSONB, nullable=False)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("custom_areas", "geometries")
    op.add_column(
        "custom_areas",
        sa.Column(
            "geometry",
            Geometry(geometry_type="GEOMETRY", srid=4326), nullable=False
        ),
    )
