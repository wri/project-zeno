"""add thread name column to threads table

Revision ID: 8182f6394c44
Revises: b2c5d0a31a8b
Create Date: 2025-07-22 09:38:17.343380

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8182f6394c44"
down_revision: Union[str, None] = "b2c5d0a31a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("threads", sa.Column("name", sa.String(), nullable=True))

    op.execute("UPDATE threads SET name = 'Unnamed Thread' WHERE name IS NULL")
    pass


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("threads", "name")
    pass
