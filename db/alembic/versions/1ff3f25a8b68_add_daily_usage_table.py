"""add daily usage table

Revision ID: 1ff3f25a8b68
Revises: b2c5d0a31a8b
Create Date: 2025-07-14 13:21:00.024936

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ff3f25a8b68'
down_revision: Union[str, None] = 'b2c5d0a31a8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "daily_usage",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", "date"),
        sa.UniqueConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("daily_usage")
    pass
