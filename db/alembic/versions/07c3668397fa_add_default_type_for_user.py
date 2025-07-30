"""Add default type for user

Revision ID: 07c3668397fa
Revises: 14bd7b5fb4a1
Create Date: 2025-07-30 10:43:03.933429

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "07c3668397fa"
down_revision: Union[str, None] = "14bd7b5fb4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE users SET user_type = 'regular' WHERE user_type IS NULL")
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
