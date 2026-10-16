"""add dashboard_sections.template

Revision ID: a3e8c5d17f42
Revises: e7c1f4a92b58
Create Date: 2026-09-23 12:00:00.000000

``template`` records how an analysis template built the section: the
template name, the period and the build time. It is NULL for a section that
a user or the agent composed. No code reads it for access or edit rules. An
edited section keeps it, because it tells how the section started, not what
it contains now.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "a3e8c5d17f42"
down_revision: Union[str, None] = "e7c1f4a92b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "dashboard_sections",
        sa.Column("template", JSONB, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("dashboard_sections", "template")
