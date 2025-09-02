"""add has_profile field to users table

Revision ID: 8f636b664598
Revises: 95d9d8ca3bf1
Create Date: 2025-09-02 16:57:45.873121

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f636b664598'
down_revision: Union[str, None] = '95d9d8ca3bf1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("has_profile", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "has_profile")
