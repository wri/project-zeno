"""merge insights and drop_whitelisted_users heads

Revision ID: 73c0c72faa9e
Revises: 75841e9932e5, f2a9c8d1e7b4
Create Date: 2026-05-12 14:12:15.326825

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "73c0c72faa9e"
down_revision: Union[str, None] = ("75841e9932e5", "f2a9c8d1e7b4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
