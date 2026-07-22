"""add language_code to insights

Revision ID: b7d4a1f9c3e2
Revises: ceea2a027738
Create Date: 2026-07-22 00:00:00.000000

ISO 639-1 code the insight text/charts were generated in, resolved per-turn
from the conversation (see src.agent.language.resolve_language). Null for
insights persisted before this field existed, and for insights created via
the deterministic job path where no conversation language is available.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4a1f9c3e2"
down_revision: Union[str, None] = "ceea2a027738"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "insights",
        sa.Column("language_code", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("insights", "language_code")
