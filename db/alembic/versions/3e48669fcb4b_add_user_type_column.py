"""add user type column

Revision ID: 3e48669fcb4b
Revises: 1ff3f25a8b68
Create Date: 2025-07-15 17:10:32.345474

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3e48669fcb4b"
down_revision: Union[str, None] = "1ff3f25a8b68"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users", sa.Column("user_type", sa.String(), nullable=True, default="regular")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "user_type")
