"""merge thread name and custom areas branches

Revision ID: 169f57df5479
Revises: 8182f6394c44, d8398e3c6f00
Create Date: 2025-07-28 15:34:28.501483

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "169f57df5479"
down_revision: Union[str, None] = ("8182f6394c44", "d8398e3c6f00")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
