"""add aoi search columns, name variants and token table

Revision ID: 5b7e2c9a1f40
Revises: e7c1f4a92b58
Create Date: 2026-09-18 16:10:00.000000

Schema only. The new ``aois`` columns are nullable and empty here, and the two
new tables are empty. ``build-aois`` fills them, and the custom-area mirror
keeps them current. Nothing reads them until the search rewrite ships, so the
current trigram search keeps working unchanged through this migration.

The ``unaccent`` extension and the ``aoi_search`` text search configuration
come from :mod:`src.shared.aoi_search_sql`, which the test fixture also runs,
so the two schemas cannot drift.

Indexes are plain ``CREATE INDEX``: the indexed columns are NULL on every
row at this point, so each build is small.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from src.shared.aoi_search_sql import SEARCH_DDL

# revision identifiers, used by Alembic.
revision: str = "5b7e2c9a1f40"
down_revision: Union[str, None] = "e7c1f4a92b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIVE = sa.text("NOT is_disputed AND NOT is_deprecated")


def upgrade() -> None:
    """Upgrade schema."""
    for statement in SEARCH_DDL:
        op.execute(statement)

    # --- aois: structured name columns -------------------------------------
    op.add_column("aois", sa.Column("leaf", sa.String(), nullable=True))
    op.add_column("aois", sa.Column("leaf_norm", sa.String(), nullable=True))
    op.add_column("aois", sa.Column("context", sa.String(), nullable=True))
    op.add_column(
        "aois", sa.Column("search_tsv", postgresql.TSVECTOR(), nullable=True)
    )
    # text_pattern_ops serves both `=` and a LIKE 'prefix%' range under any
    # collation, so one btree covers the exact tier and autocomplete.
    op.create_index(
        "idx_aois_leaf_norm",
        "aois",
        ["leaf_norm"],
        postgresql_ops={"leaf_norm": "text_pattern_ops"},
        postgresql_where=_LIVE,
    )
    op.create_index(
        "idx_aois_search_tsv",
        "aois",
        ["search_tsv"],
        postgresql_using="gin",
        postgresql_where=_LIVE,
    )

    # --- aoi_names: one row per searchable name variant ----------------------
    op.create_table(
        "aoi_names",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("aoi_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_norm", sa.String(), nullable=False),
        # primary | variant | native | international
        sa.Column("kind", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["aoi_id"], ["aois.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # The upsert target: a rebuild inserts every variant again and the
        # duplicates conflict here.
        sa.UniqueConstraint(
            "aoi_id", "kind", "name_norm", name="uq_aoi_names_aoi_kind_norm"
        ),
    )
    op.create_index(
        "idx_aoi_names_name_norm",
        "aoi_names",
        ["name_norm"],
        postgresql_ops={"name_norm": "text_pattern_ops"},
    )

    # --- aoi_search_tokens: distinct lexemes for typo correction -------------
    op.create_table(
        "aoi_search_tokens",
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("ndoc", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index(
        "idx_aoi_search_tokens_trgm",
        "aoi_search_tokens",
        ["token"],
        postgresql_using="gin",
        postgresql_ops={"token": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("aoi_search_tokens")
    op.drop_table("aoi_names")
    op.drop_index("idx_aois_search_tsv", table_name="aois")
    op.drop_index("idx_aois_leaf_norm", table_name="aois")
    op.drop_column("aois", "search_tsv")
    op.drop_column("aois", "context")
    op.drop_column("aois", "leaf_norm")
    op.drop_column("aois", "leaf")
    # The extension and the text search configuration stay: dropping them
    # would fail if anything else came to depend on them, and they are inert.
