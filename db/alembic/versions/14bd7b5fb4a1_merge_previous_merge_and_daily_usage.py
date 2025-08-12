"""Merge previous merge and daily usage

Revision ID: 14bd7b5fb4a1
Revises: 169f57df5479, 3e48669fcb4b
Create Date: 2025-07-29 10:22:46.748359

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "14bd7b5fb4a1"
down_revision: Union[str, None] = ("169f57df5479", "3e48669fcb4b")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
