"""initial schema

Revision ID: 2a1a0c181a13
Revises: 
Create Date: 2026-10-25 18:12:48.491730

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.settings import DEFAULT_USER_ID

# revision identifiers, used by Alembic.
revision: str = '2a1a0c181a13'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("create extension if not exists vector")  # used from P2
    op.create_table('app_user',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.Text(), server_default='me', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('concept',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('slug', sa.Text(), nullable=False),
    sa.Column('explored', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'slug')
    )
    op.create_table('concept_link',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('a_concept_id', sa.UUID(), nullable=False),
    sa.Column('b_concept_id', sa.UUID(), nullable=False),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.Column('created_by', sa.Text(), server_default='user', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('a_concept_id < b_concept_id', name='concept_link_order_check'),
    sa.ForeignKeyConstraint(['a_concept_id'], ['concept.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['b_concept_id'], ['concept.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('a_concept_id', 'b_concept_id')
    )
    op.create_index('ix_concept_link_b_concept_id', 'concept_link', ['b_concept_id'], unique=False)
    op.create_table('thread',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('root_concept_id', sa.UUID(), nullable=True),
    sa.Column('current_concept_id', sa.UUID(), nullable=True),
    sa.Column('depth', sa.Text(), server_default='explain', nullable=False),
    sa.Column('archived', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_active_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("depth in ('glance', 'explain', 'mechanism', 'expert')", name='thread_depth_check'),
    sa.ForeignKeyConstraint(['current_concept_id'], ['concept.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['root_concept_id'], ['concept.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('interest_event',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('thread_id', sa.UUID(), nullable=True),
    sa.Column('concept_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['concept_id'], ['concept.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['thread.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_interest_event_user_ts', 'interest_event', ['user_id', 'ts'], unique=False)
    op.create_table('message',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('thread_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('card', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('concept_id', sa.UUID(), nullable=True),
    sa.Column('model', sa.Text(), nullable=True),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role in ('user', 'assistant')", name='message_role_check'),
    sa.ForeignKeyConstraint(['concept_id'], ['concept.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['thread.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('thread_id', 'seq')
    )
    op.create_index('ix_message_concept_id', 'message', ['concept_id'], unique=False)
    op.create_table('takeaway',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('thread_id', sa.UUID(), nullable=True),
    sa.Column('message_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind in ('takeaway', 'idea', 'question')", name='takeaway_kind_check'),
    sa.ForeignKeyConstraint(['message_id'], ['message.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['thread.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('takeaway_concept',
    sa.Column('takeaway_id', sa.UUID(), nullable=False),
    sa.Column('concept_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['concept_id'], ['concept.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['takeaway_id'], ['takeaway.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('takeaway_id', 'concept_id')
    )
    op.execute(f"insert into app_user (id, name) values ('{DEFAULT_USER_ID}', 'me')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('takeaway_concept')
    op.drop_table('takeaway')
    op.drop_index('ix_message_concept_id', table_name='message')
    op.drop_table('message')
    op.drop_index('ix_interest_event_user_ts', table_name='interest_event')
    op.drop_table('interest_event')
    op.drop_table('thread')
    op.drop_index('ix_concept_link_b_concept_id', table_name='concept_link')
    op.drop_table('concept_link')
    op.drop_table('concept')
    op.drop_table('app_user')
