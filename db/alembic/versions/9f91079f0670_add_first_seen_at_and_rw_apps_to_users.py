"""add users.first_seen_at and users.rw_apps

Revision ID: 9f91079f0670
Revises: 9cb8d618faf9
Create Date: 2026-10-02 12:00:00.000000

Records where a person came from when they first entered GNW.
``users.created_at`` is the Resource Watch account's ``createdAt``, so until
now nothing recorded the first GNW login. ``first_seen_at`` is the server
time of the login that created the row. ``rw_apps`` is the RW account's
``extraUserData.apps`` at that moment (``gfw`` for an existing Global Forest
Watch account). Both are written once, on insert, and never updated by a
later login. Both stay NULL for rows created before this migration, for
machine users, and (``rw_apps``) when RW sends no usable apps list.

``rw_apps`` is a native array, not JSON text like ``topics``, so analytics
can filter it in SQL. The GIN index serves the containment operators
(``rw_apps @> ARRAY['gfw']``); ``'gfw' = ANY(rw_apps)`` is equivalent but
cannot use it. The index lives only here, following the convention that
performance indexes are not declared on the ORM.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f91079f0670"
down_revision: Union[str, None] = "9cb8d618faf9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("rw_apps", sa.ARRAY(sa.Text()), nullable=True),
    )
    op.create_index(
        "idx_users_rw_apps",
        "users",
        ["rw_apps"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_users_rw_apps", table_name="users")
    op.drop_column("users", "rw_apps")
    op.drop_column("users", "first_seen_at")
