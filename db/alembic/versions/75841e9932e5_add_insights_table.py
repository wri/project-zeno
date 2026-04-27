"""add_insights_table

Revision ID: 75841e9932e5
Revises: ab07f4a240eb
Create Date: 2026-04-15 14:40:53.441251

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "75841e9932e5"
down_revision: Union[str, None] = "ab07f4a240eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insights",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("insight_text", sa.String(), nullable=False),
        sa.Column(
            "follow_up_suggestions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "codeact_types",
            sa.ARRAY(sa.String()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "codeact_contents",
            sa.ARRAY(sa.String()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "is_public",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "insight_charts",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("insight_id", sa.UUID(), nullable=False),
        sa.Column(
            "position", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("chart_type", sa.String(), nullable=False),
        sa.Column("x_axis", sa.String(), server_default="", nullable=False),
        sa.Column("y_axis", sa.String(), server_default="", nullable=False),
        sa.Column(
            "color_field", sa.String(), server_default="", nullable=False
        ),
        sa.Column(
            "stack_field", sa.String(), server_default="", nullable=False
        ),
        sa.Column(
            "group_field", sa.String(), server_default="", nullable=False
        ),
        sa.Column(
            "series_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "chart_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["insight_id"], ["insights.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_insights_thread_id", "insights", ["thread_id"])
    op.create_index("idx_insights_user_id", "insights", ["user_id"])
    op.create_index(
        "idx_insight_charts_insight_id",
        "insight_charts",
        ["insight_id"],
    )
    op.create_index(
        "idx_insight_charts_insight_position",
        "insight_charts",
        ["insight_id", "position"],
    )


def downgrade() -> None:
    op.drop_index("idx_insight_charts_insight_position")
    op.drop_index("idx_insight_charts_insight_id")
    op.drop_table("insight_charts")
    op.drop_index("idx_insights_user_id")
    op.drop_index("idx_insights_thread_id")
    op.drop_table("insights")
