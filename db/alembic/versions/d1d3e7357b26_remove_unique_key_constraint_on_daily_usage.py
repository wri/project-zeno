"""Remove unique constraint on id column from daily_usage table

Revision ID: d1d3e7357b26
Revises: 14bd7b5fb4a1
Create Date: 2025-07-30 09:34:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "d1d3e7357b26"
down_revision = "14bd7b5fb4a1"
branch_labels = None
depends_on = None


def upgrade():
    # Drop the unique constraint on 'id' column if it exists

    op.execute(
        """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'daily_usage_id_key'
              AND conrelid = 'daily_usage'::regclass
        ) THEN
            ALTER TABLE daily_usage DROP CONSTRAINT daily_usage_id_key;
        END IF;
    END
    $$;
    """
    )


def downgrade():
    # Recreate the unique constraint on 'id' column
    op.create_unique_constraint("daily_usage_id_key", "daily_usage", ["id"])
