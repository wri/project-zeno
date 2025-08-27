"""Add IPAddress column to daily_usage table

Revision ID: 831ad1e71a80
Revises: 32753a3e09e0
Create Date: 2025-08-21 08:57:10.248625

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "831ad1e71a80"
down_revision: Union[str, None] = "32753a3e09e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
