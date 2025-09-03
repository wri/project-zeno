"""merge machine users and has_profile migrations

Revision ID: e092075cb11b
Revises: 08eca0bda924, 8f636b664598
Create Date: 2025-09-03 18:00:57.505369

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e092075cb11b'
down_revision: Union[str, None] = ('08eca0bda924', '8f636b664598')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
