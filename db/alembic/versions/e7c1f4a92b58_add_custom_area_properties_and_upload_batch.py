"""add custom_areas properties and upload_batch_id

Revision ID: e7c1f4a92b58
Revises: d4a1c7b93e02
Create Date: 2026-08-29 12:00:00.000000

``properties`` carries the non-geometry attributes of an uploaded feature and is
projected into ``aois.properties`` by the custom-area mirror. ``upload_batch_id``
groups the rows created by one file upload; a drawn area leaves it null. No
index on ``upload_batch_id`` yet — nothing queries by it.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "e7c1f4a92b58"
down_revision: Union[str, None] = "d4a1c7b93e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "custom_areas",
        sa.Column("properties", JSONB, nullable=True),
    )
    op.add_column(
        "custom_areas",
        sa.Column("upload_batch_id", UUID, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("custom_areas", "upload_batch_id")
    op.drop_column("custom_areas", "properties")
