"""add_machine_users_and_api_keys

Revision ID: 08eca0bda924
Revises: 95d9d8ca3bf1
Create Date: 2025-09-01 09:06:34.832320

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "08eca0bda924"
down_revision: Union[str, None] = "95d9d8ca3bf1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add machine user fields to users table
    op.add_column(
        "users", sa.Column("machine_description", sa.String(), nullable=True)
    )

    # Create machine_user_keys table
    op.create_table(
        "machine_user_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("key_name", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("key_prefix"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for performance
    op.create_index(
        "idx_machine_user_keys_prefix", "machine_user_keys", ["key_prefix"]
    )
    op.create_index(
        "idx_machine_user_keys_user_id", "machine_user_keys", ["user_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index("idx_machine_user_keys_user_id", "machine_user_keys")
    op.drop_index("idx_machine_user_keys_prefix", "machine_user_keys")

    # Drop machine_user_keys table
    op.drop_table("machine_user_keys")

    # Remove machine user fields from users table
    op.drop_column("users", "machine_description")

    # Note: Cannot easily remove enum value from PostgreSQL enum type
    # The 'machine' value will remain but be unused
