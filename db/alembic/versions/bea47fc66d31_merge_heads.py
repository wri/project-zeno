"""merge heads

Revision ID: bea47fc66d31
Revises: 07c3668397fa, d1d3e7357b26
Create Date: 2025-08-06 17:08:50.426513

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "bea47fc66d31"
down_revision: Union[str, None] = ("07c3668397fa", "d1d3e7357b26")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
