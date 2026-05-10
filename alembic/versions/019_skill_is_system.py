"""add is_system flag to skills

Revision ID: 019
Revises: 018
Create Date: 2026-05-09 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = '019'
down_revision: Union[str, None] = '018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'skills',
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false',
                  comment='True for skills seeded from source code. Immutable via API.'),
    )


def downgrade() -> None:
    op.drop_column('skills', 'is_system')
