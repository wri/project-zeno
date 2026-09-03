"""add dashboard_sections table and dashboard_widgets.section_id

Revision ID: c9f1a2b3d4e5
Revises: d4a1c7b93e02
Create Date: 2026-08-31 00:00:00.000000

Sections give a dashboard one level of hierarchy. A widget either belongs to
a section or stays ungrouped (``section_id`` NULL), so existing widgets need
no backfill. Deleting a section keeps its widgets and ungroups them
(ON DELETE SET NULL) — content is never dropped by a grouping change.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c9f1a2b3d4e5"
down_revision: Union[str, None] = "d4a1c7b93e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dashboard_sections",
        sa.Column(
            "id",
            postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dashboard_id", postgresql.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dashboard_sections_dashboard_id",
        "dashboard_sections",
        ["dashboard_id"],
    )
    op.add_column(
        "dashboard_widgets",
        sa.Column("section_id", postgresql.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_dashboard_widgets_section_id",
        "dashboard_widgets",
        "dashboard_sections",
        ["section_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_dashboard_widgets_section_id",
        "dashboard_widgets",
        type_="foreignkey",
    )
    op.drop_column("dashboard_widgets", "section_id")
    op.drop_index(
        "ix_dashboard_sections_dashboard_id",
        table_name="dashboard_sections",
    )
    op.drop_table("dashboard_sections")
