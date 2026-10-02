"""add users.terms_accepted_at and users.terms_version

Revision ID: 9cb8d618faf9
Revises: a3e8c5d17f42
Create Date: 2026-09-30 12:00:00.000000

Records which version of the terms a person accepted and when. The server
sets ``terms_accepted_at`` whenever ``PATCH /api/auth/profile`` carries a
``terms_version``; clients never supply the timestamp. Both columns are NULL
for anyone who has not accepted through the consent screen. There is no
backfill: people who completed the old onboarding form (``has_profile``)
ticked the terms box there, and the frontend treats that as acceptance.

The timestamp is timezone-aware on purpose. It is a legal audit record, so
it must not depend on the server's local clock.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9cb8d618faf9"
down_revision: Union[str, None] = "a3e8c5d17f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "terms_accepted_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "users",
        sa.Column("terms_version", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "terms_version")
    op.drop_column("users", "terms_accepted_at")
