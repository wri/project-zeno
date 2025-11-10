"""add_pro_user_type

Revision ID: 56ff882d4e7c
Revises: cccd7f25f096
Create Date: 2025-11-10 18:23:38.298020

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "56ff882d4e7c"
down_revision: Union[str, None] = "cccd7f25f096"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Add 'pro' as a valid user_type value.
    No schema changes needed since user_type is a String column.
    The UserType enum in the code now accepts 'pro' as a valid value.
    """
    # No schema changes needed - user_type is a String column
    # that can accept any value. The validation happens in the
    # application layer via the UserType enum.
    pass


def downgrade() -> None:
    """Downgrade schema.

    Remove 'pro' user type support.
    Note: Any existing users with user_type='pro' would need to be
    updated to a different type before this downgrade.
    """
    # Optionally update any 'pro' users to 'regular'
    # This is commented out to avoid data loss - handle manually if needed
    # op.execute("UPDATE users SET user_type = 'regular' WHERE user_type = 'pro'")
    pass
