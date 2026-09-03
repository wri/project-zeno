"""add dashboard_sections.config

Revision ID: c4d8b1e60a25
Revises: a3f5c7e1b204
Create Date: 2026-09-03 00:00:00.000000

What a recipe built a section from — the window it covers, and the parameters
it was given. A hand-composed section keeps the empty default, so no backfill
is needed.

This is what a refresh reads to know what to replace, and what the API
reports so a reader can be told which period is on screen. Before it, the
only record of the period was inside the widgets' own configs, which meant
sniffing a tile layer's dates to answer a question about the section.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4d8b1e60a25"
down_revision: Union[str, None] = "a3f5c7e1b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
