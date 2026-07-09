"""create unified aoi tables

Revision ID: ceea2a027738
Revises: a1b2c3d4e5f6
Create Date: 2026-07-08 14:34:50.155560

Schema only. The unified ``aois`` table and the ``user_aois`` relationship
join are created empty here; data is populated out-of-band by the idempotent
``build-aois`` CLI command (heavy work must not run in the blocking migrate
Job). No existing tables are touched -- this is purely additive, so the live
API keeps serving from ``geometries_*`` / ``custom_areas`` until the API PR.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

# revision identifiers, used by Alembic.
revision: str = "ceea2a027738"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # --- aois: unified AOI table -------------------------------------------
    op.create_table(
        "aois",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("subtype", sa.String(), nullable=False),
        # spatial_index=False: the GiST index is created explicitly below so
        # its name is controlled and not auto-emitted by geoalchemy2.
        sa.Column(
            "geometry",
            Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
            nullable=False,
        ),
        # [west, south, east, north]; precomputed, antimeridian-aware.
        sa.Column("bbox", sa.ARRAY(sa.Float()), nullable=True),
        sa.Column("area_km2", sa.Float(), nullable=True),
        sa.Column("iso3", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("admin_level", sa.SmallInteger(), nullable=True),
        sa.Column(
            "is_disputed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_deprecated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # One *live* version per logical id. Identical to a full unique today;
    # partial-on-not-deprecated leaves room for future versioning with no
    # constraint surgery. Also backs INSERT ... ON CONFLICT in build-aois.
    op.create_index(
        "uq_aois_source_source_id_live",
        "aois",
        ["source", "source_id"],
        unique=True,
        postgresql_where=sa.text("NOT is_deprecated"),
    )
    op.create_index(
        "idx_aois_geometry_gist",
        "aois",
        ["geometry"],
        postgresql_using="gist",
    )
    # Partial: disputed/deprecated rows are absent from the search index, so
    # excluding them from results costs nothing, yet they stay resolvable by
    # (source, source_id) / id for geometry fetches and analytics linkage.
    op.create_index(
        "idx_aois_name_trgm",
        "aois",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
        postgresql_where=sa.text("NOT is_disputed AND NOT is_deprecated"),
    )
    op.create_index(
        "idx_aois_iso3",
        "aois",
        ["iso3"],
        postgresql_using="gin",
    )
    op.create_index("idx_aois_source", "aois", ["source"])
    op.create_index("idx_aois_admin_level", "aois", ["admin_level"])
    op.create_index("idx_aois_created_by", "aois", ["created_by"])

    # --- user_aois: user<->AOI relationships -------------------------------
    op.create_table(
        "user_aois",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("aoi_id", sa.UUID(), nullable=False),
        sa.Column(
            "relationship",
            sa.Enum(
                "owner",
                "saved",
                name="aoi_relationship",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["aoi_id"], ["aois.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "aoi_id",
            "relationship",
            name="uq_user_aoi_relationship",
        ),
    )
    # Powers the custom-visibility semi-join and the saved-first sort.
    op.create_index(
        "idx_user_aois_user_rel_aoi",
        "user_aois",
        ["user_id", "relationship", "aoi_id"],
    )
    op.create_index("idx_user_aois_aoi_id", "user_aois", ["aoi_id"])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the child (FK -> aois) first; indexes drop with their tables.
    op.drop_table("user_aois")
    op.drop_table("aois")
    # Extensions are left in place -- they may be used by other tables.
