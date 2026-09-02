"""add dashboard_sections.type

Revision ID: a3f5c7e1b204
Revises: c9f1a2b3d4e5
Create Date: 2026-09-02 00:00:00.000000

A section carries how it was built: "default" for a user- or agent-composed
group, or a recipe name such as "nrt-monitoring" for a section a builder
wrote in one piece. The server default backfills every existing row, so no
data migration is needed. Recipe sections are read-only; that rule lives in
the application (``dashboard_writer.SEALED_SECTION_TYPES``), not here, so
adding a type or an exception stays a code change.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f5c7e1b204"
down_revision: Union[str, None] = "c9f1a2b3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dashboard_sections",
        sa.Column(
            "type",
            sa.String(),
            nullable=False,
            server_default="default",
        ),
    )


def downgrade() -> None:
    op.drop_column("dashboard_sections", "type")
