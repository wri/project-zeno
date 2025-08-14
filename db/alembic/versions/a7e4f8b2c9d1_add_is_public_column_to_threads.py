"""add is_public column to threads

Revision ID: a7e4f8b2c9d1
Revises: c1d2e3f4a5b6
Create Date: 2025-08-12 15:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7e4f8b2c9d1"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_public column to threads table."""
    op.add_column("threads", sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()))

    # Ensure all existing threads are set to private (redundant with server_default but explicit)
    op.execute("UPDATE threads SET is_public = FALSE WHERE is_public IS NULL")


def downgrade() -> None:
    """Remove is_public column from threads table."""
    op.drop_column("threads", "is_public")
