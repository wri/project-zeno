"""Drop whitelisted_users table

Revision ID: f2a9c8d1e7b4
Revises: c1d2e3f4a5b6
Create Date: 2026-04-22 15:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a9c8d1e7b4"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("whitelisted_users")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "whitelisted_users",
        sa.Column("email", sa.String(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
