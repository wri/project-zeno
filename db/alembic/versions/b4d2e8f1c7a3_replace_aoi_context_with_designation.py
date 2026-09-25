"""replace aois.context with aois.designation

Revision ID: b4d2e8f1c7a3
Revises: 9c4e1d7f2a60
Create Date: 2026-09-25 12:00:00.000000

``aois.context`` (the parents, designation and country that follow a place's
own name) was stored but nothing read it: it only fed ``search_tsv`` at
build time, which ``build-aois`` now derives without storing. What the name
vector needs stored is the designation alone (WDPA ``desig_eng``, LandMark
``category``; NULL for the other sources), so that column replaces it. See
docs/aoi-full-text-search.md.

Both statements are instant: dropping a column only marks it, and adding a
nullable column without a default rewrites nothing. The column is filled by
the next ``build-aois``, which the deploy that ships the search rewrite
already requires right after the migrate Job.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d2e8f1c7a3"
down_revision: Union[str, None] = "9c4e1d7f2a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("aois", "context")
    op.add_column("aois", sa.Column("designation", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("aois", "designation")
    op.add_column("aois", sa.Column("context", sa.String(), nullable=True))
