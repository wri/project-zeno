"""add comment field to ratings

Revision ID: c1d2e3f4a5b6
Revises: b95e6a03dc6a
Create Date: 2025-08-07 15:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b95e6a03dc6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add comment field to ratings table."""
    op.add_column('ratings', sa.Column('comment', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove comment field from ratings table."""
    op.drop_column('ratings', 'comment')