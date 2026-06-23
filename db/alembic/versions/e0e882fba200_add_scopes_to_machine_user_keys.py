"""add scopes to machine_user_keys

Revision ID: e0e882fba200
Revises: 8391583bd224
Create Date: 2026-06-22 00:00:00.000000

Per-key authorization scopes for machine API keys (e.g. ``traces:read``). A key
carrying a scope grants access to the matching endpoints without an elevated
user_type, decoupling authentication (the key) from authorization (the scope).
Existing keys default to no scopes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e0e882fba200"
down_revision: Union[str, None] = "8391583bd224"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "machine_user_keys",
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("machine_user_keys", "scopes")
