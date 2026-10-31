"""message favourited_at

Revision ID: b3e1f5a7c902
Revises: a9cea2316fcd
Create Date: 2026-10-31 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3e1f5a7c902'
down_revision: Union[str, Sequence[str], None] = 'a9cea2316fcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('message', sa.Column('favourited_at', sa.DateTime(timezone=True), nullable=True))
    # The sidebar lists favourites newest first; only favourites are indexed.
    op.create_index(
        'ix_message_favourited_at', 'message', ['favourited_at'],
        postgresql_where=sa.text('favourited_at IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_message_favourited_at', table_name='message')
    op.drop_column('message', 'favourited_at')
