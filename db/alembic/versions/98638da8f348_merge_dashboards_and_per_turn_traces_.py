"""merge dashboards and per-turn traces heads

Revision ID: 98638da8f348
Revises: b7e4d9a2c1f8, c2e8b4d1f6a7
Create Date: 2026-07-21 18:55:45.309504

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "98638da8f348"
down_revision: Union[str, None] = ("b7e4d9a2c1f8", "c2e8b4d1f6a7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
