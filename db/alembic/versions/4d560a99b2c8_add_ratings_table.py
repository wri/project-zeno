"""add_ratings_table

Revision ID: 4d560a99b2c8
Revises: 8182f6394c44
Create Date: 2025-07-24 15:25:45.904863

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4d560a99b2c8"
down_revision: Union[str, None] = "8182f6394c44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ratings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["threads.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "thread_id",
            "trace_id",
            name="uq_user_thread_trace_rating",
        ),
    )
    op.create_index("idx_ratings_user_id", "ratings", ["user_id"])
    op.create_index("idx_ratings_thread_id", "ratings", ["thread_id"])
    op.create_index("idx_ratings_trace_id", "ratings", ["trace_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_ratings_trace_id", "ratings")
    op.drop_index("idx_ratings_thread_id", "ratings")
    op.drop_index("idx_ratings_user_id", "ratings")
    op.drop_table("ratings")
