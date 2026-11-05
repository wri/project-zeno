"""add subscriptions table

Revision ID: b5e2a9c41d07
Revises: f3a8c1d5b204
Create Date: 2026-11-04 10:00:00.000000

Dashboard alert subscriptions: one row per dashboard, dataset and mode, and a
row means the mode is on. Both modes start off, so the table starts empty.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e2a9c41d07"
down_revision: Union[str, None] = "f3a8c1d5b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "subscriptions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dashboard_id", sa.UUID(), nullable=False),
        sa.Column("aoi_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "dataset",
            sa.Enum(
                "integrated_alerts",
                name="subscription_dataset",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "mode",
            sa.Enum(
                "email",
                "in-app",
                name="subscription_mode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_id"], ["dashboards.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["aoi_id"], ["dashboard_aois.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dashboard_id",
            "dataset",
            "mode",
            name="uq_subscriptions_dashboard_dataset_mode",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The enums are VARCHAR + CHECK, so there are no types to drop.
    op.drop_table("subscriptions")
