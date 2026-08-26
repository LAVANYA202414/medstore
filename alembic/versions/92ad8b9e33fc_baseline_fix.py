"""baseline_fix

Revision ID: 92ad8b9e33fc
Revises: 
Create Date: 2026-08-25 16:31:18.633071

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92ad8b9e33fc'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

import sqlalchemy as sa
from alembic import op

def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create chat_topics first (since chat_history depends on it)
    op.create_table(
        'chat_topics',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # Add indexes for chat_topics
    op.create_index(op.f('ix_chat_topics_id'), 'chat_topics', ['id'], unique=False)
    op.create_index(op.f('ix_chat_topics_user_id'), 'chat_topics', ['user_id'], unique=False)
    
    # Add foreign key from chat_topics to users table
    op.create_foreign_key('fk_chat_topics_user_id', 'chat_topics', 'users', ['user_id'], ['id'])

    # 2. Now create the chat_history table
    op.create_table(
        'chat_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.Column('user_query', sa.Text(), nullable=False),
        sa.Column('response_type', sa.String(length=50), nullable=True),
        sa.Column('response_json', sa.Text(), nullable=True),
        sa.Column('products_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # Add indexes for chat_history
    op.create_index(op.f('ix_chat_history_user_id'), 'chat_history', ['user_id'], unique=False)
    op.create_index(op.f('ix_chat_history_topic_id'), 'chat_history', ['topic_id'], unique=False)

    # Add foreign keys for chat_history
    op.create_foreign_key('fk_chat_history_user_id', 'chat_history', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_chat_history_topic_id', 'chat_history', 'chat_topics', ['topic_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    # Drop chat_history components
    op.drop_constraint('fk_chat_history_topic_id', 'chat_history', type_='foreignkey')
    op.drop_constraint('fk_chat_history_user_id', 'chat_history', type_='foreignkey')
    op.drop_index(op.f('ix_chat_history_topic_id'), table_name='chat_history')
    op.drop_index(op.f('ix_chat_history_user_id'), table_name='chat_history')
    op.drop_table('chat_history')
    
    # Drop chat_topics components
    op.drop_constraint('fk_chat_topics_user_id', 'chat_topics', type_='foreignkey')
    op.drop_index(op.f('ix_chat_topics_user_id'), table_name='chat_topics')
    op.drop_index(op.f('ix_chat_topics_id'), table_name='chat_topics')
    op.drop_table('chat_topics')


