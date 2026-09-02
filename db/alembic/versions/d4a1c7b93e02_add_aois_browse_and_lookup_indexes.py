"""add aois browse and lookup indexes

Revision ID: d4a1c7b93e02
Revises: d4f7b1e9a3c2
Create Date: 2026-07-30 18:20:00.000000

This migration adds two partial indexes to ``aois``. Neither index holds
deprecated rows.

``idx_aois_name_live`` supports browse mode. Browse mode sorts by ``name``,
``source`` and ``source_id``. Without the index, each request scans the table and
then sorts it. This index also excludes disputed rows, as ``idx_aois_name_trgm``
does.

``idx_aois_source_subtype_source_id`` supports subregion expansion and the
global-country query. Both match ``source`` and ``subtype``. Subregion expansion
also matches a prefix of ``source_id``. ``text_pattern_ops`` makes that prefix an
index range. The default collation cannot do this, so
``uq_aois_source_source_id_live`` cannot serve the prefix. The index keeps
disputed rows, because the subregion query does not exclude them.

Both indexes are small and build quickly. Therefore they use ``CREATE INDEX``,
not ``CREATE INDEX CONCURRENTLY``.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4a1c7b93e02"
down_revision: Union[str, None] = "d4f7b1e9a3c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "idx_aois_name_live",
        "aois",
        ["name", "source", "source_id"],
        postgresql_where=sa.text("NOT is_disputed AND NOT is_deprecated"),
    )
    op.create_index(
        "idx_aois_source_subtype_source_id",
        "aois",
        ["source", "subtype", "source_id"],
        postgresql_ops={"source_id": "text_pattern_ops"},
        postgresql_where=sa.text("NOT is_deprecated"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_aois_source_subtype_source_id", table_name="aois")
    op.drop_index("idx_aois_name_live", table_name="aois")
