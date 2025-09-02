"""add_whitelisted_users_table

Revision ID: 95d9d8ca3bf1
Revises: 831ad1e71a80
Create Date: 2025-09-01 16:44:44.206285

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "95d9d8ca3bf1"
down_revision: Union[str, None] = "831ad1e71a80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "whitelisted_users",
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("email"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("whitelisted_users")
