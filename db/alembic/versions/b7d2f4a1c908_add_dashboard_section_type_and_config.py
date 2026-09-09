"""add dashboard_sections.type and dashboard_sections.config

Revision ID: b7d2f4a1c908
Revises: c9f1a2b3d4e5
Create Date: 2026-09-09 00:00:00.000000

Two columns that turn a section into something a builder can own.

``type`` records how the section was built: "default" for a user- or
agent-composed group, or the name of the analysis template that wrote it in
one piece. ``config`` records what that template built it from — the window
it covers and the parameters it was given — so a refresh knows what to
replace and a reader can be told which period is on screen without sniffing
the dates out of a widget's tile layer.

Both take a server default, so every existing row is correct with no data
migration. A templated section is read-only; that rule lives in the
application (``analysis_templates.registry``), not here, so adding a
template or an exception stays a code change.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7d2f4a1c908"
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
    op.add_column(
        "dashboard_sections",
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("dashboard_sections", "config")
    op.drop_column("dashboard_sections", "type")
