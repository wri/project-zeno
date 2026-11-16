"""add subscriptions table

Revision ID: b5e2a9c41d07
Revises: f3a8c1d5b204
Create Date: 2026-11-04 10:00:00.000000

Dashboard subscriptions: one row per dashboard, dataset and channel, and a
row means subscribed. Email is the only channel and nobody starts
subscribed, so the table starts empty.

Also marks which dashboards are eligible for subscription: those with an
integrated alerts widget, either an insight chart or a map or alerts layer.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e2a9c41d07"
down_revision: Union[str, None] = "f3a8c1d5b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The integrated alerts dataset id in the dataset catalog.
INTEGRATED_ALERTS_DATASET_ID = 11


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "dashboards",
        sa.Column(
            "eligible_for_subscription",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE dashboards SET eligible_for_subscription = true
            WHERE EXISTS (
                SELECT 1
                FROM dashboard_widgets AS widget
                LEFT JOIN insight_charts AS chart
                    ON chart.insight_id = widget.insight_id
                WHERE widget.dashboard_id = dashboards.id
                AND (
                    chart.dataset_id = :dataset_id
                    OR widget.config -> 'dataset' ->> 'dataset_id'
                        = CAST(:dataset_id AS text)
                )
            )
            """
        ).bindparams(dataset_id=INTEGRATED_ALERTS_DATASET_ID)
    )
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
            "channel",
            sa.Enum(
                "email",
                name="subscription_channel",
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
            "channel",
            name="uq_subscriptions_dashboard_dataset_channel",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The enums are VARCHAR + CHECK, so there are no types to drop.
    op.drop_table("subscriptions")
    op.drop_column("dashboards", "eligible_for_subscription")
