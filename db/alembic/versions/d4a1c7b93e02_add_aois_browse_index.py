"""add aois browse index

Revision ID: d4a1c7b93e02
Revises: ceea2a027738
Create Date: 2026-07-30 18:20:00.000000

Browse mode (``GET /api/aois`` with no ``name``) orders by
``name, source, source_id`` across every source. Without a matching index that
is a full scan plus a top-N sort of the whole table on every request. Measured
on an 849k-row copy: 88ms -> 0.1ms for the first page, 3.4ms at offset 5000,
and the sort node disappears.

Index-only on the sort key, partial on the same predicate the search query
carries, so disputed/deprecated rows stay out of it -- matching
``idx_aois_name_trgm``. One index serves both the all-sources and the
single-source browse (the planner uses it for ``source = ANY(...)`` as an index
filter), so no separate source-leading index is needed.

Build cost measured at ~1s / 50MB for 849k rows: fine for the blocking migrate
Job, which is why this is a plain CREATE INDEX rather than CONCURRENTLY.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4a1c7b93e02"
down_revision: Union[str, None] = "ceea2a027738"
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_aois_name_live", table_name="aois")
