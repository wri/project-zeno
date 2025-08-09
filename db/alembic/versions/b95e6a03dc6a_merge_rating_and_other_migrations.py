"""merge rating and other migrations

Revision ID: b95e6a03dc6a
Revises: 4d560a99b2c8, bea47fc66d31
Create Date: 2025-08-07 15:22:40.287340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b95e6a03dc6a'
down_revision: Union[str, None] = ('4d560a99b2c8', 'bea47fc66d31')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
