"""api_call purpose translate

Revision ID: a9cea2316fcd
Revises: c5f4a3d0f543
Create Date: 2026-10-27 12:20:18.567517

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9cea2316fcd'
down_revision: Union[str, Sequence[str], None] = 'c5f4a3d0f543'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD = "purpose in ('turn', 'title', 'spark', 'eval', 'judge')"
NEW = "purpose in ('turn', 'title', 'spark', 'translate', 'eval', 'judge')"


def upgrade() -> None:
    """Allow ledger rows for card translations."""
    op.drop_constraint("api_call_purpose_check", "api_call", type_="check")
    op.create_check_constraint("api_call_purpose_check", "api_call", NEW)


def downgrade() -> None:
    op.execute("delete from api_call where purpose = 'translate'")
    op.drop_constraint("api_call_purpose_check", "api_call", type_="check")
    op.create_check_constraint("api_call_purpose_check", "api_call", OLD)
