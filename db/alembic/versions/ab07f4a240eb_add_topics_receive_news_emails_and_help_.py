"""add topics, receive_news_emails, and help_test_features fields to users table

Revision ID: ab07f4a240eb
Revises: e092075cb11b
Create Date: 2025-09-10 15:08:17.650795

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab07f4a240eb'
down_revision: Union[str, None] = 'e092075cb11b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add topics field as String (JSON array of selected topic codes)
    op.add_column('users', sa.Column('topics', sa.String(), nullable=True))
    
    # Add boolean fields for user preferences
    op.add_column('users', sa.Column('receive_news_emails', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('help_test_features', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove the added columns
    op.drop_column('users', 'help_test_features')
    op.drop_column('users', 'receive_news_emails')
    op.drop_column('users', 'topics')
