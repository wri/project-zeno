"""add dashboards, dashboard_aois and dashboard_widgets tables

Revision ID: b7e4d9a2c1f8
Revises: a1b2c3d4e5f6
Create Date: 2026-07-02 00:00:00.000000

A dashboard is a persistent, curated collection of insights, layers and AOIs.
Widgets only *reference* insights (FK with ON DELETE CASCADE so deleting an
insight silently drops widgets pointing at it) plus presentation config;
dashboard AOIs store the canonical (source, src_id, subtype) address plus a
denormalized display name — never geometry. The AOI join table supports
multiple areas from day one; the MVP single-area constraint lives in API
validation, not the schema.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7e4d9a2c1f8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column(
            "id",
            postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "dashboard_aois",
        sa.Column(
            "id",
            postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dashboard_id", postgresql.UUID(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("src_id", sa.String(), nullable=False),
        sa.Column("subtype", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dashboard_id",
            "source",
            "src_id",
            name="uq_dashboard_aois_dashboard_source_src_id",
        ),
    )
    op.create_table(
        "dashboard_widgets",
        sa.Column(
            "id",
            postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dashboard_id", postgresql.UUID(), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("widget_type", sa.String(), nullable=False),
        sa.Column("insight_id", postgresql.UUID(), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"]),
        sa.ForeignKeyConstraint(
            ["insight_id"], ["insights.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # An insight appears on a dashboard at most once, so retries cannot
    # duplicate widgets. Partial: map/text widgets (insight_id NULL) exempt.
    op.create_index(
        "uq_dashboard_widgets_dashboard_insight",
        "dashboard_widgets",
        ["dashboard_id", "insight_id"],
        unique=True,
        postgresql_where=sa.text("widget_type = 'insight'"),
    )


def downgrade() -> None:
    op.drop_table("dashboard_widgets")
    op.drop_table("dashboard_aois")
    op.drop_table("dashboards")
