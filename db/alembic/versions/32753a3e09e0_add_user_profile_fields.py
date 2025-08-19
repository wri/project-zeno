"""add user profile fields

Revision ID: 32753a3e09e0
Revises: a7e4f8b2c9d1
Create Date: 2025-08-19 18:07:13.385477

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32753a3e09e0'
down_revision: Union[str, None] = 'a7e4f8b2c9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new profile fields to users table
    op.add_column('users', sa.Column('first_name', sa.String(), nullable=True))
    op.add_column('users', sa.Column('last_name', sa.String(), nullable=True))
    op.add_column('users', sa.Column('profile_description', sa.String(), nullable=True))
    op.add_column('users', sa.Column('sector_code', sa.String(), nullable=True))
    op.add_column('users', sa.Column('role_code', sa.String(), nullable=True))
    op.add_column('users', sa.Column('job_title', sa.String(), nullable=True))
    op.add_column('users', sa.Column('company_organization', sa.String(), nullable=True))
    op.add_column('users', sa.Column('country_code', sa.String(), nullable=True))
    op.add_column('users', sa.Column('preferred_language_code', sa.String(), nullable=True))
    op.add_column('users', sa.Column('gis_expertise_level', sa.String(), nullable=True))
    op.add_column('users', sa.Column('areas_of_interest', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove profile fields from users table
    op.drop_column('users', 'areas_of_interest')
    op.drop_column('users', 'gis_expertise_level')
    op.drop_column('users', 'preferred_language_code')
    op.drop_column('users', 'country_code')
    op.drop_column('users', 'company_organization')
    op.drop_column('users', 'job_title')
    op.drop_column('users', 'role_code')
    op.drop_column('users', 'sector_code')
    op.drop_column('users', 'profile_description')
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')
