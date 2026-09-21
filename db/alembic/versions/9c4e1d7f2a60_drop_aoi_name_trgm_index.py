"""drop the composite-name trigram indexes

Revision ID: 9c4e1d7f2a60
Revises: 5b7e2c9a1f40
Create Date: 2026-09-21 12:00:00.000000

Search no longer reads ``aois.name`` with pg_trgm: it reads the leaf, the
name variants and the tsvector that ``5b7e2c9a1f40`` added (see
docs/aoi-full-text-search.md). ``idx_aois_name_trgm`` (about 200 MB) has no
reader left, and neither do the trigram indexes the ingest scripts used to
build on the ``geometries_*`` staging tables, which nothing has read since
the read path moved to ``aois``. Those staging tables live outside Alembic,
so their indexes are dropped IF EXISTS.

Dropping an index is instant. The downgrade rebuilds only the ``aois`` index,
because only the search of the previous revision reads it, and a rebuild
over the full table takes minutes; run a downgrade outside the blocking
migrate Job.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c4e1d7f2a60"
down_revision: Union[str, None] = "5b7e2c9a1f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STAGING_INDEXES = [
    "idx_geometries_gadm_name_gin",
    "idx_geometries_kba_name_gin",
    "idx_geometries_wdpa_name_gin",
    "idx_geometries_landmark_name_gin",
]


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("idx_aois_name_trgm", table_name="aois")
    for index in _STAGING_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index}")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index(
        "idx_aois_name_trgm",
        "aois",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
        postgresql_where=sa.text("NOT is_disputed AND NOT is_deprecated"),
    )
