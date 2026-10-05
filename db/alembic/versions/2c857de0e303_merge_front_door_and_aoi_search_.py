"""merge front door and aoi search migrations

Revision ID: 2c857de0e303
Revises: 5b7e2c9a1f40, 9f91079f0670
Create Date: 2026-10-02 11:15:04.357779

Joins the two heads that branched from a3e8c5d17f42: the front-door user
columns (9cb8d618faf9 -> 9f91079f0670) and the AOI search schema
(5b7e2c9a1f40). The branches touch different tables, so the merge itself
changes nothing.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "2c857de0e303"
down_revision: Union[str, None] = ("5b7e2c9a1f40", "9f91079f0670")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
