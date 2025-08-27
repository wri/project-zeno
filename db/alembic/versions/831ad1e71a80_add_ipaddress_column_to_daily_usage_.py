"""Add IPAddress column to daily_usage table

Revision ID: 831ad1e71a80
Revises: 32753a3e09e0
Create Date: 2025-08-21 08:57:10.248625

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "831ad1e71a80"
down_revision: Union[str, None] = "32753a3e09e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add ip_address column to daily_usage table
    op.add_column(
        "daily_usage", sa.Column("ip_address", sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""

    # Remove ip_address column from daily_usage table
    op.drop_column("daily_usage", "ip_address")

