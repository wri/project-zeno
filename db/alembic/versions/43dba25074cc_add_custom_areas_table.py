"""add_custom_areas_table

Revision ID: 43dba25074cc
Revises: b2c5d0a31a8b
Create Date: 2025-07-22 15:29:59.683475

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

# revision identifiers, used by Alembic.
revision: str = "43dba25074cc"
down_revision: Union[str, None] = "b2c5d0a31a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create PostGIS extension if it doesn't exist
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # Create custom_areas table
    op.create_table(
        "custom_areas",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="GEOMETRY", srid=4326),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes
    op.create_index("idx_custom_areas_user_id", "custom_areas", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes first
    op.drop_index("idx_custom_areas_geometry")
    op.drop_index("idx_custom_areas_user_id")

    # Drop table
    op.drop_table("custom_areas")

    # Don't drop PostGIS extension as it might be used by other tables
